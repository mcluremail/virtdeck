# Этап 6.3.1 — исправление D1–D4 (достоверность данных и классификация транспортных ошибок)

Дата: 2026-10-15. База: `main @ 7385cb0`. Исходный аудит: `docs/AUDIT_2026-10-15_PROVIDER_API.md`.
Этап исправлений, не аудит: затронуты только D1–D4, D5–D17 не тронуты.

---

## D1 — PBS-датастор: сбой чтения статуса показывался как «0 B, 0%, зелёный» (P2)

**Первоопричина.** `PbsProvider.datastores()` при ошибке `GET /admin/datastore/{s}/status`
подставлял `status = {}`; `PbsDatastore.build()` трактовал пустой статус как
`usage=0.0, used=0, total=0`; панель рендерила эти плейсхолдеры как реальные
данные (`_usage_color(0.0)` — зелёный). Сбой неотличим от пустого датастора.

**Изменённые файлы:** `virtdeck/domain/pbs.py`, `virtdeck/pbs/provider.py`,
`virtdeck/ui/pbs_panel.py`, `virtdeck/ui/i18n/{ru,ar,zh,fr,es}.json` (1 новый ключ).

**Решение.** Различение «подтверждённый ноль» / «статус недоступен» флагом
`PbsDatastore.status_ok` (dataclass-поле с дефолтом `True` — обратная
совместимость прямого конструирования). `build()` считает статус полученным
только если в ответе присутствуют все три обязательных поля PBS (`usage`,
`used`, `total`); частичный/пустой/не-dict ответ — `status_ok=False`.
Провайдер при `PbsError` (HTTP, сеть, тайм-аут — клиент поднимает `PbsError`
для всех этих случаев) передаёт `None` вместо `{}`. UI (таблица датасторов и
вкладка статуса) при `status_ok=False` показывает `—` серым (`Color.TEXT_SEC`)
с подсказкой «Usage data unavailable»; прогресс-бар обнуляется и серится.
Подтверждённые нули (успешный ответ с нулями) отображаются как прежде —
семантика успешной статистики не изменена. Исключений при отображении нет.

**Тесты:** `tests/domain/test_pbs.py` — статус-тройка подтверждена / `None` /
`{}` / не-dict / частичный / нулевой подтверждён / дефолт прямого конструирования;
`tests/pbs/test_provider.py` — PbsError (HTTP 500) и тайм-аут → `status_ok=False`,
пустой ответ `data:null` → `False`; `tests/ui/test_pbs_panel.py` — «—» в таблице,
«0% / 0 B» остаётся для подтверждённого нуля, «Usage data unavailable» в статусе.

**Ограничения.** Неизвестные поля статуса игнорируются как прежде. Если PBS в
будущем сделает какое-то из трёх полей необязательным, условие придётся
пересмотреть (сейчас контракт требует все три).

## D2 — HealthCheckWorker: «healthy» при нечитаемых проверках (P2)

**Первоопричина.** Три проверки (`services`, `subscription`, `apt/update`) были
обёрнуты в `try/except` с `logger.debug`; неудача проверки не фиксировалась в
результате, и при пустых `issues`/`warnings` итоговый статус был `healthy`.

**Изменённые файлы:** `virtdeck/ui/api/metrics.py` (`HealthCheckWorker`;
в ТЗ указан `backend/metrics.py` — фактически воркер живёт в `ui/api/metrics.py`).

**Решение.** Исход каждой проверки фиксируется: при исключении ИЛИ
неподходящей структуре ответа (`services` — не список, `subscription` — не
объект) имя проверки попадает в `unavailable`. Отсутствие поля `data`
трактуется как пустой подтверждённый результат (контракт допускает), поэтому
не считается ошибкой. При непустом `unavailable` добавляется warning
«Could not check: …» — существующая лестница статусов
(`issues→critical`, иначе `warnings→warning`, иначе `healthy`) не менялась,
новой системы состояний нет: неполнота использует штатную модель
`issues/warnings` + доп. ключ данных `unavailable: [имена]`. Результаты
успешных проверок сохраняются (issue по неработающему сервису остаётся
`critical` и при неполноте); неизвестное состояние не превращается в ошибку
сервиса (не попадает в `issues`).

**Тесты:** `tests/ui/test_metrics_workers.py::TestHealthHonestyD2` — 11 случаев:
все проверки ок / неработающий сервис / просроченная подписка / нечитаемые
services, subscription, updates по отдельности / некорректная структура обоих
типов / отсутствие поля `data` / частичный сбой с сохранением issue / все три
нечитаемые.

