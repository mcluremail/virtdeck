"""M4.4: snapshot sprawl — агрегация и скан с лимитом параллелизма."""

from __future__ import annotations

from tests.harness import fake_pve_cfg, install_fake_pve
from tests.harness.scenarios import make_pve_cluster
from virtdeck.domain.backup_coverage import Guest
from virtdeck.fleet.sprawl import fetch_snapshots, scan_sprawl

NOW = 1727830000
DAY = 86400


def guest(vmid: int, node: str = "pve01", vm_type: str = "qemu",
          template: bool = False) -> Guest:
    return Guest(vmid=vmid, node=node, vm_type=vm_type, template=template)


def snap(name: str, age_days: float | None = 1.0) -> dict:
    entry: dict = {"name": name}
    if age_days is not None:
        entry["snaptime"] = int(NOW - age_days * DAY)
    return entry


class TestScanSprawl:
    def test_fresh_vs_stale(self):
        snapshots = {101: [snap("yesterday", 1.0),
                           snap("old", 45.0)]}
        scan = scan_sprawl(snapshots, [guest(101)], now=NOW,
                           stale_days=30)
        assert len(scan.guests) == 1
        row = scan.guests[0]
        assert row.count == 2
        assert row.stale_names == ("old",)
        assert row.oldest_time == int(NOW - 45 * DAY)
        assert row.has_stale

    def test_current_and_zombie(self):
        snapshots = {101: [snap("current", None), snap("good", 2.0),
                           {"name": "broken"}]}
        scan = scan_sprawl(snapshots, [guest(101)], now=NOW)
        row = scan.guests[0]
        assert row.count == 2  # current исключён
        assert row.zombie_names == ("broken",)
        assert "broken" in row.stale_names  # зомби — тоже забытое

    def test_no_snapshots_guest_absent(self):
        scan = scan_sprawl({101: [snap("current", None)]},
                           [guest(101)], now=NOW)
        assert scan.guests == ()
        scan = scan_sprawl({}, [guest(101)], now=NOW)
        assert scan.guests == ()

    def test_ordering_stale_first_by_oldest(self):
        snapshots = {
            101: [snap("fresh", 2.0)],                  # без stale
            102: [snap("a", 40.0)],                     # stale, моложе
            103: [snap("b", 90.0), snap("c", 35.0)],    # stale, старейший
        }
        guests = [guest(101), guest(102), guest(103)]
        scan = scan_sprawl(snapshots, guests, now=NOW)
        assert [r.vmid for r in scan.guests] == [103, 102, 101]
        assert scan.guests[0].stale_names == ("b", "c")

    def test_unknown_guest_keeps_vmid(self):
        """Снапшоты есть, гостя нет в resources (удалён) — строка остаётся."""
        scan = scan_sprawl({999: [snap("old", 60.0)]}, [], now=NOW)
        assert scan.guests[0].vmid == 999
        assert scan.guests[0].node == ""


class TestFetchSnapshots:
    def test_fetch_over_harness(self, monkeypatch):
        api = make_pve_cluster("alpha")
        install_fake_pve(monkeypatch, api)
        from virtdeck.provider import ProxmoxProvider
        with ProxmoxProvider(fake_pve_cfg("alpha")) as provider:
            guests = [Guest(101, "web01", "pve01", "qemu"),
                      Guest(301, "cache01", "pve02", "lxc"),
                      Guest(201, "tmpl", "pve02", "qemu", template=True)]
            result = fetch_snapshots(provider, guests, concurrency=2)
        # шаблон пропущен; у 301 снапшотов нет — его нет в результате
        assert set(result) == {101}
        assert result[101][0]["name"] == "pre-upgrade"

    def test_error_isolated_per_vm(self, monkeypatch):
        api = make_pve_cluster("alpha")
        api.fail["nodes/pve01/qemu/101/snapshot"] = (500, "boom")
        install_fake_pve(monkeypatch, api)
        from virtdeck.provider import ProxmoxProvider
        with ProxmoxProvider(fake_pve_cfg("alpha")) as provider:
            guests = [Guest(101, "web01", "pve01", "qemu"),
                      Guest(102, "db01", "pve01", "qemu")]
            progress: list[tuple[int, int]] = []
            result = fetch_snapshots(provider, guests, concurrency=1,
                                     on_progress=lambda d, t:
                                     progress.append((d, t)))
        assert 101 not in result and 102 not in result  # 102 без снапшотов
        assert progress  # прогресс вызывался
        assert progress[-1] == (2, 2)  # обработаны оба, включая упавший

    def test_empty_targets(self, monkeypatch):
        api = make_pve_cluster("alpha")
        install_fake_pve(monkeypatch, api)
        from virtdeck.provider import ProxmoxProvider
        with ProxmoxProvider(fake_pve_cfg("alpha")) as provider:
            assert fetch_snapshots(provider, []) == {}
            assert fetch_snapshots(provider, [guest(201, template=True)]) \
                == {}
