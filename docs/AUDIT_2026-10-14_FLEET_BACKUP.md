# Аудит: система резервного копирования и Fleet Health (этап 6.2)

Дата: 2026-10-14 · База: `main @ e3973c1`, v3.0.4 · Режим: только чтение и анализ, код не менялся, коммитов нет.

Главный вопрос аудита: какие реальные задания Proxmox VE VirtDeck способен корректно читать и редактировать, и может ли Fleet Health достоверно определять состояние резервного копирования каждой VM/CT — в том числе при заданиях `all=1` и заданиях, привязанных к пулу.

---

## 1. Исходное состояние репозитория

- Ветка `main`, коммит `e3973c1` (`test(refresh): audit 6.1.1 review — late-completion and re-create coverage`), рабочее дерево чистое, версия 3.0.4.
- Изменения этапа 6.1.1 (pools/HA sentinel) опубликованы; «дополнительные локальные изменения в тестах», упомянутые в задании, — это тот самый `e3973c1`, уже отправленный в origin.
- Проверка выполнена по фактическому коду; в репозиторий не вносилось никаких изменений.

## 2. Архитектура Fleet Health

Цепочка: `источники API → collector → domain-агрегация → FleetHealthWorker → диалог`.

| Компонент | Файл | Роль |
|---|---|---|
| Сборка целей | `virtdeck/backend/fleet.py::build_fleet_targets` | nodes_cfg → FleetTarget: один кластер = один таргет (репрезентатив `cluster_rep`), standalone — отдельно; skip/PBS/ambiguous исключены |
| Сборщик кластера | `virtdeck/fleet/collector.py::collect_cluster` | fan-out по источникам, каждый изолирован (`guarded`): resources, backup_jobs, tasks (лимит `TASK_HISTORY_LIMIT=200`), версии и storage по узлам; частичный сбор → `errors`, `complete=False` |
| Чистая агрегация | `virtdeck/domain/fleet.py` | `_task_aggregates` (бакеты per-vmid + per-job), `build_backup_states`, `build_cluster_report`; PBS-карта passed-in |
| Покрытие | `virtdeck/domain/backup_coverage.py` | `BackupJob.from_raw` / `selects` / `compute_coverage`: семантика vzdump — `all > pool > vmid`, `exclude` только с `all`, `node`-ограничение, шаблоны exempt, дубликаты vmid — первый побеждает |
| PBS-источник | `virtdeck/fleet/pbs_source.py` | все PBS-конфиги → `{(type,id): ts}`, walk namespace (глубина ≤3), `verify=failed` исключены; изоляция на сервер |
| Runway | `virtdeck/fleet/runway.py` | МНК по rrddata, 95% CI, качества ok/sparse/no-trend/no-capacity/no-data, возраст последней точки |
| Drift | `virtdeck/fleet/drift.py` | отставание узла от новейшего (ok/patch/unknown/minor/major) |
| Sprawl | `virtdeck/fleet/sprawl.py` + `virtdeck/ui/api/fleet.py` | on-demand скан, 1 запрос/VM, пул ≤8, неудачи → `failed` (не «нет снапшотов») |
| Воркер | `virtdeck/backend/fleet.py::FleetHealthWorker` | параллельно ≤8 потоков, PBS-карта один раз, rrddata для runway, `finished_all` гарантированно в `finally` |
| UI | `virtdeck/ui/fleet_health.py` | секции compliance/drift/runway/sprawl; `tasks_truncated` → caveat-строка; incomplete-данные → «Data from HH:MM» / «Data unavailable»; навигация двойным кликом |

Периодичность: только по требованию (открытие диалога / кнопка Refresh); фонового пересчёта нет. Данные — свежие ответы API (без кэша); PBS-карта собирается один раз на прогон.

## 3. Архитектура резервного копирования

Цепочка: `API Proxmox VE → провайдер → воркеры CRUD → форма → таблица`; история задач → Fleet Health.

