"""Tests for the noVNC console plumbing (worker URL/ticket, page html, provider call)."""

import asyncio
from unittest.mock import MagicMock

from virtdeck.backend import NoVncWorker
from virtdeck.ui.console.page import build_console_html


class TestBuildWsUrl:
    def test_qemu_path_and_port(self):
        url = NoVncWorker.build_ws_url("pve.host", "n1", 100, "qemu", 5900, "TICKET")
        assert url == ("wss://pve.host:8006/api2/json/nodes/n1/qemu/100/"
                       "vncwebsocket?port=5900&vncticket=TICKET")

    def test_lxc_path(self):
        url = NoVncWorker.build_ws_url("pve.host", "n1", 200, "lxc", 5901, "T")
        assert "/lxc/200/vncwebsocket" in url

    def test_ticket_is_quoted(self):
        url = NoVncWorker.build_ws_url("pve.host", "n1", 100, "qemu", 5900,
                                       "a b&c=d/e?плюс")
        assert "vncticket=a%20b%26c%3Dd%2Fe%3F%D0%BF%D0%BB%D1%8E%D1%81" in url

    def test_host_is_quoted(self):
        url = NoVncWorker.build_ws_url("p ve.host", "n 1", 100, "qemu", 5900, "T")
        assert url.startswith("wss://p%20ve.host:8006/api2/json/nodes/n%201/")


class TestExtractTicket:
    def test_password_preferred(self):
        assert NoVncWorker.extract_ticket(
            {"password": "p", "ticket": "t"}) == "p"

    def test_ticket_fallback(self):
        assert NoVncWorker.extract_ticket({"ticket": "t"}) == "t"

    def test_empty(self):
        assert NoVncWorker.extract_ticket({}) == ""


class TestBuildConsoleHtml:
    def test_contains_rfb_with_credentials(self):
        html = build_console_html(5910, "TICKET</script>")
        assert '"ws://127.0.0.1:" + cfg.port + "/"' in html
        assert "new RFB(" in html
        # ticket inserted as a JSON string with "</" escaped
        assert 'TICKET<\\/script>' in html

    def test_ticket_not_raw_in_html(self):
        html = build_console_html(5910, "<script>alert(1)</script>")
        # closing tag must not survive as live html
        assert "alert(1)</script>" not in html
        assert '<script>alert(1)<\\/script>' in html

    def test_no_html_entities_in_script(self):
        # regression: html.escape turned " into &quot; → SyntaxError in <script>
        html = build_console_html(5910, 'a"b&c<d')
        assert "&quot;" not in html
        assert "&amp;" not in html
        assert '"a\\"b&c<d"' in html

    def test_exposes_rfb_to_page(self):
        html = build_console_html(5910, "T")
        assert "window.rfb = rfb;" in html


class TestStickyKeyJs:
    def test_press_and_release(self):
        from virtdeck.ui.console.page import sticky_key_js
        assert sticky_key_js(0xFFE3, "ControlLeft", True) == (
            'if (window.rfb) rfb.sendKey(65507, "ControlLeft", true);')
        assert sticky_key_js(0xFFE1, "ShiftLeft", False) == (
            'if (window.rfb) rfb.sendKey(65505, "ShiftLeft", false);')

    def test_guard_when_rfb_missing(self):
        from virtdeck.ui.console.page import sticky_key_js
        assert sticky_key_js(0xFFEB, "MetaLeft", True).startswith(
            "if (window.rfb) ")


