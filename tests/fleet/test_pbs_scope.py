"""Fleet Health PBS scoping: bindings extraction and evidence selection.

Pure level (no sockets, no Qt): pins the scoping rules of audit D5 —
per-cluster evidence by storage-config bindings, confirmed absence vs
missing data, conservative handling of shared sources with intersecting
guest identifiers.
"""

from __future__ import annotations

from virtdeck.fleet.pbs_scope import (
    SCOPE_AMBIGUOUS,
    SCOPE_OK,
    SCOPE_UNAVAILABLE,
    PbsBinding,
    bindings_from_storage_configs,
    select_pbs_evidence,
)
from virtdeck.fleet.pbs_source import PbsEvidence

PBS_A = ("pbs-a.local", 8007)
PBS_B = ("pbs-b.local", 8007)


def ev(sources: dict, collected: set | None = None,
       failed_stores: set | None = None) -> PbsEvidence:
    return PbsEvidence(
        by_source=sources,
        collected_stores=collected if collected is not None
        else {(host, port, ds) for (host, port, ds, _ns) in sources},
        failed_stores=failed_stores or set())


def bind(server, datastore, namespace="", storage_id="pbs-x"):
    return PbsBinding(server=server, datastore=datastore,
                      namespace=namespace, storage_id=storage_id)


# ── bindings_from_storage_configs ────────────────────────────────────


def test_bindings_extract_pbs_rows_only():
    rows = [
        {"storage": "local", "type": "dir", "path": "/var/lib/vz"},
        {"storage": "pbs1", "type": "pbs", "server": "PBS-A.local",
         "datastore": "main", "password": "s3cret"},
        {"storage": "pbs2", "type": "pbs", "server": "pbs-b.local",
         "port": 8008, "datastore": "vault", "namespace": "tenant1"},
    ]
    bindings, problems = bindings_from_storage_configs(rows)
    assert problems == []
    assert bindings == [
        bind(PBS_A, "main", storage_id="pbs1"),
        bind(("pbs-b.local", 8008), "vault", "tenant1", storage_id="pbs2"),
    ]


def test_bindings_missing_datastore_rejected_no_guessing():
    rows = [{"storage": "pbs1", "type": "pbs", "server": "pbs-a.local"}]
    bindings, problems = bindings_from_storage_configs(rows)
    assert bindings == []
    assert problems == ["storage 'pbs1': datastore missing"]


def test_bindings_missing_server_rejected():
    rows = [{"storage": "pbs1", "type": "pbs", "datastore": "main"}]
    bindings, problems = bindings_from_storage_configs(rows)
    assert bindings == []
    assert problems == ["storage 'pbs1': server missing"]


def test_bindings_namespace_absent_is_root():
    rows = [{"storage": "pbs1", "type": "pbs", "server": "pbs-a.local",
             "datastore": "main"}]
    bindings, _problems = bindings_from_storage_configs(rows)
    assert bindings[0].namespace == ""


def test_bindings_bad_port_rejected():
    rows = [{"storage": "pbs1", "type": "pbs", "server": "pbs-a.local",
             "port": "abc", "datastore": "main"}]
    bindings, problems = bindings_from_storage_configs(rows)
    assert bindings == []
    assert problems == ["storage 'pbs1': invalid server port"]


def test_bindings_problems_never_carry_secrets():
    """T14 (extraction half): a problem message names the storage id,
    never the row contents (rows may contain password)."""
    rows = [{"storage": "p", "type": "pbs", "server": "s",
             "password": "top-secret-pw"}]
    _bindings, problems = bindings_from_storage_configs(rows)
    assert all("top-secret-pw" not in p for p in problems)


# ── select_pbs_evidence ──────────────────────────────────────────────


def test_no_pbs_configured_is_ok_and_empty():
    scopes = select_pbs_evidence(None, {"a": [bind(PBS_A, "main")]}, {})
    assert scopes["a"].status == SCOPE_OK
    assert scopes["a"].flat == {}