- **Чтение заданий**: `virtdeck/provider/_cluster.py` — `list_backup_jobs` (GET /cluster/backup), `list_all_jobs` (PVE8+: GET /cluster/jobs с фильтром `type==vzdump`, fallback на /cluster/backup при 404/501; другие ошибки пробрасываются), `list_jobs`. Выбор пути записи — `_use_jobs_path` (probe кэшируется на провайдер, решение принимается ДО записи; таймауты перебрасываются как «исход неизвестен», без автоповтора).
- **CRUD-воркеры**: `virtdeck/backend/cluster.py` — `ClusterJobsWorker`, `ClusterJobCreateWorker` (POST), `ClusterJobUpdateWorker` (PUT), `ClusterJobDeleteWorker` (DELETE); таймаут 15 с, политика «исход неизвестен» при таймауте.
- **UI**: `virtdeck/ui/detail_panel/_host_tabs.py` — вкладка Backup jobs в контекстах кластера и хоста; таблица (id / enabled / schedule / storage / vmid / mode / comment); исходная строка API сохраняется в `Qt.UserRole`; `_on_add_backup_job` / `_on_edit_backup_job` / `_on_remove_backup_job`; `pve_major` определяется по `pve_version_raw` (`_detect_pve_major`, неизвестная версия → 7).
- **Форма**: `virtdeck/ui/backup_job_dialog.py::BackupJobDialog` — поля: enabled, VMIDs (текст), mode, storage, compress, notes/comment, remove+keep-last, bwlimit, расписание (daily/weekly/custom).
- **Покрытие/комплаенс**: `backup_coverage` (см. §2) — задания читаются полностью, включая pool/all/exclude/node.
- **Ручной бэкап**: `virtdeck/ui/vzdump_dialog.py` + `virtdeck/backend/storage.py::VzdumpWorker` (POST /nodes/{node}/vzdump + поллинг задачи, `remove`/`bwlimit`/notes).
- **История задач**: `provider/_tasks.py::list_cluster(limit=200)` → `_task_aggregates` → `build_backup_states` → compliance-строки Fleet Health.

## 4. Поддерживаемые и неподдерживаемые типы заданий

Сопоставление с исходником PVE (pve-manager `PVE/API2/Backup.pm`, fetch с git.proxmox.com 2026-10-14; дальше — «PVE-исходник»):

| Сценарий | Чтение | Отображение | Создание | Редактирование | Удаление |
|---|---|---|---|---|---|
| Явный список vmid | ✅ | ✅ (колонка VMIDs) | ✅ | ⚠️ теряет retention-политику (D3) и дефолты (D3b) | ✅ |
| `all=1` (+exclude) | ✅ | ⚠️ выглядит как пустой VMID, неотличим от пустого задания | ❌ D1 | ❌ D1/D2 | ✅ |
| Задание пула (`pool=`) | ✅ | ⚠️ pool не показывается вовсе | ❌ D1 | ❌ D1/D2 | ✅ |
| `node`-ограничение | ✅ | ❌ не показывается | ❌ | ❌ | ✅ |
| legacy-задания vzdump.cron (PVE7) | ✅ (index отдаёт их вместе с jobs.cfg) | ✅ | ✅ (legacy-путь) | ⚠️ те же потери | ✅ |
| Служебные поля (mailto, mailnotification, performance, fleecing, notes-template, repeat-missed) | ✅ (в raw-строке) | ❌ | ❌ | ✅ не теряются (не включаются в PUT; PVE обновляет только переданные поля) | ✅ |

**Ключевой факт PVE-исходника (update_job, PUT /cluster/backup/{id})**:

```perl
if (defined($param->{vmid})) {
    delete $job->{all};
    delete $job->{exclude};
    delete $job->{pool};
} elsif ($param->{all}) {
    delete $job->{vmid};
    delete $job->{pool};
} elsif ($job->{pool}) { ... }
```

Отправка `vmid` в PUT **удаляет** из задания `pool`, `all` и `exclude`. Форма VirtDeck шлёт `vmid` всегда (`get_params`: `params["vmid"] = vmid_text if vmid_text else "all"`) — отсюда D1/D2.