**Ограничения.** Имена проверок в предупреждении не локализуются (технические
термины, как и имена сервисов PVE). `unavailable` — данные, не отдельный
статус; если понадобится дифференцировать «incomplete» визуально от «warning»,
это отдельное задание по UI.

## D3 — HostSnapshotsWorker/StorageDisksWorker: `except: pass` растворял сбои per-VM (P2)

**Первоопричина.** В цикле по ВМ `except Exception: pass` — нечитаемый гость
выглядел как «снимков/дисков нет» наравне с подтверждённо пустым ответом.
Внутренний `except` вокруг запроса размера снимка не тронут: сам снимок там
уже подтверждён, неопределён только размер (остаётся 0 → «—»).

**Изменённые файлы:** `virtdeck/ui/api/metrics.py` (оба воркера + сигналы),
`virtdeck/ui/detail_panel/_host_tabs.py`, `virtdeck/ui/detail_panel/_storage_tabs.py`,
`virtdeck/ui/i18n/*.json` (1 новый ключ).

**Решение.** По образцу fleet/sprawl (`failed: tuple[int, ...]`): сбои per-VM
копятся в `failed_vms` (`{"vmid": int, "error": str}`) и эмитятся вместе с
результатом — сигналы `snapshots_ready`/`disks_ready` расширены третьим
аргументом `list` (изменение арности потребовалось самим дефектом; подключения
обновлены: 2 для снимков, 1 для дисков; `VmSnapshotsWorker` и физические диски
узла не затронуты — у них отдельные сигналы и честный полный `error`).
Ошибки соседних ВМ не отменяют сбор (пул потоков сохранён), логи на ожидаемые
сбои не добавлены, в `error` — текст исключения от `_check_response`
(«HTTP 500: …»), секретов нет (токен в заголовке, не в URL). UI: при частичном
сборе данные показываются + серый маркер «N виртуальных машин не прочитано»
с причинами в tooltip (дерево снимков — топ-левел item; таблица дисков —
строка-маркер); при полном сбое узла — тот же текст вместо «No snapshots /
No data». Подтверждённое отсутствие (успешный пустой ответ) маркером не
считается. Кластерный путь: маркер добавляется в общее дерево на каждый узел —
порядок завершения воркеров не влияет на видимость данных соседних узлов.

**Тесты:** `tests/ui/test_metrics_workers.py` — 7 воркер-кейсов (успех всех /
подтверждённая пустота ≠ сбой / сбой одной ВМ при успешных соседях / несколько
сбоев / сохранение результатов соседей — для обоих воркеров) + 2 UI-теста
маркера; обновлены 2 подключения-потребителя в существующих тестах
(`tests/provider/test_requests_session.py` — прогон `run()` без подписчиков).

**Ограничения.** Маркер в таблице дисков — строка без span; при сортировке
таблицы пользователем строка-маркер может уехать (в этой таблице сортировка
не включена). Причины ошибок в tooltip — технические тексты, не локализованы.

## D4 — классификация транспортных ошибок по числам в URL (P3)

**Первоопричина.** `from_exception` (`provider/_errors.py`) матчил `\b401\b` и
т.п. по тексту сообщения; `requests.exceptions.ConnectionError` при DNS-сбое
цитирует URL запроса — VMID 401/403/404 в пути давал ложные
`ProxmoxAuthError`/`ProxmoxNotFoundError`. Зеркальная подстрочная логика — в
`ui/utils.parse_pve_error` («403»/«401» в строке) и `backend/tokens.py`
(`"401" in msg` → «Invalid login or password»).

**Изменённые файлы:** `virtdeck/provider/_errors.py`, `virtdeck/ui/utils.py`,
`virtdeck/backend/tokens.py`.

**Решение.** Тип до текста. Порядок в `from_exception`: passthrough `ProxmoxError`
→ AnyEvent 595–599 → точный `status_code` (proxmoxer) → **requests-типы**:
`HTTPError` классифицируется по реальному `response.status_code` (тот же
контракт, что у ветки статуса: 401→auth, 403→permission/auth, 404→not_found,
504→timeout, остальное→api, `status_code` сохраняется), `Timeout` → timeout
(`ConnectTimeout` — подкласс обоих — падает в timeout), `ConnectionError`/
`SSLError`/`ChunkedEncodingError` → network; прочие `RequestException`
(TooManyRedirects и т.п.) остаются текстовому фолбэку и не могут стать
auth/not_found. Числовые regex фолбэка (не-requests исключения) анкерированы
формами `HTTP 401` / `401 Client Error` — «VM 401 status» больше не auth.
Первопричина сохраняется (`raise ... from exc` в вызывающих + исходный текст в
сообщении); секретов в сообщениях нет (токен в заголовке). `parse_pve_error`
анкерирован так же; `create_admin_token` — except по типам (`HTTPError` по
`response.status_code` 401 → «Invalid login or password», Timeout/
ConnectionError → «Cannot connect to …», прочее → generic), текстовые
«authorization/permission» сохранены как доп. признаки.

