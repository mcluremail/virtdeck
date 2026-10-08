# ROADMAP.md

## v2.13 — Стабилизация (последний 2.x) ✅ (выпущено в v2.13.0)
- ✅ B12a/B12b: cluster join и create через UI (`POST /cluster/config[/join]`)
- ✅ B4 завершение: CRUD storage-определений (`/storage`), Copy volume
- ✅ B11: произвольный диапазон метрик + экспорт CSV
- ✅ PBS-серверы в отдельном режиме дерева «Backup servers view»,
  per-node строки под shared-хранилищами кластера
- ✅ Стилизация: акцент только у первичных действий (Start, Create VM)
- ✅ i18n: полный паритет ключей в 5 локалях (версия 31)
- ✅ Аудит 2026-09-10 (`docs/AUDIT_2026-09-10.md`): join-воркер получал
  конфиг без credentials — исправлено
- ~~Управление кластером после создания (перемещение нод, link-топология)~~ —
  кандидат в 3.x

## v2.10 — Стабилизация Desktop ✅
- ✅ Тесты backend-воркеров и config (tests/backend, tests/config)
- ✅ Глобальный поиск (B14)
- ✅ Массовые операции (B3)
- ✅ Snapshot rollback (B1a)
- ~~Dry Run (B15)~~ — исключено по решению (см. FEATURES_BACKLOG.md)

## v2.12 — Резервное копирование и PBS (B17) ✅ (выпущено в v2.12.0)
Этап 1 — через PVE API (storage типа pbs):
- ✅ Статус и заполненность PBS-хранилищ (покрывается общим storage-UI)
- ✅ Просмотр PBS-снапшотов: владелец, время, состояние верификации
- ✅ Удаление отдельных бэкапов из UI (prune по одному)
- ✅ Restore PBS-бэкапа в новую ВМ/контейнер

Этап 2 — прямое подключение к PBS API (порт 8007), отдельный плагин:
- ✅ Plugin API: `PbsPlugin` (dispatch по `cfg["type"]="pbs"`), клиент с ticket-авторизацией
- ✅ Добавление PBS-сервера в диалоге Add Server (проверка подключения при добавлении)
- ✅ PBS-серверы в дереве (flat, режим Hosts) со списком datastores и заполненностью
- ✅ Панель PBS: статус/usage datastore, снапшоты (ns, verify, владелец, размер,
  удаление), sync/verify/prune задачи (просмотр, запуск вручную)
- ~~Server-side trash~~ — в PBS API нет публичных эндпоинтов trash (серверная фича)

## Поддержка версий PVE
- ✅ PVE 7.x — поддерживается (основная среда эксплуатации): jobs через
  `/cluster/backup`, детект версии с fallback на 7, HA через `/cluster/ha/groups`
- ✅ PVE 8.x — базовая линейка, полное покрытие
- ✅ PVE 9.x — совместимость подтверждена аудитом по API-документации (2026-09):
  breaking changes учтены — VNC password+TLS (PSA-2026-00014-1), `schedule` вместо
  `starttime`/`dow` в backup jobs, HA groups deprecated (fallback в UI)
- Нюансы PVE 7.0 (без 7.1+): в ответе jobs нет `schedule`, нет `download-url` —
  UI показывает пустое расписание, загрузка ISO по URL недоступна; 7.1+ — полностью

## v3.0 — Production Desktop ✅ (выпущено в v3.0.0 — первая волна: M0–M2 + M4)

> Статус: план на основе анализа конкурентов ([COMPETITORS.md](docs/COMPETITORS.md),
> 2026-09-10) + накопленных follow-up'ов (B3/B14/B18/B20) и [VISION.md](VISION.md).
> Цель: лучший desktop-клиент для управления несколькими независимыми PVE —
> быстрее и отзывчивее web GUI, функциональнее всех desktop-аналогов.
> Документ живой: задачи добавляются по ходу.
> **Релизы волнами: v3.0 core: M0 → M1 → M2 → M4 → M5 → M6 (релизный гейт:
> минимум M0–M2 + M4 — Fleet Health shippable standalone; если M5/M6
> задерживаются, релиз выходит с M0–M2+M4, остальное уезжает в v3.1,
> ничего не переносится целиком). v3.1: M7 → M8 → M9. v3.2: M10 → M11.
> M3 (cross-cluster move) ЗАМОРОЖЕН 2026-09-11 — вне волн до разморозки
> (причины и проработка: B21).**
>
> **Итог релиза (v3.0.0, 2026-10-08):** первая волна — M0 (перформанс-фундамент),
> M1 (движок тем + темы), M2 (командная палитра), M4 (Fleet Health), плюс
> шлифовка по UI-аудиту 2026-10-08. ~~M5, M6~~ — в v3.0 не вошли, кандидаты
> первой волны v3.1.