Контрольным вопросом было, принимает ли PVE `vmid=all` (тогда редактирование pool/all-задания «пройдёт» и молча затрёт выбор гостей). По схеме PVE параметр `vmid` — это `pve-vmid-list` (список целочисленных VMID), `all` — отдельный boolean-параметр; значит `vmid=all` отбраковывается схемой → 400. Прямую живую проверку 400 сделать не на чем — см. §7. Оба исхода дефектны: либо редактирование невозможно (fail-safe), либо возможна тихая потеря `pool`.

## 5. Проверка гипотезы Kimi о UPID и `_task_aggregates`

**Гипотеза**: «vzdump cluster-задачи имеют пустой слот vmid в UPID, поэтому `_task_aggregates` их отбрасывает, и гости с бэкапами по `all=1`-джобу получают ложное "Never backed up"».

**Вердикт: на текущем `main` гипотеза опровергнута — она была подтверждена ранее и уже исправлена.**

Цепочка (вся прослежена):

1. История задач: `provider/_tasks.py::list_cluster(limit=200)` → GET /cluster/tasks; строки содержат `upid`, `type`, `status`, `starttime`, `id` (для гостевых задач ещё и `vmid`).
2. Распознавание: `_task_aggregates` (`domain/fleet.py:122`) берёт `type` из строки или слота 5 UPID; формат UPID `UPID:<node>:<pid>:<pstart>:<starttime>:<type>:<id>:<user>` — слоты 5/6/4 определены корректно.
3. Строка без vmid (`_row_vmid` → None) **не отбрасывается**: она попадает в job-бакет `job_agg[job_id]`, где `job_id = row["jobname"] or row["id"] or слот 6 UPID`. У PVE 7.2+ UPID кластерного запуска несёт job id в слоте id (`fork_worker('vzdump', $jobid, …)`), и `GET /cluster/tasks` возвращает его же в поле `id` — совпадение с `BackupJob.job_id` (поле `id` из GET /cluster/backup) точное.
4. Непрямая атрибуция: `build_backup_states` (`domain/fleet.py:223`) — гость без прямых улик (нет своих task-строк) получает `task_last_ok` от последнего успешного запуска покрывающего задания (`j.selects(guest)`: `all=1`/`pool`/`vmid` + `node`-фильтр). Прямые улики всегда побеждают; неудачный запуск задания не маскируется зелёным.
5. Результат попадает в `_compliance_rows` (`ui/fleet_health.py:267`) — «Never backed up» только если `not state.ever_backed_up`.
6. Регрессионный тест: `tests/ui/test_fleet_health.py::test_cluster_job_run_covers_guests` — гость 105 без своих задач, `all=1`-джоб, UPID с id-слотом `bz-all` → «Never backed up» отсутствует. Механизм введён коммитом `d4b0cf8` («fix(fleet): P0 honesty batch from external reviews (Kimi/Claude/ChatGPT)») — гипотеза Kimi была валидной для состояния до этого коммита.

**Остаточные случаи, когда ложное «Never backed up» всё же возможно** (уже не гипотеза Kimi, но тот же симптом):

- **D4**: источник `tasks` недоступен (сеть/таймаут) → `tasks=None` → `build_cluster_report` получает `tasks or ()` → нет ни прямых улик, ни job-бакетов; при этом coverage считается (resources+jobs собрались) → покрытые гости краснеют «Never backed up». Тот же класс, что аудит 6.1: «не получено» неотличимо от «подтверждено отсутствие» на уровне строки отчёта. Маркер «N with incomplete data» в статусе смягчает, но не устраняет.
- **D6**: PVE < 7.2 — у запусков заданий id-слот UPID пуст (докстринг честно говорит «PVE 7.2+»), job-бакет не заполняется. Для старых кластеров без PBS/прямых задач — ложное «Never backed up».

## 6. Подтверждённые дефекты

### D1 (P1) — форма заданий не поддерживает выбор пула, `all=1`, `exclude`, `node`
- Место: `ui/backup_job_dialog.py` (`_build_ui`, `get_params`); `ui/detail_panel/_host_tabs.py::_on_add_backup_job`.
- Факт: единственный способ выбора гостей — текстовое поле VMIDs; пустое поле превращается в `vmid="all"` — невалидное значение для PVE (отдельного параметра `all` форма не шлёт, `pool` не умеет вовсе). Создать задание пула или all=1 через VirtDeck нельзя; задание пула на создание уходит только как сломанное `vmid=all` (400) либо с ручным перечислением VMID.
- Ожидание: selection mode (All / Pool / Include selected), поля `exclude` и `node`.