**Проверка потребителей изменяемых классов:** `_tasks.py` — `except
(ProxmoxNetworkError, ProxmoxTimeoutError)` ретраит поллинг: сетевой сбой
теперь честно ретраится в рамках бюджета (раньше DNS-сбой с «401» в URL давал
немедленный `poll_failed` как auth) — целевое улучшение аудита;
`_cluster.py` probe (404/501) и `_storage.py` не изменили поведения для
реальных HTTP-ответов; полный набор тестов зелёный.

**Тесты:** `tests/provider/test_provider.py::TestTransportClassificationD4` —
20 кейсов: DNS/сброс с VMID 401/403/404 в URL → network; тайм-аут → timeout;
SSL, connection reset, chunked → network; неизвестный транспорт (TooManyRedirects,
базовый RequestException) ≠ auth/not_found; реальные 401/403/404/504/500 через
`HTTPError.response` → прежние классы с `status_code`; 403 c текстом permission
→ permission; анкеры: «VM 401 status» → api, «HTTP 401»/«404 Client Error» →
прежние классы; `parse_pve_error`: DNS с VMID → «Cannot resolve DNS name»,
числа в URL ≠ auth, реальные 401/403 распознаются.
`tests/backend/test_backend.py` — DNS/тайм-аут ≠ «Invalid login», реальный 403
остаётся generic, 401 — «Invalid login» (фикстура `_resp` приближена к реальному
requests: `HTTPError` теперь несёт `response` — не ослабление, а устранение
искусственности).

**Ограничения.** `HTTPError` без `response` (искусственный случай) уходит в
текстовый фолбэк. Не-requests транспорты (urllib3 напрямую) не
классифицируются по типу — до `from_exception` они доходят уже обёрнутыми.

---

## Проверки перед завершением (§7)

| Проверка | Результат |
|---|---|
| Новые целевые тесты | 55 passed (D1: 12, D2: 11, D3: 9, D4: 23) |
| Релевантные существующие (pbs, domain, provider, ui, backend) | 312 passed |
| Полный набор `QT_QPA_PLATFORM=offscreen pytest -q -n 3` | **1516 passed, 1 warning** (54 с) |
| Предупреждение | 1, pre-existing `test_scan_worker_crash_releases_ui` (не регрессия) |
| `ruff check virtdeck tests` | чисто |
| `scripts/check_release.py` | passed; i18n-паритет 5 локалей × 1336 ключей (+3 новых) |
| Версия/выпуск | не изменены (3.0.5, `pyproject.toml`/`__init__.py` согласованы) |

Тест-счётчик: до этапа 1461 → после 1516 (+55).

## Зафиксировано

- Реальные PVE/PBS не затрагивались: все проверки — на заглушках/фейках, сеть не использовалась.
- Commit, push, выпуск не выполнялись; рабочая копия содержит изменения этапа + untracked отчёты аудита и фикса.
- D5–D17 оставлены последующим этапам (6.3.2): D5 (Snapshots «Loading…» при смене VM), D6 (optimistic-статус при полном пуле), D7 (VmActionWorker без гейта), D8 (тихий drop WorkerManager), D9 (`pbs_panel._workers` без discard), D10 (`PbsProvider.jobs()` глотание), D11 (login ValueError на не-JSON 200), D12 (легаси `/cluster/backup` без «outcome unknown»), D13 (delete_host_token синхронно в GUI), D14 (FleetHealth-диалог не останавливает скан), D15 («HA error» копипаст), D16 (исход run/verify PBS), D17 (next_vmid вне иерархии).
- Новых дефектов в ходе этапа не обнаружено; изменённые контракты (арность двух сигналов, поле `PbsDatastore.status_ok`, ключ `unavailable` в health-словаре) — минимальные и требовались самим дефектами (§6: «если изменение не требуется — сохранять контракт»).