### Принцип 0 — перформанс-философия (без этого остальное не имеет смысла)

- **Ни одна задача не блокирует UI-поток.** Любой вызов сети/диска —
  воркер + спиннер/скелетон; ожидание внешнего ресурса никогда не
  проявляется как фриз.
- **Optimistic UI**: действия применяются к интерфейсу сразу, ответ
  сервера подтверждает или откатывает с понятной ошибкой.
- **Perf-budget как контракт**: границы UI-потока закреплены контракт-тестами
  в CI (не только аудитом); регресс «фриз = баг релиза».
- **Acceptance-метрики 3.0**: холодный старт ≤1 с; клик → реакция ≤100 мс;
  обновление дерева 1000+ объектов без фриза; ни одного `FREEZE DETECTED`
  в логах типовой сессии.

### Вехи

#### M0. Перформанс-фундамент ✅ (M0.1–M0.5 закрыты 2026-09; порог дерева ≤300 мс уходит в M7 — инкрементальные апдейты TreePanel, см. M0.4)

**Факт-базис (2.13):** повсеместные QRunnable-воркеры в `backend/*.py`,
`WorkerManager` (очередь воркеров в detail_panel), спиннеры на кнопках.
Проблема: контракт соблюдается дисциплиной, а не проверкой — плюс отдельные
sync-вызовы на путях конфига/редких действий.

- ✅ **M0.1. Статический контракт-тест** (`tests/ui/test_sync_contract.py`).
  pytest-тест, сканирующий AST модулей `virtdeck/ui/**`: запрет
  импорта/вызова sync-клиента (proxmoxer, provider-фасад, `create_provider`,
  requests) в UI — весь сетевой I/O только через QRunnable-воркеры.
  Явный allowlist швов: QRunnable-воркеры `ui/api/**` (вызовы только
  внутри `run()` пула) + гвард «Qt-виджет в allowlist-модуле = ошибка»;
  старт воркеров (mainwindow, WorkerManager) не является sync-клиентом.
  Движок сканера покрыт своими тестами (relative импорты, legacy-пути,
  вызовы, false-positive-гварды). Регресс «sync-вызов в UI» = падение CI.
- ✅ **M0.2. Runtime-контракт** (`tests/ui/runtime_contract.py` +
  `tests/ui/test_runtime_contract.py`). Guard-провайдер патчит единую
  точку `PluginRegistry.create_provider`: любой вызов/доступ к провайдеру
  из main-потока фиксируется как нарушение (в фоновых потоках — тихая
  заглушка). Fake QThreadPool не выполняет воркеры; статические фабрики
  диалогов отвечают «отменено»; instance-exec (QDialog/QMenu) закрывает
  modal-closer (PySide6 не даёт перехватить exec патчем класса). В
  офлайн-прогоне: все QAction MainWindow + контекст-меню дерева (VM и
  host) — ни один слот не выполнил сетевой вызов в UI-потоке. Контракт
  вскрыл и починил реальный баг: `_build_tab_chunk` DetailPanel —
  таймер-колбэк падал с RuntimeError после deleteLater панели. Для
  тестируемости `_on_context_menu` разделён: построение меню вынесено в
  `_build_context_menu(item)` (без exec).