### D2 (P1) — редактирование задания пула/all теряет выбор гостей
- Место: `ui/detail_panel/_host_tabs.py::_on_edit_backup_job` → `dlg.get_params()` → `ClusterJobUpdateWorker` → `provider/_cluster.py::update_backup_job` (PUT).
- Факт: `get_params()` строит payload с нуля и всегда включает `vmid`; по PVE-исходнику `vmid` в PUT удаляет `pool`/`all`/`exclude`. Два исхода:
  - `vmid="all"` отбраковывается схемой PVE → 400 → редактирование невозможно (данные не теряются, функция недоступна);
  - пользователь вписал реальные VMID (например, хотел «подправить» пул-задание) → PUT проходит и **молча** превращает pool-задание в vmid-list — гости пула выпадают из бэкапов.
- Тестов, фиксирующих контракт «что уходит в PUT при редактировании», нет (§8).

### D3 (P2) — редактирование теряет retention-политику `prune-backups`
- Место: `ui/backup_job_dialog.py::_fill_from_job` (218–229) / `get_params` (281–285).
- Факт: PVE 8 возвращает `prune-backups` **объектом** (в `backup_job_return_schema` это явно оговорено: property string в POST/PUT, но объект в ответе GET). `_fill_from_job` понимает только строку и только `keep-last=`; объект → `retain=3`. Сохранение задания с `remove=1` и политикой `keep-daily=7,keep-weekly=4,…` перезаписывает её на `keep-last=3` — тихая потеря данных.
- Дополнительно: поведение наследуется и на legacy-задания (там строка, но не-`keep-last` части списка также отбрасываются).

### D3b (P2) — дефолты формы расходятся с дефолтами PVE при редактировании
- `remove`: PVE default **1**; VirtDeck читает `job.get("remove", 0)` → 0, чекбокс снят; сохранение задания, у которого `remove` не был задан явно (значит, работал дефолт 1), отправляет `remove=0` и **отключает prune** без ведома пользователя.
- `compress`: PVE default `lzo`; VirtDeck читает `job.get("compress", "0")` → «без сжатия» → сохранение меняет режим сжатия.
- `mode`/`enabled` — дефолты совпадают.

### D4 (P1) — сбой источника `tasks` даёт ложное «Never backed up» (и «Last backup failed»-семантику без сбоев)
- Место: `domain/fleet.py::build_cluster_report` (`tasks or ()`), `ui/fleet_health.py::_compliance_rows` (проверяет только `coverage is None`).
- Факт: tasks — единственный упавший источник → compliance-строки рендерятся как ни в чём не бывало: гости, реально покрытые работающими заданиями, помечаются красным «Never backed up». Отчёт честно помечен «Data from HH:MM» + «N with incomplete data», но строка противоречит реальности.
- Ожидание: при недоступной истории задач либо не рендерить «Never backed up» (как уже делается при `coverage is None`), либо явный статус «unverified» вместо красного.

### D5 (P2, условный) — PBS-карта общая на весь флот: VMID-коллизии между кластерами
- Место: `backend/fleet.py::_run` (одна `collect_pbs_last_backups(self._pbs_cfgs)` для всех таргетов), ключ карты `(backup-type, backup-id)` без кластера/датастора.
- Факт: у PBS снапшота `vm/100` нет признака кластера; два таргета с одинаковым VMID (у независимых кластеров VMID почти всегда пересекаются — оба начинаются со 100) получают перекрёстные `pbs_last_ok` → чужое время бэкапа может скрыть реальную протухлость.
- Условие: ≥2 PVE-таргета + PBS-источник + пересечение VMID. Для одного кластера дефекта нет. Требует подтверждения по фактической инфраструктуре (§7).

### D6 (P3, документированное ограничение) — PVE < 7.2: запуски заданий не атрибутируются
- Место: `domain/fleet.py` докстринг «PVE 7.2+»; `_task_aggregates` отбрасывает строки без id-слота и без `jobname`/`id`.
- Для старых кластеров непрямая атрибуция недоступна; в VirtDeck нет предупреждения об этом (caveat есть только про truncation). Приоритет низкий: owner's infra на PVE 8 (версия 7 поддерживается как fallback).