class TestProviderVncWebsocket:
    @staticmethod
    def _api():
        from virtdeck.provider import VmAPI
        mock_session = MagicMock()
        mock_session.call = MagicMock(
            side_effect=lambda fn, *a, **kw: fn(*a, **kw))
        return VmAPI(mock_session), mock_session

    def test_get_vnc_websocket_qemu(self):
        api, s = self._api()
        chain = s.proxmox.nodes
        qemu_chain = chain.return_value.qemu
        qemu_chain.return_value.vncwebsocket.get = MagicMock(
            return_value={"port": "5900"})
        result = api.get_vnc_websocket("n1", 100, "qemu", 5900, "T")
        assert result == {"port": "5900"}
        qemu_chain.return_value.vncwebsocket.get.assert_called_once_with(
            port=5900, vncticket="T")

    def test_get_vnc_websocket_lxc(self):
        api, s = self._api()
        chain = s.proxmox.nodes
        lxc_chain = chain.return_value.lxc
        lxc_chain.return_value.vncwebsocket.get = MagicMock(
            return_value={"port": "5901"})
        result = api.get_vnc_websocket("n1", 200, "lxc", 5901, "T")
        assert result == {"port": "5901"}
        lxc_chain.return_value.vncwebsocket.get.assert_called_once_with(
            port=5901, vncticket="T")

    def test_get_vnc_proxy_without_proxy_param(self):
        """The noVNC path sends no proxy (optional, rejected by some PVE
        versions), but sends websocket=1 — without it PVE does not raise
        the websocket-ready listener."""
        from virtdeck.provider import VmAPI
        mock_session = MagicMock()
        mock_session.call = MagicMock(
            side_effect=lambda fn, *a, **kw: fn(*a, **kw))
        chain = mock_session.proxmox.nodes
        post = chain.return_value.qemu.return_value.vncproxy.post
        post = MagicMock(return_value={"port": 5900})
        chain.return_value.qemu.return_value.vncproxy.post = post
        api = VmAPI(mock_session)
        api.get_vnc_proxy("n1", 100, "qemu")
        post.assert_called_once_with(websocket=1)


class TestNoVncWorkerErrorMapping:
    """Regression: the catch-all "vnc" in the mapping turned a timeout/
    network failure into a false "Console not supported for this VM"
    (vncproxy:/vncwebsocket: prefixes appear in any message)."""

    @staticmethod
    def _worker_with(exc, monkeypatch):
        import virtdeck.backend.console as console_mod

        class _Api:
            def get_vnc_proxy(self, *a, **kw):
                raise exc

        class _Provider:
            vms = _Api()

            def close(self):
                pass

        monkeypatch.setattr(console_mod, "create_provider",
                            lambda cfg, timeout=10: _Provider())
        worker = console_mod.NoVncWorker(
            {"host": "pve.test", "user": "u", "token_name": "t",
             "token_value": "s"}, "n1", 100)
        errors = []
        worker.signals.error.connect(errors.append)
        return worker, errors

    def test_timeout_not_mapped_to_not_supported(self, monkeypatch):
        worker, errors = self._worker_with(
            TimeoutError("connection timed out"), monkeypatch)
        worker.run()
        assert len(errors) == 1
        assert "not supported" not in errors[0]
        assert "timed out" in errors[0]

    def test_permission_still_mapped(self, monkeypatch):
        worker, errors = self._worker_with(
            RuntimeError("vncproxy: PERMISSION CHECK FAILED (403)"),
            monkeypatch)
        worker.run()
        assert len(errors) == 1
        assert "permission" in errors[0].lower()


class TestNoVncWindowToolbar:
    @staticmethod
    def _host_cfg():
        return {"name": "h1", "host": "pve.test", "user": "u@pam",
                "token_name": "tok", "token_value": "sec", "trust_ssl": False}

    def test_sticky_modifiers_toggle(self, qtbot, monkeypatch):
        from PySide6.QtWidgets import QToolBar, QWidget

        from virtdeck.ui.console import window as win_mod

        class _FakeView(QWidget):
            def __init__(self):
                super().__init__()
                self._page = MagicMock()

            def page(self):
                return self._page

        monkeypatch.setattr(win_mod, "QWebEngineView", _FakeView)
        monkeypatch.setattr(win_mod, "WsBridge", MagicMock())

        win = win_mod.NoVncWindow(
            self._host_cfg(), "n1", 100, "qemu", "wss://pve.test", "T")
        qtbot.addWidget(win)

        toolbar = win.findChild(QToolBar)
        assert toolbar is not None
        labels = [a.text() for a in toolbar.actions()]
        assert labels == ["Shift", "Ctrl", "Alt", "Win"]

        js = win.view.page().runJavaScript
        # before the page loads the buttons are disabled
        assert not any(a.isEnabled() for a in toolbar.actions())
        win._on_page_loaded(True)
        assert all(a.isEnabled() for a in toolbar.actions())

        ctrl = toolbar.actions()[1]
        ctrl.setChecked(True)
        js.assert_called_with(
            'if (window.rfb) rfb.sendKey(65507, "ControlLeft", true);')
        ctrl.setChecked(False)
        js.assert_called_with(
            'if (window.rfb) rfb.sendKey(65507, "ControlLeft", false);')

        toolbar.actions()[3].setChecked(True)
        js.assert_called_with(
            'if (window.rfb) rfb.sendKey(65515, "MetaLeft", true);')

    def test_window_destroyed_on_close(self, qtbot, monkeypatch):
        """Regression: without WA_DeleteOnClose every console open left
        a hidden QMainWindow + QWebEngineView (renderer process leak)."""
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QWidget

        from virtdeck.ui.console import window as win_mod

        class _FakeView(QWidget):
            def __init__(self):
                super().__init__()
                self._page = MagicMock()

            def page(self):
                return self._page

        monkeypatch.setattr(win_mod, "QWebEngineView", _FakeView)
        monkeypatch.setattr(win_mod, "WsBridge", MagicMock())

        win = win_mod.NoVncWindow(
            self._host_cfg(), "n1", 100, "qemu", "wss://pve.test", "T")
        qtbot.addWidget(win)
        assert win.testAttribute(Qt.WA_DeleteOnClose)