- **M0.3. Optimistic UI каркас. ✅** Общий helper «применить к UI сразу →
  подтвердить/откатить по ответу» (состояние + спиннер + откат с понятной
  ошибкой); пилот — power-действия (start/stop/shutdown), далее по вехам.
  Реализовано: `ui/optimistic.py` — `OptimisticVMs` (патчит `VmRepository`
  через `dataclasses.replace` на целевой статус `POWER_TARGET_STATUS`,
  ведёт pending `(host, vmid)`, повторный apply сохраняет оригинальный
  prev для отката; `OptimisticToken.confirm/rollback`); tree_panel —
  `set_pending_vm_keys` крутит спиннер на VM-элементах (общий
  `_sync_spinner` с host-загрузкой, иконка восстанавливается после
  rebuild); mainwindow — apply после confirm-диалога, `action_result` →
  confirm + refresh, `action_error` → rollback + error-нотификация.
  Тесты `tests/ui/test_optimistic.py` (15): юнит менеджера, спиннер
  дерева (PNG-сравнение иконок — `cacheKey` QIcon ненадёжен), сквозной
  поток MainWindow (start без подтверждения → error → rollback →
  result → confirm) + контроль офлайн-контракта M0.2.
- **M0.4. Perf-бейслайн. ✅** Скрипт профилирования типовой сессии (старт,
  дерево 1000+ объектов, открытие табов, refresh) → отчёт в `docs/`.
  Абсолютные пороги (дерево ≤300 мс, старт ≤1 с) — только в
  **nightly-бенчмарке на эталонной машине** (документированная конфигурация);
  в CI — smoke-тесты и относительная деградация (абсолютные пороги на
  CI-раннере без фиксированного железа флапают).
  Реализовано: `scripts/perf_session.py` (offscreen, без сети — guard/
  fake-pool из M0.2): старт MainWindow, лестница rebuild'а TreePanel
  (100→5000 элементов, median из 3), прототип стратегий вставки
  QTreeWidget (baseline / updates-off / batch+lazy-expand), cold/warm
  `DetailPanel.show_details`; данные пишутся между маркерами в
  `docs/PERF_BASELINE.md` + выводы. CI-smoke: `tests/ui/test_perf_smoke.py`
  (щедрые пороги 100≤1с, 1000≤5с — регрессии на порядок).
  **Вывод**: узкое место — обвязка TreePanel (иконки/тултипы/expandAll/
  повторная группировка), а не вставка QTreeWidget (20k за ~210 мс);
  дерево 1000 ВМ ~415 мс rebuild — цель ≤300 мс закрывается
  инкрементальными апдейтами TreePanel (см. M7), cold DetailPanel ~770 мс
  — кандидат на ленивую отрисовку.
  + **Замер потолка QTreeWidget**: дерево сейчас item-based
  (`tree_panel.py`, QTreeWidget). Прототип ленивого expand + батчинг
  вставки — сколько объектов тянет до фриза. Если потолок низкий —
  миграция на QAbstractItemModel поднимается из M7 раньше (иначе метрика
  принципа 0 не выполнится).
- **M0.5. Feature detection / PVE compat matrix. ✅** Версии нод при
  подключении + capabilities-таблица (7.x/8.x/9.x), `supports(feature)`
  в провайдере. Дёшево на M0, окупается на M4 (rrddata/version
  расхождения) и M5 (migrate/HA nuances); вместо хардкода версий.
  Реализовано: `domain/compat.py` — `PveVersion`, `parse_pve_version`
  (форматы 8.x `8.2.4` и 7.x `7.4-3`, хэши/мусор → None),
  `PVE_FEATURES` (version ≥6.2, rrddata ≥6.0, guest_tags ≥8.0) +
  `register_feature` для расширения; `ProxmoxProvider.report_version/
  node_version/supports(feature, node=None)` (node=None → все известные
  ноды; неизвестное → консервативно False); версии заполняются из
  `fetch.py` (pveversion из node status, кластер и standalone).
  Хардкод-парсинг `_detect_pve_major` в `_host_tabs.py` переведён на
  `parse_pve_version`. Тесты: `tests/domain/test_compat.py` +
  `tests/provider/test_compat.py` (23).

#### M1. Движок тем ✅ — ЛИЧНЫЙ ПРИОРИТЕТ (M1.1+M1.2+M1.3 закрыты; preview/импорт отложены, см. M1.3)
- Архитектура: ядро знает **только цветовые токены**; все темы —
  **плагины** через Plugin API (`plugins/`, тип `ThemePlugin` рядом с
  `ProviderPlugin`); QSS собирается из токенов активной темы.
- Дефолтные темы (светлая/тёмная/системная) — тоже плагины.
- Замена хардкода `Color.*` на токены; переключатель в настройках + preview.
- Импорт сторонних тем плагинами (наш ответ PVEDiscordDark ★2540,
  сообщество сможет делать темы).