def test_t1_same_vmid_different_datastores():
    """Two clusters, same VMID, different datastores: each gets only its
    own evidence (the D5 false-credit is gone)."""
    sources = {
        (*PBS_A, "main", ""): {("vm", "101"): 1000},
        (*PBS_B, "main", ""): {("vm", "101"): 2000},
    }
    scopes = select_pbs_evidence(
        ev(sources),
        {"alpha": [bind(PBS_A, "main")], "beta": [bind(PBS_B, "main")]},
        {"alpha": {("vm", "101")}, "beta": {("vm", "101")}},
    )
    assert scopes["alpha"].flat == {("vm", "101"): 1000}
    assert scopes["beta"].flat == {("vm", "101"): 2000}
    assert scopes["alpha"].status == scopes["beta"].status == SCOPE_OK


def test_t2_same_vmid_same_datastore_different_namespaces():
    sources = {
        (*PBS_A, "main", ""): {("vm", "101"): 1000},
        (*PBS_A, "main", "tenant1"): {("vm", "101"): 2000},
    }
    scopes = select_pbs_evidence(
        ev(sources),
        {"alpha": [bind(PBS_A, "main", "")],
         "beta": [bind(PBS_A, "main", "tenant1")]},
        {"alpha": {("vm", "101")}, "beta": {("vm", "101")}},
    )
    assert scopes["alpha"].flat == {("vm", "101"): 1000}
    assert scopes["beta"].flat == {("vm", "101"): 2000}
    assert all(s.status == SCOPE_OK for s in scopes.values())


def test_t3_several_stores_of_one_cluster_merge():
    sources = {
        (*PBS_A, "main", ""): {("vm", "101"): 1000},
        (*PBS_B, "vault", ""): {("vm", "101"): 2000, ("lxc", "301"): 500},
    }
    scopes = select_pbs_evidence(
        ev(sources),
        {"alpha": [bind(PBS_A, "main"), bind(PBS_B, "vault")]},
        {"alpha": {("vm", "101"), ("lxc", "301")}},
    )
    assert scopes["alpha"].flat == {("vm", "101"): 2000, ("lxc", "301"): 500}
    assert scopes["alpha"].status == SCOPE_OK


def test_t4_shared_source_intersecting_vmid_dropped_both():
    """One (server, datastore, ns) referenced by two clusters with the
    same VMID: the snapshot cannot be attributed — dropped for both,
    status ambiguous with an explanation."""
    sources = {(*PBS_A, "main", ""): {("vm", "101"): 1000}}
    scopes = select_pbs_evidence(
        ev(sources),
        {"alpha": [bind(PBS_A, "main")], "beta": [bind(PBS_A, "main")]},
        {"alpha": {("vm", "101")}, "beta": {("vm", "101")}},
    )
    for name in ("alpha", "beta"):
        assert scopes[name].flat == {}
        assert scopes[name].status == SCOPE_AMBIGUOUS
        assert any("ambiguous" in r for r in scopes[name].reasons)


def test_t4b_shared_source_non_intersecting_guests_kept():
    """Rule 8: a shared source without identifier intersection is not
    an error — evidence stays valid."""
    sources = {(*PBS_A, "main", ""): {("vm", "101"): 1000,
                                      ("vm", "201"): 2000}}
    scopes = select_pbs_evidence(
        ev(sources),
        {"alpha": [bind(PBS_A, "main")], "beta": [bind(PBS_A, "main")]},
        {"alpha": {("vm", "101")}, "beta": {("vm", "201")}},
    )
    assert scopes["alpha"].flat == {("vm", "101"): 1000}
    assert scopes["beta"].flat == {("vm", "201"): 2000}
    assert all(s.status == SCOPE_OK for s in scopes.values())