### D7 (P3) — теоретический TypeError в `_task_aggregates`
- Место: `domain/fleet.py:163–168`: строка с разборным типом vzdump и статусом, но без `starttime` (malformed UPID, len ≤ 5) при уже заполненном бакете → `None > int` → TypeError; исключение всплывает до `collect_cluster` вне `guarded` → весь кластерный отчёт теряется (ловится в `_collect_one` → «Data unavailable»).
- Требует повреждённой строки задач — на практике практически нереально.

## 7. Потенциальные риски, которые пока нельзя подтвердить

- **Поведение PVE при `vmid=all` в POST/PUT** (ожидается 400 по схеме `pve-vmid-list`): git.proxmox.com закрылся rate-limit'ом после первого файла; нужна либо живая проверка на PVE-стенде, либо повторный fetch `PVE/VZDump/Common.pm`. От исхода зависит только форма проявления D2 (400 vs тихая потеря), сам D2 верен в обоих случаях.
- **`/cluster/resources` и множественное членство в пулах**: гость может состоять в нескольких пулах; поле `pool` в resources — одиночная строка. Если PVE возвращает только один (произвольный) пул, `selects()` по второму пулу даст ложное «Not covered by any backup job». Нужен дамп `/cluster/resources` для гостя в двух пулах. Если у владельца все гости в одном пуле — риска нет.
- **Формат `prune-backups` у legacy-заданий vzdump.cron** (строка vs объект) — влияет на D3 для PVE7; проверить GET на PVE 7.
- **Кросс-кластерное пересечение VMID + PBS** — подтвердить фактическую топологию (D5).
- Зафиксировано как «недостаточно данных»: ни один из этих пунктов не выдан за доказанный дефект.

## 8. Недостающие тесты

Существующая база (125 тестов по fleet/backup): `tests/domain/test_backup_coverage.py` (семантика выбора, all>pool>vmid, exclude, node, шаблоны), `tests/domain/test_fleet.py` (бакеты, UPID-слоты, truncation-флаг, PBS-карта), `tests/fleet/` (collector/runway/sprawl/pbs_source), `tests/ui/test_fleet_health.py` (compliance-строки, truncated caveat, **test_cluster_job_run_covers_guests** — регрессия гипотезы Kimi, incomplete-маркеры, навигация), `tests/provider/test_provider.py` (list_all_jobs fallback-матрица, путь записи, «ambiguous timeout»).

Отсутствуют:

1. **BackupJobDialog**: `get_params` (vmid="all" при пустом поле — фиксация текущего и целевого контракта), `_fill_from_job` для pool/all-заданий и для `prune-backups`-объекта (D3), дефолты `remove`/`compress` (D3b).
2. **Контракт редактирования**: что реально уходит в PUT при `_on_edit_backup_job` pool-задания (D2) — тест на payload (мок `update_backup_job`).
3. **Частичный сбор → compliance**: tasks упал, jobs/resources ок → строки не должны утверждать «Never backed up» (D4).
4. **PBS-коллизия**: два таргета с общим VMID и PBS-картой (D5) — тест, документирующий текущее и целевое поведение.
5. **CRUD end-to-end**: `tests/harness/fake_pve.py` поддерживает только GET `/cluster/backup` (строка 206); POST/PUT/DELETE не смоделированы — CRUD покрыт только моками провайдера, сквозной сценарий «создал → виден в списке → отредактировал → поля сохранились» не проверяется никем.
6. Round-trip «прочитал задание → открыл форму → сохранил без изменений → задание на сервере байт-в-байт то же» — главный тест против всего класса D1–D3b.

## 9. План исправлений (этапы с критериями)