- **ThemePlugin API v1 замораживается при выпуске 3.0**: контракт токенов,
  метаданных, точек расширения и критериев breaking change зафиксирован в
  документации — темы это публичная поверхность (сообщество будет писать,
  ломать контракт каждые полгода нельзя).
- Кэш собранного QSS — старт не блокируем; проверка RTL/Arabic-локали
  и контраста на дефолтных темах.

- **M1.1. Движок ✅ (2026-09-14)** — канонический набор из 36 токенов
  (контракт v1), `Color` = живой фасад (setattr при активации); весь
  наш код мигрирован с deprecated имён и инлайн-hex (GRAY_*/SLATE_* и
  пр. удалены — алиасы остались только в валидаторе для сторонних тем,
  политика удаления в 4.0); `ThemePlugin` Protocol (`tokens()` обязателен,
  `extra_qss()`, `icons()` частично, `icon_size`, default 16);
  `load_theme()`: валидация → фасад → QSS+extra_qss → иконки
  (set_base_size/reset) → pyqtgraph-цвета → ui_state → слушатели;
  `PluginRegistry`: отдельное id-пространство тем, `unregister()`;
  переключатель темы в статус-баре (рядом с языком), применение
  сохранённой темы при старте; слушатели снимаются при разрушении окна.
  Тесты `tests/ui/test_theme_engine.py` (16): контракт, валидация
  (алиасы/полнота/hex/ошибки до подмены фасада), переключение туда-обратно
  с fake-темой 24px, AST-чистота плагинов тем, e2e через комбобокс
  MainWindow. Полный suite 890 passed.
- **M1.2. Темы ✅** — Breeze, Breeze Dark (палитры сняты из исходников
  KDE breeze, точные значения; derived-токены помечены), Oxygen (из
  color-schemes/Oxygen.colors), свой Graphite (нейтральный тёмный,
  стальной акцент), System (colorScheme: резолвер-хук в Qt-чистом
  `_themes.py`, слушатель `colorSchemeChanged` — live-переключение).
  Движок: `icons()`-оверрайды тем (частичные, фоллбэк на встроенные,
  ошибки изолируются), относительные размеры иконок (0.75×–1.5× от
  базового), Breeze/Breeze Dark — собственные SVG 24px (vm/host/
  cluster/pool/storage/backup/refresh/search, статус-точка масштабируется
  от viewBox), плотность через `extra_qss()`; порядок тем в комбо —
  UX (`ordered_theme_ids`). Тесты +18 в `test_theme_engine.py`.
  Полный suite 908 passed.
- **M1.3. Публичный контракт ✅ (2026-09-15)** — `docs/THEMES.md` (v1:
  36 токенов + reference-палитра, ThemePlugin API, пайплайн активации,
  иконки-оверрайды, ALIASES, статус каналов доставки, пример темы).
  Preview в UI и импорт сторонних .py-тем — отложены (решение владельца
  2026-09-15, реестр к ним готов: `register_theme`/`unregister`); JSON —
  после 3.0. Строка меню (пункты Theme/Settings) — отдельный пункт
  ROADMAP после M1, в веху не входит.

#### M2. Командная палитра (Ctrl+K) ✅ (2026-10-06)
- Единый реестр действий: `ui/action_registry.py` — чистое (без Qt) ядро
  (`Selection`, `ActionSpec`, fuzzy-поиск с ранжированием префикс >
  граница слова > подстрока > подпоследовательность).
- Палитра `ui/command_palette.py` (Ctrl+K): фильтр по выделению дерева с
  контекстным заголовком, живой поиск, клавиатура (стрелки/Enter/Esc,
  клик), shortcut справа, dangerous-действия красным; немодальный
  фреймless-оверлей, закрытие по клику мимо, перестилизация при смене
  темы; строки переведены (i18n v32).
- Все сигнальные действия дерева — в реестре
  (`ui/action_specs.register_tree_actions`): VM power + инструменты
  (noVNC/migrate/clone/convert/HA/Delete VM), массовые «* all» над
  мульти-выделением, блоки host/cluster/group/storage; глобальные
  действия тулбара (add/refresh/search/export/import/about/quit) — из
  `build_registry(window)`.