def test_rule8_residual_risk_vmid_reuse_after_deletion():
    """Documented residual risk (owner-confirmed, 2026-10-15): a guest
    vm/101 deleted in cluster A and recreated in cluster B, both writing
    to the same (server, datastore, ns). The intersection is checked
    against the CURRENT guest composition (rule 8): the recreated guest
    keeps the source's evidence — which may be the pre-deletion snapshot
    of the other cluster. This is not decidable from the metadata VirtDeck
    consumes (type/id/time/verify; PBS owner-auth was ruled unreliable in
    audit 6.2.2) and no heuristic is invented: the remedy is
    configuration-level — separate datastores or namespaces per cluster.
    Pinned here as deliberate behavior, not an oversight."""
    sources = {(*PBS_A, "main", ""): {("vm", "101"): 1000}}
    scopes = select_pbs_evidence(
        ev(sources),
        {"alpha": [bind(PBS_A, "main")], "beta": [bind(PBS_A, "main")]},
        {"alpha": {("vm", "202")}, "beta": {("vm", "101")}},
    )
    # rule 8: no identifier intersection → the shared source is not
    # invalidated; beta is credited with the (possibly foreign) snapshot
    assert scopes["beta"].flat == {("vm", "101"): 1000}
    assert scopes["beta"].status == SCOPE_OK
    assert scopes["alpha"].flat == {}


def test_t5_binding_without_namespace_matches_root():
    sources = {(*PBS_A, "main", ""): {("vm", "101"): 1000}}
    scopes = select_pbs_evidence(
        ev(sources), {"alpha": [bind(PBS_A, "main", "")]},
        {"alpha": {("vm", "101")}},
    )
    assert scopes["alpha"].flat == {("vm", "101"): 1000}


def test_t6_invalid_binding_unverified():
    """A binding that could not be built (missing datastore) → the
    cluster's PBS state is unverified, not silently empty-ok."""
    scopes = select_pbs_evidence(
        ev({(*PBS_A, "main", ""): {("vm", "101"): 1000}}),
        {"alpha": ()},
        {"alpha": {("vm", "101")}},
        cluster_problems={"alpha": ["storage 'pbs1': datastore missing"]},
    )
    assert scopes["alpha"].status == SCOPE_UNAVAILABLE
    assert scopes["alpha"].flat == {}
    assert tuple(scopes["alpha"].reasons) == \
        ("storage 'pbs1': datastore missing",)


def test_t7_bindings_none_unavailable():
    scopes = select_pbs_evidence(
        ev({(*PBS_A, "main", ""): {("vm", "101"): 1000}}),
        {"alpha": None, "beta": [bind(PBS_A, "main")]},
        {"alpha": {("vm", "101")}, "beta": {("vm", "101")}},
    )
    assert scopes["alpha"].status == SCOPE_UNAVAILABLE
    assert scopes["alpha"].flat == {}
    # an independent cluster is processed normally
    assert scopes["beta"].status == SCOPE_OK
    assert scopes["beta"].flat == {("vm", "101"): 1000}


def test_t8_failed_store_keeps_other_sources_unverified():
    """One PBS source down: its evidence is missing (not an absence),
    evidence of other sources is kept, status stays unverified."""
    sources = {(*PBS_B, "vault", ""): {("vm", "101"): 2000}}
    scopes = select_pbs_evidence(
        ev(sources, collected={(PBS_B[0], PBS_B[1], "vault")},
           failed_stores={(PBS_A[0], PBS_A[1], "main")}),
        {"alpha": [bind(PBS_A, "main"), bind(PBS_B, "vault")]},
        {"alpha": {("vm", "101"), ("vm", "102")}},
    )
    assert scopes["alpha"].status == SCOPE_UNAVAILABLE
    assert scopes["alpha"].flat == {("vm", "101"): 2000}
    assert any("pbs-a.local:8007/main unavailable" in r
               for r in scopes["alpha"].reasons)


