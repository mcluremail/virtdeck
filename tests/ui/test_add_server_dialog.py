"""AddServerDialog tests: PVE/PBS ports, token button, cluster detection.

Regressions from the v3.0 first run (docs/FIRST_RUN_ISSUES.md #1-#3).
"""

import pytest

from virtdeck.ui.add_server_dialog import AddServerDialog


@pytest.fixture
def dialog(qtbot):
    d = AddServerDialog()
    qtbot.addWidget(d)
    return d


class TestPorts:
    def test_default_port_is_8006_for_pve(self, dialog):
        assert dialog._is_pbs() is False
        assert dialog.port_input.text() == "8006"
        assert not dialog.port_input.isHidden()

    def test_port_switches_to_8007_for_pbs(self, dialog):
        dialog.type_combo.setCurrentIndex(1)
        assert dialog.port_input.text() == "8007"

    def test_port_switches_back_to_8006(self, dialog):
        dialog.type_combo.setCurrentIndex(1)
        dialog.type_combo.setCurrentIndex(0)
        assert dialog.port_input.text() == "8006"
        assert not dialog.port_input.isHidden()

    def test_custom_port_not_clobbered(self, dialog):
        dialog.port_input.setText("9000")
        dialog.type_combo.setCurrentIndex(1)
        assert dialog.port_input.text() == "9000"

    def test_pbs_config_uses_port(self, dialog):
        dialog.type_combo.setCurrentIndex(1)
        dialog.host_input.setText("pbs1")
        dialog.pwd_input.setText("tok")
        cfg = dialog.get_config()
        assert cfg["port"] == 8007


class TestTokenShowButton:
    def test_button_sized_to_content(self, dialog):
        """Button without fixed width: "Show" is not clipped."""
        assert dialog._token_show_btn.minimumWidth() <= 0 or \
            dialog._token_show_btn.minimumWidth() < 60
        dialog._token_show_btn.setText("Показать")
        assert dialog._token_show_btn.sizeHint().width() >= 60


class TestClusterAutoDetect:
    def test_no_checkbox(self, dialog):
        assert not hasattr(dialog, "cluster_rep_cb")

    def test_cluster_detected_fills_name_and_config(self, dialog):
        dialog.host_input.setText("pve01.ros.linru.grp")
        dialog._on_token_ready({
            "token_name": "virtdeck-abc123", "token_value": "v",
            "user": "root@pam",
            "cluster": {"name": "ros", "nodes": 3},
        })
        assert dialog.cluster_input.text() == "ros"
        assert "Обнаружен кластер" in dialog.status_label.text() or \
            "Cluster detected" in dialog.status_label.text()
        cfg = dialog.get_config()
        assert cfg["cluster_rep"] is True
        assert cfg["cluster"] == "ros"

    def test_user_cluster_name_wins(self, dialog):
        dialog.cluster_input.setText("myname")
        dialog._on_token_ready({
            "token_name": "virtdeck-abc123", "token_value": "v",
            "user": "root@pam",
            "cluster": {"name": "ros", "nodes": 3},
        })
        cfg = dialog.get_config()
        assert cfg["cluster"] == "myname"

    def test_standalone_no_cluster(self, dialog):
        dialog._on_token_ready({
            "token_name": "virtdeck-abc123", "token_value": "v",
            "user": "root@pam",
            "cluster": None,
        })
        cfg = dialog.get_config()
        assert "cluster_rep" not in cfg
        assert cfg["cluster"] is False

    def test_single_node_cluster_is_standalone(self, dialog):
        """Response without a type=cluster entry (single node) — not a cluster."""
        dialog._on_token_ready({
            "token_name": "virtdeck-abc123", "token_value": "v",
            "user": "root@pam",
            "cluster": {"name": "", "nodes": 1},
        })
        cfg = dialog.get_config()
        assert "cluster_rep" not in cfg