- Контекст-меню дерева строится из тех же спеков (`_add_action_specs`):
  подписи/иконки/доступность — единый источник; выключенные показываются
  (семантика меню), палитра их скрывает. Динамическое присутствие (режим
  дерева, наличие шаблонов, api-host хранилища) — на стороне меню;
  контекстные хелперы TreePanel (`_cluster_members`, `_storage_api_host`,
  приёмники invoke). Намеренно остались в меню: Trust SSL (динамические
  подпись+иконка), Edit note… (привязка к элементу дерева) и подменю групп.
- `TreePanel.current_selection()` / `selection_for_item()` — дескриптор
  выделения (vm/ct/template/host/cluster/storage/pbs/pool/group).
- Follow-up B14: поиск по IP и владельцу (данные появятся в доменном
  слое) — палитра и глобальный поиск делят один бэкенд.

#### M3. Cross-cluster move ⏸️ — ЗАМОРОЖЕНО (2026-09-11, решение владельца)
- Причины заморозки: пути реализации не утверждены (см. проработку
  «Universal Cluster Mover» в B21), тестовой инфраструктуры (независимые
  кластеры / фейк-провайдеры) пока нет.
- Веха сохранена под номером M3 — «просто пропускаем» на первой волне 3.0.
- Полная проработка: [FEATURES_BACKLOG.md](FEATURES_BACKLOG.md) → B21.
  Зависимость: SSH-движок (asyncssh) — сделаем в M6 «Консоли».

#### M4. Fleet Health ✅ (2026-10-07) — киллер-фича (см. B24)
Сводный отчёт по всем независимым кластерам сразу — «весь парк одним
взглядом». Ни один конкурент этого не делает (PDM/ProxCenter — server+web
для одной организации). Всё на стабильных read-only API, ноль EXPERIMENTAL.
- **M4.0. Тестовый харнесс до фич** (`tests/harness/`): fake PVE/PBS API —
  in-memory сцены кластера и PBS; record/replay-адаптеры над `requests` с
  JSON-фикстурами (`virtdeck-recording`, совпадение по method+path+params);
  швы монтирования без сокетов — реальный провайдер/proxmoxer и PBS-клиент
  работают против фейка (маршрутизация фейков по host, патч `ProxmoxAPI`
  в `provider._session`; DI-параметр `PbsClient(http=...)`).
- Backup compliance (M4.1): matching-движок `domain/backup_coverage.py` —
  семантика vzdump зафиксирована (all > pool > vmid; exclude только при
  all; шаблоны вне отчёта; disabled-джоб никого не покрывает; пересечения
  джобов допустимы), stateless — пересчёт по свежему resources (ВМ мигрирует
  между пулами между запусками); table-driven юнит-тесты до UI.
- Сбор отчёта (M4.2): `domain/fleet.py` (модели + чистая агрегация) и
  `fleet/collector.py` — фан-аут по источникам с изоляцией: упавший
  источник → errors + complete=False, отчёт не пустеет (плашка
  «данные от HH:MM»); бэкап-состояния гостя из task history (vzdump-таски:
  последний успешный/неудачный/попытка) + опциональный PBS-маппинг
  (verify-failed снапшоты не считаются успешными).
- Version drift и storage runway (M4.3): `fleet/drift.py` — отставание ноды
  от лидера кластера (patch/minor/major/unknown, неразбираемые версии
  не скрываются); `fleet/runway.py` — МНК по окну rrddata с отбрасыванием
  дыр, доверительный интервал 95% на наклоне (только на плотном ряде),
  качество прогноза ok/sparse/no-trend/no-capacity/no-data.
- Snapshot sprawl (M4.4): `fleet/sprawl.py` — 1 запрос/ВМ через пул
  с лимитом параллелизма, ошибки per-ВМ изолированы; агрегация забытых
  (порог 30 дней; снапшоты без времени — тоже забытое; current исключён).
- UI (M4.5): `ui/fleet_health.py` + `backend/fleet.py` — диалог «что где
  красное» (секции compliance/drift/runway/sprawl, цвет по серьёзности,
  двойной клик → переход к объекту в дереве), запуск из тулбара/трея
  и Ctrl+Shift+F; кластеры собираются параллельно (поток на кластер),
  sprawl-скан по кнопке.

#### M5. Maintenance mode ⏳ (см. B22)
- Контекст-меню ноды «Maintenance mode…»: эвакуация running ВМ —
  live-миграция на подобранные ноды (по загрузке из `/cluster/resources`),
  для HA-ресурсов — `relocate` (`/cluster/ha/resources/{sid}/relocate`).
