"""M4.0: requests-адаптеры харнесса — fake, запись и replay.

`FakeApiAdapter` обслуживает запросы обработчиком фейка
(`FakePveApi.handle` / `FakePbsApi.handle`) — сетевых сокетов нет,
TLS не начинается, реальный код провайдера/PBS-клиента работает как в
продакшене. `record_into` включает запись в формат фиксстуры.

`RecordingAdapter` оборачивает реальный HTTPAdapter для записи с живого
кластера (выполняется вручную с сетью и кредами, в CI не запускается).

`ReplayAdapter` обслуживает запросы из записанных entry — контракт
проверяется на ответах живого API. Совпадение — по (method, path,
params): параметры входят в ключ (rrddata-запросы с разными timeframe —
разные entry).

Формат фиксстуры (FIXTURE_FORMAT):

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

`path` — без префикса `/api2/json`; `data` — значение конверта
`{"data": ...}` (для не-200 — тело ошибки как есть).
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


# ── Разбор запроса / сборка ответа ──────────────────────────────────


def _parse(request) -> tuple[str, dict]:
    """URL запроса → (path без /api2/json, params из query и form-тела)."""
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


# ── Адаптеры ────────────────────────────────────────────────────────


class FakeApiAdapter(BaseAdapter):
    """requests-адаптер над обработчиком фейка.

    `handler(method, path, params) -> (status, data)`. `record_into` —
    список, в который дописываются entry формата фиксстуры (запись
    сценария в replay-файл).
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
    """Live-запись с реального кластера: ответ уходит как есть,
    entry дописывается в `entries` (см. FIXTURE_FORMAT)."""

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
    """requests-адаптер над записанными entry. Промах — AssertionError
    с перечнем записанных путей (в прод-коде превратится в ProxmoxError
    с тем же сообщением)."""

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
                f"params={sorted(params.items())}; записано: {known}")
        return _response(entry["status"], entry["data"])

    def close(self) -> None:
        pass


# ── Фикстуры ────────────────────────────────────────────────────────


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
