"""M0.1: static contract "no sync client in the UI" (ROADMAP v3.0).

AST scan of virtdeck/ui/**: UI modules must not import or call the
sync client (proxmoxer, provider facade, create_provider, requests) —
all network I/O goes through QRunnable workers in backend/ and ui/api/.
A "sync call in the UI" regression = this test fails.

Allowlisted seams:
- virtdeck/ui/api/** — QRunnable workers (metrics): create_provider
  calls are legitimate only inside run() on a pool thread;
- starting workers via QThreadPool.start (mainwindow, WorkerManager) —
  not a sync client and not forbidden by the rules.
"""

import ast
import os
from pathlib import Path
from textwrap import dedent

import pytest

REPO = Path(__file__).resolve().parents[2]
UI_DIR = REPO / "virtdeck" / "ui"

# QRunnable workers of the ui/api layer — the only seam where the
# provider facade is legitimate (used only inside run() on a pool thread).
ALLOWLIST_PREFIXES = ("virtdeck.ui.api",)

# Importing the sync client / transport in the UI is forbidden outside
# the allowlist:
# - proxmoxer — the sync client itself;
# - requests — HTTP transport outside workers;
# - (virtdeck.)backend.pve — legacy sync-client path (guards against
#   relapses after possible refactors);
# - (virtdeck.)provider — PVE API facade (ProxmoxProvider, VmAPI, ...).
FORBIDDEN_IMPORT_PREFIXES = (
    "proxmoxer",
    "requests",
    "backend.pve",
    "virtdeck.backend.pve",
    "provider",
    "virtdeck.provider",
)

# Direct sync-client calls by name (outside the allowlist).
FORBIDDEN_CALLS = frozenset({"ProxmoxAPI", "PVE", "create_provider"})


def _matches(name, prefixes):
    return any(name == p or name.startswith(p + ".") for p in prefixes)


def _is_allowed(modpath):
    return _matches(modpath, ALLOWLIST_PREFIXES)


def _resolve_import(module, level, modpath):
    """Absolute module name for ImportFrom (accounts for relative dots)."""
    if not level:
        return module
    parts = modpath.split(".")
    base = parts[: len(parts) - level] if level <= len(parts) else []
    if module:
        return ".".join([*base, module])
    return ".".join(base)


def _scan_source(source, modpath):
    """Return [(lineno, message)] contract violations found in the source."""
    issues = []
    allowed = _is_allowed(modpath)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not allowed and _matches(alias.name, FORBIDDEN_IMPORT_PREFIXES):
                    issues.append(
                        (node.lineno, f"sync client import '{alias.name}' in the UI")
                    )
        elif isinstance(node, ast.ImportFrom):
            resolved = _resolve_import(node.module, node.level, modpath) or ""
            for alias in node.names:
                full = f"{resolved}.{alias.name}" if resolved else alias.name
                hit = _matches(resolved, FORBIDDEN_IMPORT_PREFIXES) or _matches(
                    full, FORBIDDEN_IMPORT_PREFIXES
                )
                if not allowed and (
                    hit
                    or (
                        (resolved == "virtdeck.plugins" or resolved == "plugins")
                        and alias.name == "create_provider"
                    )
                ):
                    issues.append(
                        (node.lineno, f"sync client import '{full}' in the UI")
                    )
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                name = func.id
            elif isinstance(func, ast.Attribute):
                name = func.attr
            else:
                name = None
            if name in FORBIDDEN_CALLS and not allowed:
                issues.append((node.lineno, f"sync client call '{name}()' in the UI"))
    return issues