- **Обязательный dry-run**: план эвакуации до выполнения (куда какие ВМ).
- **Safety checks**: local storage (не shared), passthrough-устройства,
  HA-состояние, locks, anti-affinity rules.
- Пометка ноды «обслуживание» в дереве (предупреждение о запуске новых ВМ);
  состояние persist в config.sqlite (переживает перезапуск).
- Лимит параллельных миграций; abort/rollback при падении миграции.
- Прогресс по задачам, отчёт «что куда улетело»; exit — снятие пометки.
- Нативного maintenance mode в PVE API нет — оркестрация наша; у vSphere
  это стандарт индустрии, у PVE никто не сделал.

#### M6. Консоли ⏳
- SSH-движок на `asyncssh` (ключи/пароли/агент) — **общий с замороженным
  B21** (cross-cluster move его тоже использует).
- SSH-терминал к ноде/ВМ-контейнеру (встроенный, рядом с noVNC/SPICE).
- SSH-безопасность: known_hosts, agent, токены из keyring, запрет
  логирования паролей; RDP-файл — с безопасными правами.
- RDP-лаунчер к Windows-ВМ (external launcher с предзаполненным файлом).
- Убрать неровности noVNC (по фидбэку 2.x).

#### M7. Дерево 3.x ⏳ (закрывает follow-up'ы B18/B20)
- Переключатель вида кластера «по нодам / по пулам» (сейчас две разные
  модели вложенности кластера и standalone).
- Раскрытие «name (@cluster)» → список нод (per-node usage уже в 2.13).
- Удалить мёртвые `*_folder`-view в detail_panel
  (`show_cluster_folder` / `show_standalone_folder` / `show_storage_folder`).
- Виртуализация/ленивое построение для 1000+ объектов (метрика принципа 0).

#### M8. Свежесть данных ⏳
- Адаптивный polling: быстрее при активности/изменениях, тише в простое.
- Дельта-обновления таблиц и дерева через diff `/cluster/resources`
  и task events (не «идеальный» delta — версий у API нет; не перестраивать
  неизменное; сейчас — полная пересборка, тормозящая большие кластеры).

#### M9. Алерты «Pulse-лайт» ⏳
- Локальные пороги (CPU/RAM/storage/backup failed/узел offline) →
  тосты + трей; правила настраиваются per-host/per-cluster.
- Дедупликация алертов, quiet hours, severity-уровни; webhook retry.
- Webhook-канал (первый шаг к уведомлениям VISION.md; Telegram/Email — позже).

