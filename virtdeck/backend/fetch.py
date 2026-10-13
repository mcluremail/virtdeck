"""FetchWorker — generic resource fetching for tree/panels."""

import logging
import threading

from PySide6.QtCore import QObject, QRunnable, Signal

from ..plugins import create_provider

logger = logging.getLogger(__name__)

class FetchSignals(QObject):
    result_ready = Signal(dict)
    finished = Signal()
class FetchWorker(QRunnable):
    """Fetches the node summary via QThreadPool.
    Independent API requests run in parallel via threading.Thread.

    Result status semantics (audit 4.1) — "absence of an answer is not the
    absence of resources":

    - ``ok``: every MANDATORY source completed successfully — its thread
      finished before the join deadline and raised nothing.  Empty lists
      at this point are a confirmed absence of resources (a valid empty
      snapshot), not a failure.
      Mandatory: cluster path — ``/cluster/resources``; standalone path —
      node status plus the qemu/lxc/storage listings.
    - ``partial``: the host identity is confirmed but a mandatory resource
      list failed or its thread outlived the join deadline.  The consumer
      must keep the previous snapshot of this host; ``data["error"]``
      names the missing sources.
    - ``error``: the mandatory core is unavailable entirely (no confirmed
      data at all).  The consumer keeps the previous snapshot and flags
      the host as errored.

    Optional sources — pools, HA groups, node versions, per-node storage
    details, ISO images — never affect the status: their failure only
    means their enrichment data is missing, which cannot be mistaken for
    resource removal.  A failed optional source omits its key (or keeps
    it empty) so stale UI data survives instead of being replaced by a
    fake "nothing".
    """

    def __init__(self, node_cfg):
        super().__init__()
        self.node_cfg = node_cfg
        self.signals = FetchSignals()
        self._cancelled = False
        # Join ceilings for the MANDATORY phases (tests shrink them)
        self.join_phase1 = 20
        self.join_standalone = 30

    def cancel(self):
        self._cancelled = True

    def run(self):
        provider = None
        try:
            provider = create_provider(self.node_cfg, timeout=15)
            cluster_api = provider.cluster
            pool_api = provider.pools
            node_api = provider.nodes
            vm_api = provider.vms
            storage_api = provider.storage

            if self._cancelled:
                return

            is_cluster_rep = self.node_cfg.get("cluster_rep", False)

        # -- Parallel phase 1: pools, HA groups, resources --
            vmid_to_pool = {}
            pools = []
            pools_failed = False
            ha_groups = []
            nodes = []
            vms = []
            storages = []
            cluster_name = ""
            node_name = ""

            pool_lock = threading.Lock()
            ha_lock = threading.Lock()
            res_lock = threading.Lock()
            # Failures of the MANDATORY core, filled by the worker threads:
            # core_errors — no confirmed data at all ("error"),
            # list_errors  — the host is confirmed, some resource lists are
            #                not ("partial").
            core_errors: list[str] = []
            list_errors: list[str] = []

            def fetch_pools():
                nonlocal vmid_to_pool, pools, pools_failed
                try:
                    pools_data = pool_api.list()
                    with pool_lock:
                        pools = [
                            {"poolid": p.get("poolid") or p.get("pool"),
                             "comment": p.get("comment", "") or ""}
                            for p in pools_data
                            if p.get("poolid") or p.get("pool")
                        ]

                    def fetch_pool_detail(p):
                        pname = p.get("poolid") or p.get("pool")
                        if not pname:
                            return
                        try:
                            pd = pool_api.get(pname)
                            members = pd.get("members") if isinstance(pd, dict) else None
                        except Exception:
                            members = p.get("members")
                        if not isinstance(members, list):
                            return
                        local = {}
                        for m in members:
                            mt = m.get("type")
                            mv = m.get("vmid")
                            if mt in ("qemu", "lxc") and mv is not None:
                                local[int(mv)] = pname
                        with pool_lock:
                            vmid_to_pool.update(local)
                    pool_candidates = [p for p in pools_data if p.get("poolid") or p.get("pool")]
                    pool_threads = [threading.Thread(target=fetch_pool_detail, args=(p,), daemon=True)
                                    for p in pool_candidates]
                    for t in pool_threads:
                        t.start()
                    for t in pool_threads:
                        t.join(timeout=10)
                except Exception as e:
                    # Optional source: signal "not fetched" (None) instead
                    # of a fake "no pools" so the consumer keeps the
                    # previous pool data of this host (audit 4.2, D2).
                    pools_failed = True
                    logger.debug("backend error: %s", e)

            def fetch_ha():
                nonlocal ha_groups
                try:
                    result = []
                    for g in cluster_api.list_ha_groups():
                        result.append({
                            "group": g.get("group", ""),
                            "nodes": g.get("nodes", ""),
                            "restricted": g.get("restricted", 0),
                            "nofailback": g.get("nofailback", 0),
                            "comment": g.get("comment", ""),
                            "digest": g.get("digest", ""),
                        })
                    result.sort(key=lambda x: x["group"])
                    with ha_lock:
                        ha_groups = result
                except Exception:
                    pass

            def fetch_resources():
                nonlocal nodes, vms, storages, cluster_name
                try:
                    resources = cluster_api.list_resources()
                    with res_lock:
                        nodes = [r for r in resources if r.get("type") == "node"]
                        vms = [r for r in resources if r.get("type") in ("qemu", "lxc")]
                        storages = [r for r in resources if r.get("type") == "storage"]
                        cluster_name = self.node_cfg.get("cluster", "")
                        for n in nodes:
                            short = n["node"]
                            n["_display_name"] = f"{short}@{cluster_name}" if cluster_name else short
                except Exception as e:
                    # mandatory: without /cluster/resources there is no
                    # confirmed snapshot at all
                    with res_lock:
                        core_errors.append(f"cluster resources: {e}")
                    logger.debug("backend error: %s", e)

            phase1 = []
            phase1.append(threading.Thread(target=fetch_pools, daemon=True))
            phase1.append(threading.Thread(target=fetch_ha, daemon=True))
            if is_cluster_rep:
                phase1.append(threading.Thread(target=fetch_resources, daemon=True))

            for t in phase1:
                t.start()
            for t in phase1:
                t.join(timeout=self.join_phase1)
            if self._cancelled:
                return
            if is_cluster_rep:
                # A thread outliving its join deadline means its data never
                # arrived — the core is not confirmed (audit 4.1: a timed
                # out thread must not be treated as a complete result).
                res_thread = phase1[2]
                if res_thread.is_alive():
                    with res_lock:
                        core_errors.append(
                            f"cluster resources did not finish "
                            f"in {self.join_phase1:g}s")

            # -- Parallel phase 2: storage details per node / standalone data --
            iso_images = {}
            iso_lock = threading.Lock()

            if is_cluster_rep:
                for n in nodes:
                    n["host_name"] = self.node_cfg["name"]
                for s in storages:
                    s["host_name"] = self.node_cfg["name"]
                    s["cluster"] = cluster_name

                # Pull used/total from each node in parallel
                detail_lock = threading.Lock()
                detail_by_node = {}

                def fetch_node_storage(n):
                    node_name = n["node"]
                    try:
                        node_storages = node_api.list_storage(node_name)
                        with detail_lock:
                            detail_by_node[node_name] = {
                                ds["storage"]: ds for ds in node_storages
                            }
                    except Exception:
                        with detail_lock:
                            detail_by_node[node_name] = {}

                storage_threads = [threading.Thread(target=fetch_node_storage, args=(n,), daemon=True)
                                   for n in nodes]
                for t in storage_threads:
                    t.start()
                for t in storage_threads:
                    t.join(timeout=20)
                if self._cancelled:
                    return

                # Pull versions from each node in parallel
                version_lock = threading.Lock()

                def fetch_node_version(n):
                    node_name = n["node"]
                    try:
                        ver = node_api.get_version(node_name)
                        with version_lock:
                            qemu = ver.get("qemu")
                            if qemu:
                                n["qemu"] = qemu
                            lxc = ver.get("lxc")
                            if lxc:
                                n["lxctype"] = lxc
                    except Exception:
                        pass
                    # pveversion and kernel from node status
                    try:
                        st = node_api.get_status(node_name)
                        with version_lock:
                            pve = st.get("pveversion")
                            if pve:
                                n["pveversion"] = pve
                                # M0.5: node versions for the compat matrix
                                provider.report_version(node_name, pve)
                            n["kernel"] = st.get("kversion", "")
                    except Exception:
                        pass

                ver_threads = [threading.Thread(target=fetch_node_version, args=(n,), daemon=True)
                              for n in nodes]
                for t in ver_threads:
                    t.start()
                for t in ver_threads:
                    t.join(timeout=10)
                if self._cancelled:
                    return

                for s in storages:
                    detail = detail_by_node.get(s.get("node", ""), {}).get(s.get("storage", ""), {})
                    if detail.get("used") is not None and (s.get("used") or 0) == 0:
                        s["used"] = detail["used"]
                    if detail.get("total") is not None and (s.get("total") or 0) == 0:
                        s["total"] = detail["total"]
                    if detail.get("avail") is not None and (s.get("avail") or 0) == 0:
                        s["avail"] = detail["avail"]
                for vm in vms:
                    if not vm.get("pool"):
                        vm["pool"] = vmid_to_pool.get(vm["vmid"])
            else:
                # Standalone: get the node name and data in parallel
                def fetch_standalone():
                    nonlocal node_name, nodes, vms, storages
                    try:
                        local_nodes = node_api.list()
                        nn = local_nodes[0].get("node") if local_nodes else self.node_cfg["name"]
                    except Exception:
                        nn = self.node_cfg["name"]
                    node_name = nn
                    try:
                        node_status = node_api.get_status(node_name)
                        # M0.5: node version for the compat matrix
                        provider.report_version(node_name,
                                                node_status.get("pveversion"))
                    except Exception as e:
                        # Mandatory: without the node status there is no
                        # confirmed snapshot at all. Surface the failure as
                        # an error node instead of silently emitting an
                        # empty "ok" result.
                        with res_lock:
                            core_errors.append(f"node status: {e}")
                            nodes = [{
                                "node": self.node_cfg["name"],
                                "host_name": self.node_cfg["name"],
                                "_display_name": self.node_cfg["name"],
                                "status": "error",
                                "error": str(e),
                            }]
                        return
                    # /nodes/{node}/status returns nested dicts (memory,
                    # rootfs, cpuinfo); flatten to the flat keys Node.from_pve
                    # expects (same shape as /cluster/resources entries).
                    mem_info = node_status.get("memory") or {}
                    rootfs_info = node_status.get("rootfs") or {}
                    cpuinfo = node_status.get("cpuinfo") or {}
                    with res_lock:
                        nodes = [{**node_status, "node": node_name,
                                  "_display_name": self.node_cfg["name"],
                                  "host_name": self.node_cfg["name"],
                                  "status": "online",
                                  "mem": mem_info.get("used", 0) or 0,
                                  "maxmem": mem_info.get("total", 0) or 0,
                                  "disk": rootfs_info.get("used", 0) or 0,
                                  "maxdisk": rootfs_info.get("total", 0) or 0,
                                  "sockets": cpuinfo.get("sockets", 0) or 0}]
                    try:
                        qemu_list = vm_api.list_qemu(node_name)
                        lxc_list = vm_api.list_lxc(node_name)
                        vms_local = []
                        for v in qemu_list:
                            vms_local.append({**v, "type": "qemu",
                                              "node": node_name,
                                              "host_name": self.node_cfg["name"],
                                              "pool": vmid_to_pool.get(v.get("vmid"))})
                        for v in lxc_list:
                            vms_local.append({**v, "type": "lxc",
                                              "node": node_name,
                                              "host_name": self.node_cfg["name"],
                                              "pool": vmid_to_pool.get(v.get("vmid"))})
                        storages_local = list(node_api.list_storage(node_name))
                        for st in storages_local:
                            st["node"] = node_name
                            st["host_name"] = self.node_cfg["name"]
                            st["cluster"] = ""
                        with res_lock:
                            vms = vms_local
                            storages = storages_local
                    except Exception as e:
                        # Mandatory lists: their failure must not look like
                        # a confirmed absence of VMs/storages — mark the
                        # snapshot partial (the node itself is confirmed).
                        with res_lock:
                            list_errors.append(f"guest/storage lists: {e}")
                        logger.debug("backend error: %s", e)

                standalone_thread = threading.Thread(target=fetch_standalone, daemon=True)
                standalone_thread.start()
                if self._cancelled:
                    return
                standalone_thread.join(timeout=self.join_standalone)
                if standalone_thread.is_alive():
                    with res_lock:
                        core_errors.append(
                            f"standalone node data did not finish "
                            f"in {self.join_standalone:g}s")

                # Re-apply pool after the pool threads finish
                # (fetch_pools may still be running when fetch_standalone
                # has already taken the vms)
                for vm in vms:
                    if not vm.get("pool"):
                        vm["pool"] = vmid_to_pool.get(vm.get("vmid"))

                # Versions for the standalone node (pveversion/kernel are
                # already in node_status)
                if nodes:
                    try:
                        ver = node_api.get_version(node_name)
                        qemu = ver.get("qemu")
                        if qemu:
                            for n in nodes:
                                n["qemu"] = qemu
                        lxc = ver.get("lxc")
                        if lxc:
                            for n in nodes:
                                n["lxctype"] = lxc
                    except Exception:
                        pass

            # -- Parallel phase 3: ISO images --
            def fetch_iso_for_node(n):
                nname = n["node"]
                nhost = n.get("host_name", "")
                iso_storages = [
                    s["storage"] for s in storages
                    if s.get("node") == nname
                    and s.get("host_name") == nhost
                    and "iso" in (s.get("content", "") or "").split(",")
                ]
                if not iso_storages:
                    with iso_lock:
                        iso_images[nhost] = []
                    return
                try:
                    seen = {}
                    for sname in iso_storages:
                        for item in storage_api.list_content(nname, sname, content="iso"):
                            if item.get("content") == "iso":
                                volid = item["volid"]
                                if volid not in seen:
                                    seen[volid] = {
                                        "volid": volid,
                                        "format": item.get("format", ""),
                                        "size": item.get("size", 0),
                                    }
                    with iso_lock:
                        iso_images[nhost] = sorted(seen.values(), key=lambda x: x["volid"])
                except Exception:
                    # Optional source: omit the key so the consumer keeps
                    # the previous ISO list instead of a fake "no ISOs".
                    logger.debug("iso listing failed for %s", nhost, exc_info=True)

            if self._cancelled:
                return
            iso_threads = [threading.Thread(target=fetch_iso_for_node, args=(n,), daemon=True)
                           for n in nodes]
            for t in iso_threads:
                t.start()
            for t in iso_threads:
                t.join(timeout=15)

            if self._cancelled:
                return

            # -- Emit result --
            # pools is None when the optional pool source failed (consumer
            # keeps the previous data); [] is a confirmed absence.
            # conn_id (stage 5.1.2): the producer identity travels with the
            # result; the consumer drops results of unknown/deleted
            # connections before touching any state.
            emitted_pools = None if pools_failed else pools
            if core_errors:
                # No confirmed data at all.
                self.signals.result_ready.emit({
                    "host": self.node_cfg["name"],
                    "conn_id": self.node_cfg.get("conn_id", ""),
                    "status": "error",
                    "error": "; ".join(core_errors),
                })
            elif list_errors:
                # The host is confirmed, some mandatory resource lists are
                # not: the consumer must keep the previous snapshot.
                self.signals.result_ready.emit({
                    "host": self.node_cfg["name"],
                    "conn_id": self.node_cfg.get("conn_id", ""),
                    "status": "partial",
                    "error": "incomplete snapshot — " + "; ".join(list_errors),
                    "nodes": nodes,
                    "vms": vms,
                    "storages": storages,
                    "pools": emitted_pools,
                    "iso_images": iso_images,
                    "ha_groups": ha_groups,
                })
            else:
                self.signals.result_ready.emit({
                    "host": self.node_cfg["name"],
                    "conn_id": self.node_cfg.get("conn_id", ""),
                    "status": "ok",
                    "nodes": nodes,
                    "vms": vms,
                    "storages": storages,
                    "pools": emitted_pools,
                    "iso_images": iso_images,
                    "ha_groups": ha_groups
                })
        except Exception as e:
            try:
                self.signals.result_ready.emit({
                    "host": self.node_cfg["name"],
                    "conn_id": self.node_cfg.get("conn_id", ""),
                    "status": "error",
                    "error": str(e)
                })
            except RuntimeError:
                pass
        finally:
            if provider:
                provider.close()
            try:
                self.signals.finished.emit()
            except RuntimeError:
                pass

# ----------------------------------------------------------------------
# VmDetailWorker (unchanged)
# ----------------------------------------------------------------------