def _iter_ui_modules():
    for path in sorted(UI_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(REPO)
        modpath = str(rel.with_suffix("")).replace(os.sep, ".")
        source = path.read_text(encoding="utf-8")
        yield path, modpath, source


def _scan_engine(code, modpath="virtdeck.ui.tabs"):
    return _scan_source(dedent(code), modpath)


class TestScannerEngine:
    """The scanner engine catches every way to smuggle a sync client
    into the UI."""

    def test_proxmoxer_import_detected(self):
        issues = _scan_engine("import proxmoxer")
        assert len(issues) == 1
        assert "proxmoxer" in issues[0][1]

    def test_proxmoxer_submodule_import_detected(self):
        assert _scan_engine("from proxmoxer import ProxmoxAPI")

    def test_provider_import_detected(self):
        issues = _scan_engine("from virtdeck.provider import ProxmoxProvider")
        assert len(issues) == 1
        assert "virtdeck.provider" in issues[0][1]

    def test_relative_provider_import_detected(self):
        issues = _scan_engine(
            "from ...provider._session import build_requests_session",
            modpath="virtdeck.ui.detail_panel.vm_tab",
        )
        assert len(issues) == 1

    def test_backend_pve_legacy_import_detected(self):
        assert _scan_engine("from virtdeck.backend.pve import PVE")
        assert _scan_engine("from backend.pve import PVE")

    def test_create_provider_import_detected(self):
        issues = _scan_engine("from virtdeck.plugins import create_provider")
        assert len(issues) == 1
        assert "create_provider" in issues[0][1]

    def test_relative_create_provider_import_detected(self):
        issues = _scan_engine(
            "from ...plugins import create_provider",
            modpath="virtdeck.ui.detail_panel.vm_tab",
        )
        assert len(issues) == 1

    def test_requests_import_detected(self):
        assert _scan_engine("import requests")

    def test_proxmoxapi_call_detected(self):
        issues = _scan_engine("api = ProxmoxAPI('host')")
        assert len(issues) == 1
        assert "ProxmoxAPI()" in issues[0][1]

    def test_create_provider_call_detected(self):
        assert _scan_engine("provider = create_provider(cfg, timeout=10)")

    def test_clean_ui_module_passes(self):
        code = """
            from PySide6.QtCore import QObject, Signal
            from PySide6.QtWidgets import QWidget

            from ..i18n import tr


            class MyWidget(QWidget):
                clicked = Signal()

                def refresh(self):
                    self.setWindowTitle(tr("Refresh"))
        """
        assert _scan_engine(code) == []

    def test_allowlisted_worker_module_passes(self):
        code = """
            import requests

            from ...plugins import create_provider


            def make_session(cfg):
                return requests.Session()

            def provider(cfg):
                return create_provider(cfg, timeout=10)
        """
        assert _scan_engine(code, modpath="virtdeck.ui.api.metrics") == []

    def test_from_import_nonmodule_alias_passes(self):
        code = """
            from virtdeck.ui.i18n import tr
            from virtdeck.domain.models import VmRow
        """
        assert _scan_engine(code) == []


class TestUITree:
    """The real virtdeck/ui/** tree is clean."""

    def test_ui_tree_has_no_sync_client(self):
        issues = []
        for path, modpath, source in _iter_ui_modules():
            for lineno, message in _scan_source(source, modpath):
                issues.append(f"{path}:{lineno}: {message}")
        assert not issues, "Contract 'no sync client in the UI' violated:\n" + "\n".join(
            issues
        )

    def test_allowlist_modules_are_workers(self):
        """The ui/api/** seam stays on the allowlist only while it is
        made of QRunnable workers; a Qt widget showing up there is a
        reason to revisit it."""
        api_dir = UI_DIR / "api"
        for path in sorted(api_dir.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            widget_bases = [
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.ClassDef)
                for base in node.bases
                if isinstance(base, ast.Name)
                and base.id in {"QWidget", "QDialog", "QMainWindow"}
            ]
            assert not widget_bases, (
                f"{path}: Qt widget in the ui/api worker allowlist module — "
                "the sync client became directly reachable from a widget"
            )


@pytest.mark.parametrize(
    "modpath",
    ["virtdeck.ui.api", "virtdeck.ui.api.metrics", "virtdeck.ui.api.future_worker"],
)
def test_allowlist_matches_submodules(modpath):
    assert _is_allowed(modpath)


def test_non_allowlist_modules_are_checked():
    assert not _is_allowed("virtdeck.ui.mainwindow")
    assert not _is_allowed("virtdeck.ui.tree_panel")
    assert not _is_allowed("virtdeck.ui.detail_panel")