def test_t9_confirmed_absence_is_ok():
    """Store collected, namespace empty → the absence of a snapshot is
    confirmed (status ok; red states may follow from task evidence)."""
    scopes = select_pbs_evidence(
        ev({}, collected={(PBS_A[0], PBS_A[1], "main")}),
        {"alpha": [bind(PBS_A, "main")]},
        {"alpha": {("vm", "101")}},
    )
    assert scopes["alpha"].status == SCOPE_OK
    assert scopes["alpha"].flat == {}


def test_t11_port_and_case_normalize():
    from virtdeck.fleet.pbs_source import server_key
    sources = {(*PBS_A, "main", ""): {("vm", "101"): 1000}}
    # bindings are normalized at extraction time (server_key: lower-case
    # host, explicit port) — the selector matches literal keys
    b = PbsBinding(server=server_key("PBS-A.LOCAL", 8007), datastore="main")
    scopes = select_pbs_evidence(
        ev(sources), {"alpha": [b]}, {"alpha": {("vm", "101")}},
    )
    assert scopes["alpha"].status == SCOPE_OK
    assert scopes["alpha"].flat == {("vm", "101"): 1000}
    # a different port is a different server — no cross-credit
    scopes2 = select_pbs_evidence(
        ev(sources),
        {"alpha": [bind(("pbs-a.local", 8008), "main")]},
        {"alpha": {("vm", "101")}},
    )
    assert scopes2["alpha"].flat == {}
    assert scopes2["alpha"].status == SCOPE_UNAVAILABLE


def test_t12_fqdn_vs_ip_not_equated():
    sources = {(*PBS_A, "main", ""): {("vm", "101"): 1000}}
    scopes = select_pbs_evidence(
        ev(sources), {"alpha": [bind(("192.168.1.10", 8007), "main")]},
        {"alpha": {("vm", "101")}},
    )
    assert scopes["alpha"].flat == {}
    assert scopes["alpha"].status == SCOPE_UNAVAILABLE


def test_t15_one_store_failed_others_count():
    """A broken datastore of a multi-store cluster does not destroy the
    evidence of the healthy ones (rule 9)."""
    sources = {(*PBS_B, "vault", ""): {("vm", "101"): 2000}}
    scopes = select_pbs_evidence(
        ev(sources, collected={(PBS_B[0], PBS_B[1], "vault")},
           failed_stores={(PBS_A[0], PBS_A[1], "main")}),
        {"alpha": [bind(PBS_A, "main"), bind(PBS_B, "vault")]},
        {"alpha": {("vm", "101")}},
    )
    assert scopes["alpha"].flat == {("vm", "101"): 2000}
    assert scopes["alpha"].status == SCOPE_UNAVAILABLE


def test_ambiguity_partial_when_unambiguous_store_also_matches():
    """A guest with evidence from an ambiguous AND an unambiguous
    source keeps the unambiguous time (no unjustified data loss)."""
    sources = {
        (*PBS_A, "main", ""): {("vm", "101"): 9000},    # shared → suspect
        (*PBS_B, "vault", ""): {("vm", "101"): 1000},   # own → trustworthy
    }
    scopes = select_pbs_evidence(
        ev(sources),
        {"alpha": [bind(PBS_A, "main"), bind(PBS_B, "vault")],
         "beta": [bind(PBS_A, "main")]},
        {"alpha": {("vm", "101")}, "beta": {("vm", "101")}},
    )
    # the fresher shared-source time must NOT win over the own one
    assert scopes["alpha"].flat == {("vm", "101"): 1000}
    assert scopes["alpha"].status == SCOPE_AMBIGUOUS


def test_ambiguous_reason_lists_guests_compactly():
    from virtdeck.fleet.pbs_scope import _ambiguous_reason
    dropped = [("vm", str(100 + i)) for i in range(12)]
    reason = _ambiguous_reason(dropped)
    assert "… +4 more" in reason
    assert reason.startswith("shared PBS source, ambiguous guests: vm/100")
