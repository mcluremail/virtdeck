"""noVNC HTML page for QWebEngineView.

The page connects to the local WsBridge (ws://127.0.0.1:{port}) and runs
RFB from the vendored noVNC. VNC auth is a one-time ticket (vncproxy),
passed as the RFB password (PVE does set_password on qemu).
"""

import json

_PAGE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>noVNC</title>
<style>
html, body { margin: 0; padding: 0; height: 100%; background: #141414; overflow: hidden; }
#screen { width: 100%; height: 100%; }
#status {
    position: absolute; top: 8px; left: 12px; z-index: 10;
    font: 12px monospace; color: #c8c8c8; background: rgba(0,0,0,0.55);
    padding: 3px 8px; border-radius: 4px; pointer-events: none;
}
</style>
</head>
<body>
<div id="screen"></div>
<div id="status">connecting...</div>
<script type="module">
import RFB from "./core/rfb.js";

const cfg = {port: {port}, ticket: {ticket}};
const screen = document.getElementById("screen");
const status = document.getElementById("status");

const rfb = new RFB(screen, "ws://127.0.0.1:" + cfg.port + "/",
    {shared: false, credentials: {password: cfg.ticket}});
rfb.scaleViewport = true;
rfb.resizeSession = false;
rfb.background = "#141414";

rfb.addEventListener("connect", () => { status.textContent = "connected"; });
rfb.addEventListener("disconnect", (e) => {
    status.textContent = e.detail.clean ? "disconnected" : "connection failed";
});
rfb.addEventListener("credentialsrequired", () => {
    rfb.sendCredentials({password: cfg.ticket});
});

window.rfb = rfb;
</script>
</body>
</html>
"""


def build_console_html(port: int, ticket: str) -> str:
    r"""Builds the page, safely injecting port and ticket.

    Inside <script> HTML entities are not decoded, so the ticket is inserted
    as a JSON string; escaping the script context is prevented by breaking
    "</" (the standard trick: `</` -> `<\/`).
    """
    ticket_js = json.dumps(str(ticket)).replace("</", "<\\/")
    return _PAGE.replace("{port}", str(int(port))).replace("{ticket}", ticket_js)


def sticky_key_js(keysym: int, code: str, down: bool) -> str:
    r"""JS to press/release a sticky modifier key in the page's RFB session.

    down=True — the sticky key is pressed (key-down) and held in the guest
    until the reverse event; down=False — released. The user types the rest
    of the combo directly in the console.
    """
    payload = json.dumps([int(keysym), str(code), bool(down)])
    return f"if (window.rfb) rfb.sendKey({payload[1:-1]});"
