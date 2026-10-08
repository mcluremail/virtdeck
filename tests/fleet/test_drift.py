"""M4.3: version drift — lag-level table and sorting."""

from __future__ import annotations

from virtdeck.fleet.drift import detect_drift

V824 = "pve-manager/8.2.4/a1b2c3d4e5f6"
V821 = "pve-manager/8.2.1/1a2b3c4d5e6f"
V810 = "pve-manager/8.1.0/1a2b3c4d5e6f"
V743 = "pve-manager/7.4.3/1a2b3c4d5e6f"


def test_empty_mapping():
    assert detect_drift({}) == ()


def test_all_equal_all_ok():
    rows = detect_drift({"pve01": V824, "pve02": V824})
    assert all(r.level == "ok" for r in rows)
    assert all(r.newest_node == "pve01" for r in rows)


def test_mixed_levels_and_ordering():
    """Order: major → unknown → patch → ok; patch by name."""
    rows = detect_drift({
        "pve-a": V824,     # ok
        "pve-b": V810,     # minor
        "pve-c": V821,     # patch
        "pve-d": "8.2.3",  # patch (parser accepts the short form)
        "pve-e": "garbage",
        "pve-f": V743,     # major
    })
    by_node = {r.node: r for r in rows}
    assert by_node["pve-a"].level == "ok"
    assert by_node["pve-b"].level == "minor"
    assert by_node["pve-c"].level == "patch"
    assert by_node["pve-d"].level == "patch"
    assert by_node["pve-e"].level == "unknown"
    assert by_node["pve-f"].level == "major"
    assert [r.node for r in rows] == [
        "pve-f", "pve-b", "pve-e", "pve-c", "pve-d", "pve-a"]
    # each row lists the cluster leader
    assert by_node["pve-f"].newest_node == "pve-a"
    assert by_node["pve-f"].newest_version == V824


def test_unknown_keeps_raw_version():
    rows = detect_drift({"pve-x": "8.x"})
    assert rows[0].level == "unknown"
    assert rows[0].version == "8.x"
    assert rows[0].newest_node == ""


def test_only_unparsable_all_unknown():
    rows = detect_drift({"pve-x": "wtf", "pve-y": ""})
    assert [r.level for r in rows] == ["unknown", "unknown"]
    assert rows[0].newest_version == ""


def test_short_form_versions():
    rows = detect_drift({"pve-a": "8.2", "pve-b": "8.2.4"})
    # '8.2' → 8.2.0 → patch relative to 8.2.4
    by_node = {r.node: r for r in rows}
    assert by_node["pve-a"].level == "patch"
    assert by_node["pve-b"].level == "ok"