1. **Честность редактирования (P1, без расширения формы)** — маленький самостоятельный шаг: `get_params` не шлёт `vmid`, если поле пустое И исходное задание — pool/all (сохраняет `pool`/`all`); не шлёт `remove`/`compress`, если пользователь их не менял (дефолт из исходного задания, не из формы); `prune-backups` пересылается как есть при отсутствии правок. Критерии: round-trip-тест (§8.6) зелёный; редактирование pool-задания не меняет `pool` на сервере.
2. **Форма: выбор гостей (P1)** — selection mode All / Pool / VMIDs (+ `exclude`, `node`), чтение всех типов заданий в форму. Критерии: создание pool-задания через UI реально создаёт pool-задание (harness CRUD, §8.5); редактирование all=1 не превращает его в vmid-list.
3. **Комплаенс при недоступной истории (P1, D4)** — флаг «tasks not fetched» в отчёте; строки «Never backed up» заменяются на «unverified» либо скрываются с маркером. Критерий: тест §8.3 зелёный.
4. **Таблица заданий (P2)** — колонка Selection (`pool` / `all` / vmid-список / node), чтобы pool- и all-задания были отличимы. Критерий: тест на рендер строк.
5. **PBS per-target (P2, D5)** — карта last-backup, скоупированная на таргет (datastore/namespace → кластер, или per-target список PBS-конфигов) — после уточнения топологии владельцем. Критерий: тест §8.4.
6. **Мелочи (P3)** — caveat для PVE < 7.2 рядом с truncation; консолидация `last_pbs_backup_times`/`pbs_source._add_snapshot` (дублированная логика — сейчас расходятся только потенциально); защита `_task_aggregates` от строк без starttime (D7).

Зависимости: 1 независим и закрывает потерю данных даже до появления формы; 2 зависит от 1 (контракт payload); 3–6 независимы.

## 10. Список просмотренных файлов и выполненных проверок

Файлы (все — чтение): `virtdeck/domain/fleet.py`, `virtdeck/domain/backup_coverage.py`, `virtdeck/fleet/collector.py`, `virtdeck/fleet/pbs_source.py`, `virtdeck/fleet/runway.py`, `virtdeck/fleet/drift.py`, `virtdeck/fleet/sprawl.py`, `virtdeck/backend/fleet.py`, `virtdeck/backend/cluster.py` (CRUD-воркеры), `virtdeck/backend/storage.py` (VzdumpWorker), `virtdeck/backend/fetch.py` (атрибуция host_name в кластере), `virtdeck/provider/_cluster.py` (задания), `virtdeck/provider/_tasks.py`, `virtdeck/ui/fleet_health.py`, `virtdeck/ui/api/fleet.py`, `virtdeck/ui/backup_job_dialog.py`, `virtdeck/ui/vzdump_dialog.py`, `virtdeck/ui/detail_panel/_host_tabs.py` (вкладка заданий: загрузка/таблица/add/edit/remove, `_detect_pve_major`), `virtdeck/ui/detail_panel/_vm_tabs.py` (backup-вкладка гостя), `virtdeck/ui/tree_panel.py` (reveal_key/find_and_select), `virtdeck/ui/mainwindow.py` (вход в Fleet Health), `virtdeck/ui/pbs_panel.py` (обзорно), `tests/harness/fake_pve.py`, `tests/ui/test_fleet_health.py`, `tests/domain/test_fleet.py`, `tests/domain/test_backup_coverage.py`, `tests/fleet/`, `tests/provider/test_provider.py`.

Проверки:
- Полная трассировка цепочки UPID→`_task_aggregates`→`build_backup_states`→`_compliance_rows` (гипотеза Kimi, §5) + её постоянный тест.
- Сверка контракта PUT с исходником pve-manager `PVE/API2/Backup.pm` (HEAD) — семантика удаления pool/all/exclude подтверждена дословно.
- Гит-археология: `git log -S job_agg` → механизм введён `d4b0cf8`.
- Инвентаризация тестов (125 collected по fleet/backup) и harness-CRUD (только GET).
- Проверка навигации Fleet Health→дерево: в кластере все узлы/VM несут `host_name` репрезентатива (`fetch.py:226`), ключи совпадают — навигация корректна.
- Инвентаризация дефолтов формы против дефолтов PVE-схемы (D3b).
- 2 целевых fetch внешних источников (git.proxmox.com): 1 успешный (Backup.pm), далее rate-limit — остановлено сознательно.
