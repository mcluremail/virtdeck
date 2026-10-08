"""M0.5: supports(feature) in the provider — fetched node versions → matrix."""

import pytest

from virtdeck.domain.compat import PveVersion
from virtdeck.provider._provider import ProxmoxProvider


@pytest.fixture()
def provider():
    p = ProxmoxProvider({"host": "h1", "user": "u", "token_name": "t", "token_value": "v"})
    yield p
    p.close()


class TestProviderCompat:
    def test_report_and_node_version(self, provider):
        assert provider.node_version("pve01") is None
        provider.report_version("pve01", "pve-manager/8.2.4/1ac2f4b")
        assert provider.node_version("pve01") == PveVersion(8, 2, 4)

    def test_report_garbage_is_ignored(self, provider):
        provider.report_version("pve01", None)
        provider.report_version("pve01", "garbage")
        assert provider.node_version("pve01") is None
        assert provider.supports("rrddata", "pve01") is False

    def test_supports_single_node(self, provider):
        provider.report_version("pve01", "pve-manager/8.0.1/abc")
        provider.report_version("pve02", "pve-manager/7.4.1/def")
        assert provider.supports("guest_tags", "pve01") is True
        assert provider.supports("guest_tags", "pve02") is False
        assert provider.supports("rrddata", "pve02") is True

    def test_supports_cluster_requires_all_nodes(self, provider):
        """node=None → a feature counts as supported only if ALL known nodes
        support it (the cluster minimum)."""
        provider.report_version("pve01", "pve-manager/8.2.0/abc")
        assert provider.supports("guest_tags") is True
        provider.report_version("pve02", "pve-manager/7.4.1/def")
        assert provider.supports("guest_tags") is False

    def test_supports_unknown_cluster_is_false(self, provider):
        assert provider.supports("rrddata") is False
        assert provider.supports("rrddata", "unknown-node") is False

    def test_versions_survive_repeated_reports(self, provider):
        provider.report_version("pve01", "pve-manager/8.2.4/abc")
        provider.report_version("pve01", "pve-manager/8.2.4/def")
        assert provider.node_version("pve01") == PveVersion(8, 2, 4)
        assert len(provider._node_versions) == 1
