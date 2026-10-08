"""Shared pytest fixtures for UI tests."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def _isolate_xdg(tmp_path, monkeypatch):
    """Isolate user directories: tests must not touch the real
    ~/.config/virtdeck (config.sqlite, i18n cache, etc.). Regression
    from the 2026-09-09 audit."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))


@pytest.fixture
def make_node():
    """Factory fixture for building Node domain objects."""
    from virtdeck.domain.enums import NodeStatus
    from virtdeck.domain.node import Node

    def _make(
        host_name="h1",
        node="n1",
        cluster="",
        status=NodeStatus.ONLINE,
        cpu_fraction=0.5,
        cpu_sockets=2,
        mem_bytes=8 * 1024**3,
        maxmem_bytes=16 * 1024**3,
        disk_bytes=10 * 1024**3,
        maxdisk_bytes=100 * 1024**3,
        uptime_seconds=3600,
        **kwargs,
    ):
        return Node(
            host_name=host_name,
            node=node,
            cluster=cluster,
            status=status,
            error=kwargs.get("error", ""),
            cpu_fraction=cpu_fraction,
            cpu_sockets=cpu_sockets,
            mem_bytes=mem_bytes,
            maxmem_bytes=maxmem_bytes,
            disk_bytes=disk_bytes,
            maxdisk_bytes=maxdisk_bytes,
            uptime_seconds=uptime_seconds,
            pve_version_raw=kwargs.get("pve_version_raw", "pve-manager/8.2.4/abc"),
            kernel_version=kwargs.get("kernel_version", "6.8.12"),
            qemu_version=kwargs.get("qemu_version", "9.0.0"),
            lxc_version=kwargs.get("lxc_version", "6.0.0"),
            is_cluster=kwargs.get("is_cluster", False),
        )

    return _make


@pytest.fixture
def make_vm():
    """Factory fixture for building Vm domain objects."""
    from virtdeck.domain.enums import VmStatus, VmType
    from virtdeck.domain.vm import Vm

    def _make(
        vmid=100,
        name="test-vm",
        vm_type=VmType.QEMU,
        node="n1",
        host_name="h1",
        pool="",
        status=VmStatus.RUNNING,
        hastate="",
        tags="",
        template=False,
        cpu_fraction=0.3,
        mem_bytes=2 * 1024**3,
        maxmem_bytes=4 * 1024**3,
        disk_bytes=0,
        maxdisk_bytes=0,
        uptime_seconds=600,
        **kwargs,
    ):
        return Vm(
            vmid=vmid,
            name=name,
            vm_type=vm_type,
            node=node,
            host_name=host_name,
            pool=pool,
            status=status,
            hastate=hastate,
            tags=tags,
            template=template,
            cpu_fraction=cpu_fraction,
            mem_bytes=mem_bytes,
            maxmem_bytes=maxmem_bytes,
            disk_bytes=disk_bytes,
            maxdisk_bytes=maxdisk_bytes,
            uptime_seconds=uptime_seconds,
            netin_bytes=kwargs.get("netin_bytes", 0),
            netout_bytes=kwargs.get("netout_bytes", 0),
            diskread_bytes=kwargs.get("diskread_bytes", 0),
            diskwrite_bytes=kwargs.get("diskwrite_bytes", 0),
        )

    return _make


@pytest.fixture
def make_storage():
    """Factory fixture for building Storage domain objects."""
    from virtdeck.domain.storage import Storage

    def _make(
        storage="local",
        node="n1",
        host_name="h1",
        cluster="",
        storage_type="dir",
        content="images,iso",
        used_bytes=10 * 1024**3,
        total_bytes=100 * 1024**3,
        avail_bytes=90 * 1024**3,
        shared=False,
    ):
        return Storage(
            storage=storage,
            node=node,
            host_name=host_name,
            cluster=cluster,
            storage_type=storage_type,
            content=content,
            used_bytes=used_bytes,
            total_bytes=total_bytes,
            avail_bytes=avail_bytes,
            shared=shared,
        )

    return _make