#### M10. Платформа ⏳
- Доменные модели бэкапов (снять техдолг «dict'ами до B17»).
- Feature-плагины: Notifications как плагин (шов из Plugin API).
- **Профили подключений (B25)**: справочник профилей в config.sqlite,
  поле профиля у кластера, активный профиль, переключатель в UI; кластеры
  вне активного профиля — скрыты/спят (без переподключений); автозапуск
  с последним профилем. Сценарий: несколько площадок/VPN, работа по одной
  организации за раз.
- PVE compat matrix — detection уже в M0.5, здесь — расширение таблицы
  capabilities по мере фич.
- Массовые операции по VISION.md целиком: bulk migrate (выбор target
  node), bulk clone, bulk delete, bulk snapshot/backup — единый механизм
  (план + прогресс + отмена, как в B3).

#### M11. UI-паритет с офиц. PVE ⏳ — в конец списка, приоритеты определим (см. B23)
Цель: «не возвращаться в офиц. UI». Карта паритета проверена по коду (2026-09-10).
Разбит на подвехи (hardware editor — отдельный крупный проект).
- **M11a.** Tags ВМ (редактирование + фильтры), PVE-ноты ВМ/CT,
  Services: restart/stop/start (сейчас только просмотр), Updates
  read-only badge («доступно N») — строго без установки.
- **M11b.** xterm-консоль CT (через наш WsBridge; техоснова готова),
  Node Syslog viewer (+follow).
- **M11c.** Полный Hardware-редактор ВМ/CT (список устройств, Add/Remove/Edit,
  boot order, PCI/USB passthrough; сейчас — правка полей по одному),
  Node Disks: список, S.M.A.R.T., wipe/initialize.

### Идеи без вехи (добавляются «по ходу песни»)

- Долгосрочный банк идей из анализа ProxCenter — **`docs/PROXCENTER_IDEAS.md`**
  (26 разделов: проблемы-центр, глобальный поиск, backup matrix, migration
  wizard, bulk ops, Saved Views, топологии, Wave A/B/C). Не roadmap и не
  обязательства: сначала оценка относительно текущего плана, приоритет —
  функциям, усиливающим преимущества VirtDeck (см. §26 дока).
- B10 Replication: zfs replication между нодами
  (`GET/POST/DELETE /nodes/{node}/replication`) — кандидат в M10+.
- Управление кластером после создания: link-топология, перемещение нод
  (кандидат из 2.13).
- Site/Datacenter-сущности из VISION.md (фундамент — группы B16).
- Аналитика-тренды из VISION.md (рост storage, uptime, частота ошибок).
- Policy Engine (рекомендации → approve → автоматика) — v3.x/v4.
- Ceph-плагин (плагины VISION.md); SDN-панель — ниша.
- **DR-режим** (из Xen Orchestra Incremental Replication/DR): массовый
  restore парка из PBS в другой кластер одной кнопкой («поднять сайт Б
  из снапшотов») — без фонового планировщика, desktop-feasible.
- **Capacity forecasting** (из Nutanix Prism Capacity Runway / What-if):
  тренды rrddata → прогноз «ресурсы кончатся через ~N дней» + сценарий
  «если добавить X ВМ — хватит ли». Данные уже собраны, чисто клиентские
  расчёты; приёмник идей — инвентарь-отчёты.
- **Affinity rules UI** (`/cluster/ha/rules`, PVE 9 — API есть, UI нет
  ни у кого).
- **zfs send/receive по SSH для cross-cluster** — путь минимизации
  downtime при будущей разморозке M3 (внутрикластерный pvesr не работает
  между кластерами; B10 — только внутри).
- Инвентарь-отчёты CSV/HTML (парк ВМ, теги, рост storage).

### Явно НЕ в 3.0

Мобильный клиент; серверная часть (v4.0); IaC/terraform; дублирование
Pulse; Telegram/Email/Matrix-каналы уведомлений; **firewall-управление**
(периметр закрывает железо/гостевые фаерволы — осознанное решение);
**update management** (установка обновлений — опасная зона, read-only
badge в M11 достаточно); **DRS/load balancing** (XO/ProxCenter-стиль —
требуют постоянно живущего сервера, не desktop-архитектура).

## v3.5 — Платформа
- ✅ Стабильная модель объектов (миграция UI с dict на доменные модели завершена в v2.10)
- ✅ Data Provider API: шов `DataProvider` (Protocol) + фасад `ProxmoxProvider`
  (`provider/_provider.py`); backend и metrics работают через фасад
- ✅ Plugin API (seed): `plugins/` — `ProviderPlugin` + `PluginRegistry`, диспетчеризация
  `create_provider(cfg)` по `cfg["type"]`; feature-плагины (Notifications, Policies, ...)
  — продолжение шва

### Техдолг миграции (осознанно не переводится на доменные модели)
- Backups-таблица и vzdump/backup jobs — dict'ами до B17 (модели бэкапов появятся там)
- rrddata / metrics (`ui/api/metrics.py`) — числовые сэмплы, dict оправдан
- VmDetailWorker / вкладка Config — глубоко вложенный PVE-конфиг, моделирование дорого при малой пользе
- Config-словари (`cfg["group"]`, тела POST-запросов) — dict по дизайну, не PVE-ответы

## v4.0 — Опциональная серверная часть
- Inventory
- Централизованный Cache
- History
- Event Bus
- REST API / WebSocket
- **Async-контракт поверх DataProvider**: текущий sync-фасад (QRunnable
  сверху) не переписываем заранее (YAGNI), но Protocol не цементировать
  как чистый request/response — оставить место под push-события
  (WebSocket-канал подписки), чтобы server mode не заставил переписывать UI.

## v4.5
- Audit
- Notifications
- CLI

## v5.0 — Policy Engine и автоматизация
- Рекомендации
- Affinity / Anti-affinity
- Балансировка нагрузки
- Maintenance policies
- DRS-подобные возможности
- Предиктивная аналитика
