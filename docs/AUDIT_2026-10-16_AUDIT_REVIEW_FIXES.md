# Этап 6.3.4 — исправления по итогам аудит-ревизии (A1–A3, B1, D1)

Дата: 2026-10-16
База: `main` = `58e4aad`; аудит-ревизия — `docs/AUDIT_2026-10-16_POST_6_3_3_REVIEW.md`.
Характер: точечные фиксы находок аудита, test-first, без изменений контрактов UI-потоков.

## Гейты

- `ruff check virtdeck/ tests/` — чисто.
- Полный прогон `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -q -n 3` —
  **1628 passed, 1 warning** (предсуществующий, намеренный краш в
  `tests/ui/test_fleet_health.py::test_scan_worker_crash_releases_ui`); +6 тестов к 1622.
- `scripts/check_release.py` — все проверки пройдены.

## A1 (MEDIUM): PVE `_await_task` — ответ без UPID больше не «успех»

`virtdeck/backend/core.py`. Новый параметр `expect_upid=True` (по умолчанию —
безопасная сторона: синхронная операция, не помеченная флагом, даёт честное
«исход неизвестен», а не фальшивый успех):

- `expect_upid=True` (по умолчанию, все async-операции): 200 без UPID →
  `(False, "outcome unknown — the server did not return a task id (UPID); check
  the task list on the node")`. Задача могла быть запущена и остаться без
  наблюдателя — как в PBS-контракте 6.3.3 (честный запуск).
- `expect_upid=False` (синхронные эндпоинты): null-ответ — это и есть успех;
  UPID, если сервер всё же прислал, по-прежнему дожидается.

Помечены `expect_upid=False` (проверено по API PVE — синхронные):
`delete_content` (storage.py), `create/update/delete_storage` (storage.py),
`delete_snapshot` (vm.py), `post_config(template=0)` (vmops.py). Остальные 18+
вызовов — заведомо async (resize, move, clone, migrate, restore, upload,
vzdump, snapshot create/rollback, start/stop/…), остались на безопасном
дефолте. Дефолт выбран fail-safe: пропущенная пометка на sync-операции даёт
видимое «неизвестно» (легко заметить и починить), а не тихий фальшивый успех.

## A2 (MEDIUM): Fleet Health runway — сбой чтения больше не молчит

- `virtdeck/fleet/runway.py`: `RunwayEstimate` получил поле `note: str = ""`
  (keyword-дефолт, обратная совместимость) и константу качества
  `UNAVAILABLE = "unavailable"`; докстринг модуля дополнен.
- `virtdeck/backend/fleet.py::_runway`: при сбое `get_storage_rrddata`
  вместо `continue` добавляется оценка-заглушка (`days_left=None`,
  `used_bytes=None`, `quality=UNAVAILABLE`, `note=_sanitize_error(e)[:120]`)
  — санитизация как у всех текстов, попадающих в UI.
- `virtdeck/ui/fleet_health.py::_runway_rows`: заглушка рендерится явной
  жёлтой строкой «Runway data unavailable» (`_SEV_WARN`, паттерн D4
  «unverified»), label `"{storage} ({node})"`, detail — причина.

Вторая ветка `_runway` (исключение из `estimate_runway`) оставлена как есть —
после чтения `estimate_runway` выяснено, что дегенеративные серии он
возвращает оценками `no-data`/`no-trend`/`no-capacity` (они доходят до UI, и
фоллбэк «почти заполнено» по заполнению работает), а исключение — только
защитный путь против бага в самом расчёте, скрывать который жёлтой строкой
«данные недоступны» было бы неверно.

## A3 (LOW): кластер при краше обработки ошибки не исчезает

`virtdeck/backend/fleet.py`: построение отчёта-заглушки с `CollectError`
вынесено в `FleetHealthWorker._error_collection(name, exc)`; теперь его
вызывают и `_collect_one` (как раньше), и `job()` — краш внутри собственной
except-ветки сбора больше не выкидывает кластер из `finished_all` без
строки-объяснения. Контракт «диалог получает сигнал по каждому кластеру»
теперь держится во всех путях.

## B1 (LOW): «still running» больше не читается как провал

`virtdeck/backend/core.py`: тексты не-провальных исходов `_await_task`
теперь начинаются с честного состояния:

- тайм-аут: `outcome unknown — the task is still running after {N} s`
  (было `still running after {N} s`);
- без UPID (A1): `outcome unknown — …`;
- poll_failed: без изменений (`task outcome unknown — status poll failed: …`).

Композиты в UI читаются согласованно: «Upload failed: outcome unknown — the
task is still running after 120 s».

**Отступление от рекомендации аудита, осознанное:** полный перенос контракта
на `(status, detail)` с отдельными i18n-ключами в воркерах потребовал бы
правки всех 24 точек вызова и их тестов при нулевой разнице в поведении —
управление у воркеров для всех не-`ok` состояний одинаковое (emit ошибки,
разблокировка кнопок). Выбран вариант с тем же `ok, err`-контрактом и
состояние-ведущими текстами: та же честность в UI при доле риска. Если
потребуется первоклассное состояние «неизвестно» для PVE-задач (как у
PBS-трекера) — это отдельный этап.

## D1 (LOW): выход приложения не ждёт трекеров

`virtdeck/ui/pbs_panel.py`: в `__init__` подключён
`QCoreApplication.instance().aboutToQuit → _stop_all_trackers` (рядом с
существующим `destroyed`). Все stop-события взводятся до того, как Qt начнёт
дожидаться потоков глобального пула; задержка выхода сокращается с «до
интервала опроса» до времени завершения текущего HTTP-запроса трекера.

## i18n

Один новый ключ: `Runway data unavailable` ×5 локалей (ru/es/fr/zh/ar);
`_I18N_VERSION` 44 → 45. Скрипт с round-trip проверкой подтвердил: +1 ключ в
каждом файле, значения существующих переводов не изменены (несколько ранее
дописанных в конец ключей вернулись на алфавитные места — сортировка по
конвенции).

## Тесты (+6)

- `tests/backend/test_backend.py::TestAwaitTask`: async-ответ без UPID →
  «исход неизвестен»; sync-операция с `expect_upid=False` → успех (dict и
  `None`); тайм-аут-текст ведёт с `outcome unknown` (B1). `TestBulkVmActionWorker`
  переведён на реалистичный поток UPID+poll (фейковый `None`-ответ теперь
  честно означает «неизвестно» — старая заглушка была бы ложным успехом).
- `tests/ui/test_fleet_health.py`: юнит `_runway` — сбой rrddata даёт
  заглушку `note`/`UNAVAILABLE`, здоровый хранилище не задет; UI — жёлтая
  строка «Runway data unavailable» с причиной; i18n-ключ во всех локалях;
  `test_worker_crash_still_emits_finished` переписан на новое честное
  поведение A3 (кластер присутствует со строкой CollectError).
- `tests/ui/test_pbs_panel.py::TestTaskTracking`: `aboutToQuit` взводит
  stop-события всех трекеров (D1).

## Разное

- Написание репозитория — одна «e»: `https://github.com/mcluremail/virtdeck`
  (вариант с двумя «e» встречался только в рабочих сводках агента; в файлах
  репо и отчётах его нет — проверено grep).