class _FakeServer:
    def __init__(self, log):
        self._log = log

    def close(self):
        self._log.append("server.close")

    async def wait_closed(self):
        self._log.append("server.wait_closed")


class _FakeConn:
    def __init__(self, log):
        self._log = log
        self.closed = False

    async def close(self):
        self.closed = True
        self._log.append("upstream.close")


class TestWsBridgeShutdown:
    """Regression: bridge teardown finishes BEFORE the loop stops (no
    "Task was destroyed" / GeneratorExit / EBADF); the upstream is
    closed BEFORE wait_closed — otherwise a deadlock (the handler waits
    for the upstream)."""

    def test_teardown_completes_before_loop_stop(self):
        from virtdeck.ui.console.bridge import WsBridge

        bridge = WsBridge("ws://upstream.test", "hdr", False)
        loop = asyncio.new_event_loop()
        log = []
        bridge._loop = loop
        bridge._server = _FakeServer(log)
        bridge._upstream = _FakeConn(log)

        loop.call_soon(bridge._shutdown)
        loop.run_forever()

        assert log == ["server.close", "upstream.close",
                       "server.wait_closed"]
        assert bridge._upstream.closed
        # no unfinished tasks at the moment the loop stops
        assert not asyncio.all_tasks(loop)
        loop.close()

    def test_shutdown_without_server_is_safe(self):
        from virtdeck.ui.console.bridge import WsBridge

        bridge = WsBridge("ws://upstream.test", "hdr", False)
        loop = asyncio.new_event_loop()
        bridge._loop = loop
        loop.call_soon(bridge._shutdown)
        loop.run_forever()
        assert not asyncio.all_tasks(loop)
        loop.close()


class TestWsBridgeStopRace:
    """Regression: stop() before port_ready / before the thread starts
    leaves no unhandled exceptions and no leaked threads."""

    def test_stop_before_loop_assigned_no_leak(self):
        from virtdeck.ui.console.bridge import WsBridge

        bridge = WsBridge("wss://upstream.test", "hdr", False)
        bridge.stop()   # no _loop yet — used to be a no-op, thread leaked
        bridge.start()  # the thread must see the flag and exit immediately
        bridge._thread.join(5)
        assert not bridge._thread.is_alive()

    def test_stop_during_serve_no_unhandled_error(self, monkeypatch):
        import threading
        import time

        import virtdeck.ui.console.bridge as bridge_mod
        from virtdeck.ui.console.bridge import WsBridge

        async def fake_serve(*args, **kwargs):
            # simulate "bind not finished yet": _serve hangs until stop()
            await asyncio.get_running_loop().create_future()

        monkeypatch.setattr(bridge_mod.websockets, "serve", fake_serve)

        bridge = WsBridge("wss://upstream.test", "hdr", False)
        errors = []
        bridge.error.connect(errors.append)
        recorded = []
        old_hook = threading.excepthook

        def hook(args):
            recorded.append(args)

        threading.excepthook = hook
        try:
            bridge.start()
            deadline = time.time() + 5
            while bridge._loop is None and time.time() < deadline:
                time.sleep(0.01)
            bridge.stop()
            bridge._thread.join(5)
        finally:
            threading.excepthook = old_hook

        assert not bridge._thread.is_alive()
        assert recorded == []   # CancelledError must not reach the excepthook
        assert errors == []     # and must not turn into an error signal
