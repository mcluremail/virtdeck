"""M0.5: PVE version parsing and the feature compat matrix."""

import pytest

from virtdeck.domain import compat
from virtdeck.domain.compat import (
    PVE_FEATURES,
    PveVersion,
    parse_pve_version,
    register_feature,
    supports,
)


class TestParsePveVersion:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("pve-manager/8.2.4/1ac2f4b0f", (8, 2, 4)),
            ("pve-manager/7.4-3/0615a192", (7, 4, 3)),  # 7.x format
            ("7.2-1", (7, 2, 1)),
            ("pve-manager/9.0.6/xyz", (9, 0, 6)),
            ("8.2.4", (8, 2, 4)),
            ("8.2", (8, 2, 0)),
            ("9", (9, 0, 0)),
            ("", None),
            (None, None),
            ("garbage", None),
            ("pve-manager/hash12345/6.1.2", (6, 1, 2)),
        ],
    )
    def test_parsing(self, raw, expected):
        v = parse_pve_version(raw)
        if expected is None:
            assert v is None
        else:
            assert v == PveVersion(*expected)
            assert v.as_tuple() == expected

    def test_hash_part_is_not_mistaken_for_version(self):
        """The '1ac2f4b' hash is not mistaken for a version (non-numeric parts)."""
        assert parse_pve_version("pve-manager/1ac2f4b/8.2.4") == PveVersion(8, 2, 4)


class TestSupports:
    def test_matrix_covers_known_features(self):
        assert set(PVE_FEATURES) >= {"version", "rrddata", "guest_tags"}

    def test_feature_boundaries(self):
        assert supports(PveVersion(7, 4), "guest_tags") is False
        assert supports(PveVersion(8, 0), "guest_tags") is True
        assert supports(PveVersion(8, 1), "guest_tags") is True
        assert supports(PveVersion(6, 2), "version") is True
        assert supports(PveVersion(6, 1), "version") is False
        assert supports(PveVersion(9, 3), "rrddata") is True

    def test_unknown_version_and_feature_are_conservative_false(self):
        assert supports(None, "rrddata") is False
        assert supports(PveVersion(8, 2), "no-such-feature") is False
        assert supports(None, "no-such-feature") is False

    def test_register_feature_extends_matrix(self):
        register_feature("test_feat_xyz", 8, 3)
        try:
            assert supports(PveVersion(8, 2), "test_feat_xyz") is False
            assert supports(PveVersion(8, 3), "test_feat_xyz") is True
        finally:
            PVE_FEATURES.pop("test_feat_xyz", None)

    def test_patch_version_does_not_gate_feature(self):
        """Features are gated on (major, minor); the patch is irrelevant."""
        assert supports(PveVersion(8, 0, 99), "guest_tags") is True

    def test_str_short_form(self):
        assert str(PveVersion(8, 2, 4)) == "8.2.4"
        assert str(PveVersion(8, 2, 0)) == "8.2"


def test_compat_module_is_pure():
    """domain/compat pulls no network/Qt — stdlib only (AST import scan)."""
    import ast
    import pathlib

    src = pathlib.Path(compat.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".")[0])
    assert not roots & {"PySide6", "requests", "proxmoxer"}, roots
