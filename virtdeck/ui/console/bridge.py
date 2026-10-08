"""Local WebSocket bridge for the noVNC console.

Tunnel: noVNC (ws://127.0.0.1:{port}) -> PVE (wss://host:8006/.../vncwebsocket).
Auth: Authorization header with an API token; TLS verification per trust_ssl.
The connection is kept alive by websocket pings (ping_interval) — the PVE
server replies pong (PVE::APIServer::AnyEvent, opcode 9). Frames are relayed
unchanged.
"""

import asyncio
import logging
import ssl
import threading

try:
    import websockets
except ImportError:  # minimal build without websockets — noVNC unavailable
    websockets = None
from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class WsBridge(QObject):
    """Async bridge in a dedicated thread with its own asyncio loop."""

    port_ready = Signal(int)  # local bridge port
    error = Signal(str)
    stopped = Signal()

    def __init__(self, ws_url, auth_header, verify_ssl, parent=None):
        super().__init__(parent)
        self._ws_url = ws_url
        self._auth_header = auth_header
        self._verify_ssl = verify_ssl
        self._loop = None
        self._server = None
        self._upstream = None
        self._error_sent = False
        self._stop_requested = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        if websockets is None:
            self.error.emit(
                "The 'websockets' module is not installed — noVNC console is unavailable")
            return
        self._thread.start()

    def stop(self):
        # The flag is required: stop() may arrive BEFORE self._loop is
        # assigned in the thread (race on quick window close) — without it
        # the request is lost and the thread leaks along with the server.
        self._stop_requested = True
        if self._loop is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._shutdown)
        except RuntimeError:
            pass

    def _emit_error(self, msg):
        logger.warning("noVNC bridge error: %s", msg)
        if self._error_sent:
            return
        self._error_sent = True
        try:
            self.error.emit(msg)
        except RuntimeError:
            pass

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            if not self._stop_requested:
                self._loop.run_until_complete(self._serve())
                self._loop.run_forever()
        except asyncio.CancelledError:
            # stop before _serve completes: teardown cancels the serve task —
            # normal path, not an error (CancelledError is a BaseException)
            pass
        except Exception as e:
            if self._stop_requested:
                logger.debug("noVNC bridge stopped during startup: %s", e)
            else:
                self._emit_error(str(e))
        finally:
            self._loop.close()
            try:
                self.stopped.emit()
            except RuntimeError:
                pass

    async def _serve(self):
        self._server = await websockets.serve(
            self._handle_client, "127.0.0.1", 0, max_size=None,
        )
        sock = list(self._server.sockets)[0]
        self.port_ready.emit(sock.getsockname()[1])

    def _ssl_context(self):
        ctx = ssl.create_default_context()
        if not self._verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    async def _handle_client(self, client):
        try:
            async with websockets.connect(
                self._ws_url,
                ssl=self._ssl_context(),
                additional_headers={"Authorization": self._auth_header},
                ping_interval=25,
                max_size=None,
            ) as upstream:
                self._upstream = upstream
                logger.info("noVNC tunnel established: %s",
                            self._ws_url.split("?")[0])
                await asyncio.gather(
                    self._pump(client, upstream),
                    self._pump(upstream, client),
                    return_exceptions=True,
                )
        except Exception as e:
            self._emit_error(str(e))

    @staticmethod
    async def _pump(src, dst):
        try:
            async for msg in src:
                await dst.send(msg)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    def _shutdown(self):
        async def _close():
            # Order matters: wait_closed() waits for conn_handler to finish,
            # which waits for the upstream to close — close the upstream
            # BEFORE waiting.
            if self._server is not None:
                self._server.close()
            if self._upstream is not None:
                await self._upstream.close()
            if self._server is not None:
                await self._server.wait_closed()
            # Cancel remaining tasks (conn_handler, keepalive) BEFORE
            # stopping the loop: otherwise close() raises "Task was
            # destroyed" and coroutines get GeneratorExit writing to an
            # already-closed fd (EBADF).
            tasks = [t for t in asyncio.all_tasks()
                     if t is not asyncio.current_task()]
            for t in tasks:
                t.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        def _finalize(task):
            if not task.cancelled() and task.exception() is not None:
                logger.debug("bridge shutdown error", exc_info=task.exception())
            self._loop.stop()

        try:
            # Stop the loop only after teardown completes.
            asyncio.ensure_future(_close()).add_done_callback(_finalize)
        except RuntimeError:
            pass
