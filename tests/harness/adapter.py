"""M4.0: requests adapters of the harness — fake, record, replay.

`FakeApiAdapter` serves requests via the fake's handler
(`FakePveApi.handle` / `FakePbsApi.handle`) — no network sockets, TLS
never starts, the real provider/PBS-client code runs as in production.
`record_into` turns on recording into the fixture format.

`RecordingAdapter` wraps a real HTTPAdapter to record from a live
cluster (run manually with network and credentials, never in CI).

`ReplayAdapter` serves requests from recorded entries — the contract is
checked against live API responses. Matching is by (method, path,
params): params are part of the key (rrddata requests with different
timeframes are different entries).

Fixture format (FIXTURE_FORMAT):

    {
      "kind": "virtdeck-recording",
      "version": 1,
      "recorded_at": "2026-10-07T12:00:00+00:00",
      "host": "pve1.corp",
      "entries": [
        {"method": "GET", "path": "/nodes",
         "params": {}, "status": 200, "data": [...]}
      ]
    }

`path` — without the `/api2/json` prefix; `data` — the value of the
`{"data": ...}` envelope (for non-200 — the error body as is).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit

import requests
from requests.adapters import BaseAdapter, HTTPAdapter

FIXTURE_KIND = "virtdeck-recording"
FIXTURE_VERSION = 1


# ── Request parsing / response building ─────────────────────────────


def _parse(request) -> tuple[str, dict]:
    """Request URL → (path without /api2/json, params from query and
    form body)."""
    split = urlsplit(request.url)
    path = split.path
    if "/api2/json" in path:
        path = path.split("/api2/json", 1)[1] or "/"
    params = dict(parse_qsl(split.query, keep_blank_values=True))
    body = request.body
    if body:
        if isinstance(body, bytes):
            body = body.decode("utf-8", "replace")
        try:
            form = json.loads(body)
            if isinstance(form, dict):
                params.update({str(k): v for k, v in form.items()})
        except ValueError:
            params.update(dict(parse_qsl(body, keep_blank_values=True)))
    return path, params


def _response(status: int, data: object) -> requests.Response:
    if isinstance(data, dict) and "errors" in data:
        body = data
    else:
        body = {"data": data}
    resp = requests.Response()
    resp.status_code = status
    resp._content = json.dumps(body, ensure_ascii=False).encode("utf-8")
    resp.headers["Content-Type"] = "application/json"
    return resp


def _param_key(params: dict | None) -> tuple:
    return tuple(sorted((str(k), str(v)) for k, v in (params or {}).items()))


def _entry(request, status: int, data: object) -> dict:
    path, params = _parse(request)
    return {"method": request.method, "path": path, "params": params,
            "status": status, "data": data}


# ── Adapters ────────────────────────────────────────────────────────


class FakeApiAdapter(BaseAdapter):
    """requests adapter over the fake's handler.

    `handler(method, path, params) -> (status, data)`. `record_into` —
    a list that fixture-format entries are appended to (recording a
    scenario into a replay file).
    """

    def __init__(self, handler, record_into: list | None = None):
        self.handler = handler
        self.record_into = record_into

    def send(self, request, *args, **kwargs) -> requests.Response:
        path, params = _parse(request)
        status, data = self.handler(request.method, path, params)
        if self.record_into is not None:
            self.record_into.append(_entry(request, status, data))
        return _response(status, data)

    def close(self) -> None:
        pass


class RecordingAdapter(BaseAdapter):
    """Live recording from a real cluster: the response is passed
    through as is, the entry is appended to `entries` (see
    FIXTURE_FORMAT)."""

    def __init__(self, inner: HTTPAdapter):
        self.inner = inner
        self.entries: list[dict] = []

    def send(self, request, **kwargs) -> requests.Response:
        resp = self.inner.send(request, **kwargs)
        try:
            body = resp.json()
            data = body.get("data") if isinstance(body, dict) \
                and "data" in body else body
        except ValueError:
            data = resp.text
        self.entries.append(_entry(request, resp.status_code, data))
        return resp

    def close(self) -> None:
        self.inner.close()


class ReplayAdapter(BaseAdapter):
    """requests adapter over recorded entries. A miss raises
    AssertionError with the list of recorded paths (production code
    turns it into ProxmoxError with the same message)."""

    def __init__(self, entries: list[dict]):
        self._index: dict[tuple, dict] = {}
        for entry in entries:
            key = (entry["method"], entry["path"], _param_key(entry["params"]))
            self._index[key] = entry
        self.calls: list[tuple] = []

    def send(self, request, *args, **kwargs) -> requests.Response:
        path, params = _parse(request)
        key = (request.method, path, _param_key(params))
        self.calls.append(key)
        entry = self._index.get(key)
        if entry is None:
            known = sorted({k[1] for k in self._index})
            raise AssertionError(
                f"replay miss: {request.method} {path} "
                f"params={sorted(params.items())}; recorded: {known}")
        return _response(entry["status"], entry["data"])

    def close(self) -> None:
        pass


# ── Fixtures ────────────────────────────────────────────────────────


def save_fixture(path: str | Path, entries: list[dict], *, host: str = "",
                 recorded_at: str | None = None) -> None:
    doc = {
        "kind": FIXTURE_KIND,
        "version": FIXTURE_VERSION,
        "recorded_at": recorded_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": host,
        "entries": list(entries),
    }
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                          encoding="utf-8")


def load_fixture(path: str | Path) -> list[dict]:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("kind") != FIXTURE_KIND:
        raise ValueError(f"not a {FIXTURE_KIND} fixture: {path}")
    if doc.get("version") != FIXTURE_VERSION:
        raise ValueError(f"unsupported fixture version: {path}")
    return list(doc["entries"])
