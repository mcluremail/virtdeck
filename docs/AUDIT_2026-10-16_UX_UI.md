# Аудит UX/UI — отчёт (серия UX, этапы UX-0…UX-8)

Дата начала: 2026-10-16. План: [AUDIT_2026-10-16_UX_UI_PLAN.md](AUDIT_2026-10-16_UX_UI_PLAN.md).
Статус: **завершён (UX-0…UX-8)**. Отчёт копился по этапам; консолидация — UX-8.
Маркировка находок: `U*` (usability), `A*` (aesthetics) — присваиваются в
этапе, где находка подтверждается; в UX-0 идут как **кандидаты** с маршрутом.

## Рубрика эстетики (эталон, зафиксирована до поиска дефектов)

1. **Иерархия и приоритет взгляда**: статус → объект → действие; уровни
   различимы размером/весом, а не только цветом.
2. **Единый визуальный язык**: одна шкала отступов, одна типографическая
   шкала, сетка выравнивания; близкое сгруппировано (закон близости).
3. **Цвет = смысл**: DANGER/WARN/OK только семантически; одинаково на всех
   поверхностях и темах; декоративного цвета нет.
4. **Правда аффордансов**: кликабельное выглядит кликабельным, disabled
   очевиден, hover/pressed читаются.
5. **Плотность операторского инструмента**: насыщенно, но сгруппировано.
6. **Типографика данных**: VMID/IP/даты — mono; усечение предсказуемо.
7. **Ритм и полировка**: согласованные радиусы, бордюры, паддинги.

Иконки — вне объёма (отдельная тема). Эталон — собственный язык приложения и
конвенции операторских инструментов (Proxmox VE, virt-manager), не «под Apple».

---

## UX-0. Картография (2026-10-16)

### Метод и среда

- Автономный скрипт (артефакт: `/tmp/opencode/ux_audit/instantiate.py`) с
  runtime-контрактом тестов (`tests/ui.runtime_contract`: guard + fake pool +
  autofire + pyqtgraph-шимы), `QT_QPA_PLATFORM=offscreen`, пустой конфиг
  (XDG_CONFIG_HOME → свежий tmp): каждая поверхность конструируется, показывается
  и захватывается `grab()` → PNG в `/tmp/opencode/ux_audit/ux0/`.
- **26 из 26 поверхностей создаются без живого PVE/PBS.** Для
  `NoVncWindow` (`console/window.py:40`) потребовался программный рендер
  WebEngine (`QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu"`): без флага процесс
  падает на offscreen-EGL. Содержимое VNC-вью — только с живым хостом;
  собственный UI окна (тулбар sticky-модификаторов) рендерится полностью.
- Шрифты в рендерах — fallback-подстановка среды; для межтемных/межэтапных
  сравнений среда одинакова, абсолютная типографика — с поправкой на это.

### Реестр поверхностей

| Поверхность | Модуль / класс | Точки входа | Состояние по умолчанию (пустой конфиг) | Инстанциация |
|---|---|---|---|---|
| Главное окно | `mainwindow.MainWindow` | запуск, трей «Show window» | тулбар + дерево «No servers added» + «Select object in tree» + док задач + статус-бар | OK |
| Дерево объектов | `tree_panel.TreePanel` | главное окно (левая колонка) | режим combo (Hosts/Storages/Backup servers), empty-state честный | OK |
| Detail-панель | `detail_panel.DetailPanel` (+ `_vm_tabs`, `_host_tabs`, `_storage_tabs`, `_worker_manager`) | правая колонка, выбор в дереве | «Select object in tree» | OK |
| PBS-панель | `pbs_panel.PbsPanel` | правый стек (режим Backup servers) | голая шапка таблицы datastore, без сообщения | OK |
| Fleet Health | `fleet_health.FleetHealthDialog` | тулбар, трей, Ctrl+Shift+F | кнопки + таблица + «No issues found» (при 0 целей!) | OK |
| Глобальный поиск | `search_dialog.GlobalSearchDialog` | тулбар, Ctrl+F | ввод + пустой результат | OK |
| Command palette | `command_palette.CommandPalette` | Ctrl+K | «Type a command…» + список | OK |
| Уведомления | `notification.NotificationManager` / `FadeToast` | программные | — (не рендерится в UX-0) | — |
| Консоль noVNC | `console.window.NoVncWindow` | контекстное меню VM → Console/noVNC | тулбар sticky-клавиш; VNC-вью пуст (нет хоста) | OK (`--disable-gpu`) |
| О программе | `about_dialog.AboutDialog` | тулбар, палитра | — | OK |
| Добавить сервер | `add_server_dialog.AddServerDialog` | тулбар, Ctrl+N, палитра | форма Connection/Token, Add disabled | OK |
| ACL | `acl_dialog.AclDialog` | detail-панель (вкладка ACL) | Path/Type/Principal/Role, Add primary | OK |
| Backup job | `backup_job_dialog.BackupJobDialog` | PBS-панель | storages/job/pools | OK |
| Клон VM | `clone_vm_dialog.CloneVMDialog` | контекстное меню, палитра | vm_info + target/storage combos | OK |
| Создание кластера | `cluster_create_dialog.ClusterCreateDialog` | контекстное меню хоста | cfg_name | OK |
| Вход в кластер | `cluster_join_dialog.ClusterJoinDialog` | контекстное меню кластера | candidates + cluster_name | OK |
| Создание VM | `create_vm_dialog.CreateVmDialog` | контекстное меню хоста/кластера, палитра | General/CPU&Memory/System, **кнопки внутри скролла** | OK |
| Группа | `group_dialog.GroupDialog` | контекстное меню группы | group | OK |
| Миграция VM | `migrate_vm_dialog.MigrateVMDialog` | контекстное меню, палитра | vm_info + target combo | OK |
| Роль | `role_dialog.RoleDialog` | ACL | role/privs | OK |
| Конфиг хранилища | `storage_config_dialog.StorageConfigDialog` | контекстное меню, detail | Create storage…: ID/Type/Content/Nodes/Enable/Path | OK |
| Токен | `token_dialog.TokenDialog`, `TokenValueDialog` | хост, refresh token | userid/token/users | OK |
| Пользователь | `user_dialog.UserDialog` | ACL | user/groups | OK |
| Редактор поля конфига VM | `vm_config_editor_dialog.VmConfigEditorDialog` | detail (Options) | key/label/field_type/current_value | OK |
| Восстановление из бэкапа | `vm_restore_dialog.VmRestoreDialog` | detail (Backup) | volid/vm_type | OK |
| VZDump | `vzdump_dialog.VzdumpDialog` | контекстное меню VM/детали | vmid/storages | OK |
| Виджеты | `widgets/*` (card_list, cluster_tasks_widget, metric_card, spinner, time_range, vm_hardware/metrics/options/pool/task_history) | внутри поверхностей | рендерятся в составе вкладок detail | (в составе) |

### Точки входа (инвентарь)

1. **Тулбар** (`mainwindow.py:317-384`): add, refresh, search, fleet | export,
   import | about, quit + brand. Стиль `ToolButtonIconOnly` (317-323).
2. **Трей** (`mainwindow.py:2705-2725`): Show window, Refresh, Fleet Health,
   Quit.
3. **Контекстные меню дерева** (`tree_panel.py:523-676`): ветки vm (вкл.
   bulk при мультивыборе), host, cluster, group, storage. **Нет веток** для
   `pbs`, `pbs_datastore`, `pool` (и для пустой области).
4. **Command palette** (Ctrl+K): 41 ActionSpec (8 глобальных + 33 tree,
   `action_specs.py`).
5. **Шорткаты** (`mainwindow.py:386-393`): Ctrl+R, F5, Ctrl+Q, Ctrl+N, Del,
   Ctrl+F, Ctrl+Shift+F, Ctrl+K.
6. **Статус-бар**: язык (6 локалей, смена = рестарт), тема (5), метрики
   Hosts/VMs/CPU/RAM + часы.
7. **Combo режимов дерева** (`tree_panel.py:295-309`): hosts / storages / pbs.
8. **Навигация**: `search/fleet.object_selected → tree_panel.reveal_key`;
   `detail.navigate_requested → find_and_select` (B20-ключи).

### Матрица «действие × точка входа» (черновик)

Глобальные (палитра — все 8 спецификаций):

| Действие | Палитра | Тулбар | Трей | Контекст-меню | Шорткат | Примечание |
|---|---|---|---|---|---|---|
| Add server | ✅ | ✅ | — | — | Ctrl+N | |
| Refresh | ✅ («Refresh data») | ✅ («Refresh») | ✅ («Refresh») | — | Ctrl+R, F5 | **3 ярлыка одного действия** |
| Global search | ✅ | ✅ | — | — | Ctrl+F | |
| Fleet Health | ❌ **нет spec** | ✅ | ✅ | — | Ctrl+Shift+F | пробел покрытия палитры |
| Export / Import | ✅ | ✅ | — | — | — | |
| About | ✅ | ✅ | — | — | — | |
| Quit | ✅ (dangerous) | ✅ (без иконки) | ✅ | — | Ctrl+Q | |
| Delete (object.delete) | ✅, scopes: все 9 типов | — | — | — | Del | **нооп для group/storage/pbs/pool** (см. находки) |

Tree-действия (33): все — в палитре; в контекстных меню — по типу объекта;
ярлыки/иконки/enabled — из одного `ActionSpec` (`tree_panel._add_action_specs`).
Только в меню, вне реестра: «Edit note…» (vm/host/cluster/group/storage),
«Trust SSL certificate» (host), «Move to group» (host/cluster).

### Находки-кандидаты UX-0 (маршрутизация)

| # | Наблюдение | Обоснование (file:line) | Маршрут |
|---|---|---|---|
| 1 | Палитра показывает «Delete» для всех типов объектов (scopes = 9 типов), но `Del`/invoke обрабатывают только vm/host/cluster — для group/storage/pbs/pool действие **молча ничего не делает** | spec: `action_specs.py:331-337`; обработчик: `tree_panel.py:1511-1533` | UX-4 ✅ подтверждён кодом и runtime-матрицей → **U13 (U-HIGH)** |
| 2 | Кнопки Create/Cancel диалога создания VM внутри скроллируемого контента: при ограниченной высоте уходят за пределы видимости (в отрендеренном кадре кнопок нет); в `add_server` кнопки вне скролла — анатомия диалогов непоследовательна | `create_vm_dialog.py:433-447` (footer → `form`, затем `scroll.setWidget(content)`); сравнение: `add_server_dialog` | UX-5 ✅ подтверждён кодом, рендером и замером (717px контент / 408px вьюпорт) → **U19 (U-MEDIUM)** |
| 3 | Fleet Health отсутствует в палитре (нет spec), хотя есть в тулбаре/трее/шорткате | `action_specs.py` (нет fleet-spec); `mainwindow.py:343-348` | UX-4 ✅ → **U15 (U-MEDIUM)** |
| 4 | Три ярлыка одного действия Refresh: «Refresh data» (палитра) / «Refresh» (тулбар) / «Refresh» (трей) | `action_specs.py:297-302`; `mainwindow.py:331`; `mainwindow.py:2714` | UX-4 ✅ переформулирован: точки входа консистентны (все → `refresh_data`); реальная проблема — скрытый F5 и ручные биндинги → **U16 (U-LOW)** |
| 5 | Quit — текстовый элемент в иконочном тулбаре (`ToolButtonIconOnly`, у QAction нет иконки) | `mainwindow.py:317-323, 372-375` | UX-2 ✅ → **A11** |
| 6 | Fleet Health при **нулевом числе целей** пишет «No issues found» — проверка не выполнялась, текст читается как «проверено, чисто» (наследие D4: молчание = норма) | `fleet_health.py:191` | UX-3 ✅ → **U6 (U-MEDIUM)** |
| 7 | PBS-панель в пустом состоянии — голая шапка таблицы без пустого-state сообщения (контраст: дерево имеет «No servers added») | рендер `panel.pbs.png`; `pbs_panel.py` | UX-3 ✅ → **U7 (U-MEDIUM, повышен)** |
| 8 | Инлайн-QSS с хардкодом (12px, padding 4px 12px) в двух контекстных меню мимо токенов темы | `tree_panel.py:535-539, 580-584` | UX-1 ✅ → **A1 (A-MEDIUM)** |
| 9 | `ActionSpec.shortcut` — декларативен; реальные QShortcut ставятся вручную в mainwindow, тулбар-тултипы дублируют шорткаты строками — риск расхождения при изменении | `action_registry.py:79-80`; `mainwindow.py:326,386-393` | UX-4 ✅ расхождений сегодня нет (Ctrl+N/R/F/Q/Del согласованы); структурный риск → в **U16** |
| 10 | Для типов `pbs`, `pbs_datastore`, `pool` нет контекстного меню вовсе; вопросов: как из UI удаляется PBS-сервер; чем управляется pool | `tree_panel.py:523-676` (нет веток); `_build_tree:779-800, 1002` | UX-4 ✅ подтверждено (runtime: CTX [pool] = None); правый клик без меню — приемлемо, но в паре с нооп-Delete из U13; удаление PBS/pool как фича отсутствует |

### Открытые вопросы к следующим этапам

- Видимость вкладок detail-панели и PBS-панели с данными (UX-2 даст рендеры
  непустых состояний на тестовой сцене).
- ~~Полная матрица enabled/disabled для tree-действий по типам selection
  (UX-4)~~ — закрыто в UX-4: `/tmp/opencode/ux_audit/ux4/matrix.txt`.
- ~~Поведение `object.delete` для storage…~~ — закрыто в UX-4 (U13: нооп
  дублирует рабочий `storage.delete`).
- Рендер консоли — вынести в отдельную проверку вне offscreen (среда).

### Live-проход (read-only, по решению владельца; прод-инфраструктура)

**Метод.** Бандл владельца `~/virtdeck-nodes.enc` (13 нод: 12 PVE + 1 PBS,
токены вшиты) расшифрован штатным кодом приложения в tmpfs-файл 0600; в чат и
отчёт — только счётчики. Скрипт наблюдения с трёхуровневой защитой:
1. транспортный guard — `requests.Session.request` поднят на raise для любого
   не-GET (накрывает proxmoxer/PVE, PBS-клиент, update-проверки);
2. ловушка модалок — `QDialog.exec`/`QMessageBox`/`QInputDialog` патчи
   «записать и закрыть», ни один диалог не исполняется;
3. без invoke/кликов — только построение, выбор элемента дерева (локальное
   состояние) и `grab()`.
Фактически: 3 прогона, ~50 кадров, не-GET заблокирован 1 раз (PBS-логин,
POST /access/ticket — поэтому PBS-панель в live-кадрах без авторизации; PBS
состояния покрываются заглушками). Сеть с машины аудита до прода деградирована:
первая VM появилась через 92,8 с; из 10 ответивших хостов 9 с ошибками — кадры
фиксируют UX деградированной сети (худший случай честности), плотные
«здоровые» кадры — частично (1 хост, 7 VM).

**Кандидаты от live-данных (маршрут UX-3, если не указано иное):**

| # | Наблюдение | Доказательство |
|---|---|---|
| L1 | Экран ошибки хоста показывает красный текст «… is unavailable» + подсказку, но спиннер загрузки под ним **продолжает крутиться** — одновременные «ошибка» и «загрузка» | `live3_detail_host_bad.png` |
| L2 | VM-detail: два индикатора загрузки одновременно («Loading detailed Info...» вверху + центровой спиннер «Loading...»), регистр и формулировки расходятся | `live3_detail_vm.png` |
| L3 | Семантика счётчиков сводки неоднозначна во время обновления: «Hosts: 0/1» → «1/10» при 12 настроенных PVE и 14 строках в дереве; знаменатель — «ответившие», а не «настроенные» | `live_mainwindow_hosts.png`, `live3_mainwindow_populated.png` |
| L4 | Группа с 9 настроенными хостами пишет «0 hosts · 0 online» + «No data» — нули честные, но формулировка читается как «хостов нет» | `live3_mainwindow_populated.png` |
| L5 | Недостижимые хосты крутят спиннер без таймаута/обратной связи (2 хоста крутили 120+ с); в статус-баре нет сигнала «обновление завершено» — оператор не отличает «ещё грузится» от «висит» | `live2_mainwindow_populated.png`, `live3_mainwindow_populated.png` |
| L9 | Карточка QUORUM на кластере с ошибкой крутит спиннер бесконечно, а в detail группы при том же отсутствии данных показывается «—» — два разных представления пустоты/ошибки у одинаковых карточек | `live4_detail_cluster.png` vs `live4_mainwindow_hosts.png` |
| L10 | Док задач: таблица с заголовками и фильтром, но без единой строки и без empty-state сообщения — «пустота с колонками» | `live4_mainwindow_hosts.png` → U-LOW |
| L6 | VM-detail: у disabled-кнопки Console видима стрелка-dropdown — аффорданс меню на неактивной кнопке | `live3_detail_vm.png` → UX-2 |
| L7 | Заголовок VM — крупный курсивный name без VMID (VMID ищется в вкладках) → UX-2/UX-6 | `live3_detail_vm.png` |
| L8 | Режим дерева персистится между запусками приложения (B20, load_ui_state) — по дизайну; зафиксировано как факт карты | run 2 стартовал в PBS-режиме |

**Положительные паттерны (фиксируются как эталон — не ломать при фик-ах):**
красный экран ошибки хоста с конкретной подсказкой («SSL certificate
self-signed — enable Trust SSL in context menu»); красные точки-ошибки на
иконках хостов в дереве + счётчик Errors в статус-баре; «Loading fleet
data...» в Fleet Health; метка «SSL trusted» на карточке ADDRESS; честные
disabled-состояния кнопок VM; спиннер внутри пустого графика мониторинга.

**Дополнение 4-го прогона (после открытия firewall до кластера):** инверсия
кнопок VM по состоянию честна в обоих направлениях (остановленная: только
Start; работающая: Shutdown/Reboot/Reset/Stop + активный Console с dropdown);
cluster-detail («ROS», 8 вкладок) показывает ошибочный хост строкой таблицы
(status error, uptime «—»), group-detail («LTN сервера ИБ», 2 вкладки) —
набор вкладок другой (карта: group ≠ cluster). Уточнение L6: стрелка на
Console — by design (dropdown вариантов), дефект лишь в том, что стрелка
видна и на disabled-кнопке. Заметка UX-2: брайлевский спиннер обновления в
статус-баре (`mainwindow.py:257-264`, индекс 0) при 12px читается как шум
из точек — в кадрах неоднократно принимался за артефакт рендера.

## UX-1. Дизайн-система и тема-движок (2026-10-16)

### Метод

Чтение: `theme.py` (Color-фасад, 36 канонических токенов + 2 шрифтовых,
QSS-шаблон, движок `load_theme`/`validate_tokens`), `docs/THEMES.md`
(контракт v1: «widgets never hardcode colors — they read
`theme.Color.TOKEN`»), `brand.py`, `hover.py`, `optimistic.py`. Серия
grep'ов по `virtdeck/ui/*.py`: `setStyleSheet`, hex/rgb-литералы,
`QColor(`/`QBrush`, `QFont`/`setPointSize`/`setPixelSize`,
`font-family`/`font-size`-литералы, `setContentsMargins`,
`subscribe_theme_changed`. Иконки исключены (отдельная тема).

### Матрица «файл × токены vs хардкод»

62 вызова `setStyleSheet` в 21 файле. Вне `theme.py`: **0** hex/rgb-литералов
цветов; все `QColor(`/`QBrush` — через токены (включая словари
`VERIFY_COLORS`, `_usage_color()`); brand/hover/optimistic — чисты.

| Файл | QSS | Токен-источник | Замечания |
|---|---|---|---|
| mainwindow | 6 | 6 | A5 (дубль стиля комбо) |
| tree_panel | 3 | 3 | A1 (дрейф семантики QMenu ×2) |
| detail_panel | — | — | `reapply_theme()` ✓ |
| pbs_panel | 6 | 6 | A7 (нет reapply → устаревание) |
| fleet_health | 1 | 1 | диалог на один показ — ок |
| command_palette | 4 | 4 | `retheme()` ✓ |
| notification | 3 | 2 | A2 (`color: white` + string-surgery) |
| add_server_dialog | 5 | 4 | A3 (`monospace` ×2) |
| about_dialog | 8 | 8 | A4 (`setPointSize(20)`) |
| vm_device_editors | 14 | 14 | 2× `font-weight: bold` мимо QSS |
| vm_config_editor | 3 | 3 | — |
| остальные 11 файлов | по 1–2 | все | чисто |

Шрифтовая шкала (литералы `font-size`): 11px×22, 13px×17, 12px×15,
14px×3, 22px×1 — три соседних кегля (11/12/13) для вторичного текста
используются взаимозаменяемо. Отступы: `setContentsMargins(16,16,16,16)`
доминирует (27×), хвост из разовых значений 2…28.

### Находки UX-1

| # | Серьёзность | Находка |
|---|---|---|
| A1 | 🟡 A-MEDIUM | Контекст-меню дерева: inline-QSS (`tree_panel.py:535-539, 580-584`, копипаста дважды) перекрашивает выделение пункта в `Color.BORDER` (серый), тогда как глобальный QSS темы (`theme.py:574-577`) — `ACCENT_LIGHT`+`ACCENT` (синий). Два визуальных языка меню в одном приложении; inline-QSS дублирует и искажает глобальный селектор |
| A2 | 🟡 A-LOW | `notification.py:41`: `color: white` — цветовой литерал-ключевое слово вместо `Color.ON_ACCENT`; там же обратная связь копирования сделана string-surgery по QSS (`styleSheet().replace("color: white;", …)`) — хрупко |
| A3 | 🟡 A-LOW | `add_server_dialog.py:164,172`: `font-family: monospace` мимо токена `Color.MONO_FONT` — на системах, где Qt резолвит `monospace` иначе, mono-лейблы токена разойдутся с остальными mono-поверхностями |
| A4 | 🟡 A-LOW | `about_dialog.py:23`: `setPointSize(20)` — абсолютный кегль заголовка, не масштабируется с системным шрифтом |
| A5 | 🟡 A-LOW | `mainwindow.py:268`: QSS комбика языка продублирован inline вместо вызова `_status_combo_style()` (который используется и при re-apply) — латентный дрейф |
| A7 | 🟡 U-LOW | Покрытие смены темы неполное: `_on_theme_applied` (`mainwindow.py:2656-2670`) обновляет дерево/detail/палитру/иконки/бренд, но **не pbs_panel** — статус-метки и цвета usage-баров держат старую тему до следующего обновления данных. **Подтверждено в UX-2: 1.6:1 на graphite** (кадры `graphite.pbs_stale_a7` / `graphite.pbs_panel`) |
| A6 | 🟡 системазев | Контракт v1 токенизирует только цвета: нет токенов шрифтовой шкалы и отступов — отсюда 11/12/13px вперемешку и хвост margin-значений. Не нарушение (контракт соблюдён), а зазор на v2 |

### Положительное (эталон)

Ноль цветовых литералов вне `theme.py`; словари статуса-цветов на токенах;
`retheme()`/`reapply_theme()` у долгоживущих поверхностей; шрифты делегата
дерева — относительные (от `opt.font`, ×0.82) — масштабируются с системой;
семантика DANGER vs DANGER_SOLID и SUCCESS/STATUS_* задокументирована в
комментариях фасада и соблюдается в использовании.

---

## UX-2. Отрисованная эстетика (2026-10-16)

### Метод и объём

Рендер-матрица на тестовой сцене (`/tmp/opencode/ux_audit/ux2_render.py`,
кадры в `/tmp/opencode/ux_audit/ux2/`, 47 PNG). Сцена — «грязный» парк из
доменных объектов, без сети: кластер rep1 (pve-alpha+pve-beta), standalone
pve-gamma (offline, SSL-ошибка) и pve-delta, 8 VM (running/stopped/template/
LXC), 5 хранилищ (38/81/93%/битый статус), 3 пула, 6 задач (OK/failed), PBS
с 4 датасторами (46/78/93%/status_ok=False). Fleet — через тестовый
FakePveApi-транспорт (реальный пул, фейковая сеть), 2 кластера.

Покрытие: светлая тема × {populated, error, partial, empty} + ключевые
поверхности (mainwindow с выбором host/VM, detail, storages/pbs режимы,
PBS-панель, палитра, Create VM, Add Server, About, тосты) × 5 тем
(light/breeze/breeze_dark/oxygen/graphite). Спец-кадры: A7-застывание,
дамп структуры дерева.

Ограничения харнесса (учитывать при чтении кадров): fake pool подавляет
workers → вкладки detail без контента (chrome+плейсхолдеры), вкладки
датастора PBS (Status/Snapshots/Jobs) не отрендерены ни в одном кадре
(метод закрытия: прямой `show_datastore`+fill в UX-3); счётчики статус-бара
не устанавливаются (ставятся из worker-колбэков); VMS-карточка хоста
считает из `panel.all_vms` (`set_lists`) — в харнессе пуста, показы «0/0» —
артефакт, не дефект. Offline-нода сцены несёт метрики — артефакт данных
сцены, не UI.

### Межтемная матрица (наблюдения)

| Тема | Связность | Замечания |
|---|---|---|
| light | ✅ | эталон для сравнения; моно-иконки, статус-точки зелёные/красные |
| breeze | ✅ | светлее light; цветные иконки (контракт тем), акценты читаемы |
| breeze_dark | ✅ | цветные иконки + тёмный фон согласованы; график перекрашен (dark plot bg) |
| oxygen | ✅ | без замечаний к связности на ключевых поверхностях |
| graphite | ✅ | моно-иконки; акцентная подчёркивание вкладки читаемо; график перекрашен |

Кросс-темные константы: статус-точка = `STATUS_OK/ERR` темы (все значения —
зелёная/красная семья, `get_icon("vm", status)` без типа VM —
`tree_panel.py:729,904,1350`); usage-цвета PBS — абсолютные hex — переживают
смену темы корректно. Иконочные языки меняются между темами (mono↔color) —
допустимо по контракту, но см. A11.

### Находки UX-2

Нумерация: A продолжается с UX-1 (A8+); U-серия начинается здесь — кандидаты
UX-0 получат номера при верификации на своих этапах (UX-3/4/5).

| # | Серьёзность | Находка |
|---|---|---|
| A8 | 🟡 A-MEDIUM | **Порог WARN для «использования ресурса» разный на поверхностях**: карточки хостов/VM — WARN при ≥50%, ERR при ≥80% (`metric_card.py:125-130`); PBS usage — WARN при ≥75%, DANGER при ≥90% (`pbs_panel.py:77-83`); «норма» тоже разная — синий `ACCENT`-бар у хостов vs зелёный `SUCCESS` у PBS. Одна семантика — три цветовых словаря; оператор видит янтарный на полузагруженном хосте и зелёный на 74% датасторе. Нарушение рубрики §3.2 (цвет = смысл, одинаково на всех поверхностях). Кадры: `light.error_detail_host.png` (50%→янтарный) vs `light.pbs_panel_filled.png` (46%→зелёный, 78%→янтарный) |
| A9 | 🟡 A-LOW | Таблица задач: DESCRIPTION усекается до ~8–10 символов («Backup w…») при десятках пустых пикселей справа — ширины заданы жёстко (155/155/180, остальные дефолтные), resize-to-contents нет (`cluster_tasks_widget.py:132-147`); STATUS при этом широченная. Нарушение рубрики §3.6 (усечение непредсказуемо, площадь расходуется впустую). Кадр: `light.hosts_no_selection.png` |
| A10 | 🟡 A-LOW | PBS-таблица: единицы прыгают поячеечно (GiB→TiB: «930.0 GiB / 1,000.0 GiB» рядом с «4.5 TiB / 9.8 TiB» — `_fmt_size`), числовые колонки выровнены влево — сравнивать величины трудно. Рубрика §3.6. Кадр: `graphite.pbs_panel.png` |
| A11 | 🟡 A-LOW | Quit — единственный текстовый элемент в иконочном тулбаре (`ToolButtonIconOnly`, у QAction нет иконки; `mainwindow.py:317-323`) — закрывает кандидата UX-0 №5; виден во всех mainwindow-кадрах. Сама отрисовка иконки — вне объёма (иконки), но структурная непоследовательность панели фиксируется здесь |
| U1 | 🟡 U-MEDIUM | **Кластерное дерево: члены кластера — бездетные строки со счётчиками [N/N]**, все VM живут на уровне кластера (папки пулов + плоские no-pool VM); в строке VM нет атрибуции ноды — ни текстом, ни в tooltip (`tree_panel.py:977-1009`, `_add_vm_item:895-911`; дамп структуры подтверждает). Счётчик у члена обещает раскрытие, которого нет; для мультинодового кластера VM→нода из дерева не прослеживается вовсе. Кадр: `light.hosts_no_selection.png` (pve-beta@rep1 [2/2] без детей; db-01 из пула «db» стоит на pve-beta — в дереве не видно) |
| U2 | 🟡 U-MEDIUM | **SSL-метка ADDRESS-карточки противоречит поведению соединения**: `_host_tabs.py:847,1017` — дефолт `trust_ssl=True` → «trusted» для конфигов без ключа, тогда как соединение с тем же конфигом верифицирует строго (`_session.py:78`, `pbs/client.py:50`, `tokens.py:26` — везде дефолт False). Обратная подмена: член кластера без собственного конфига (host_cfg=None) → «untrusted», хотя прямого соединения у него нет вообще. Оператор, отлаживающий SSL-отказ, видит «trusted». Кадры: `light.host_selected.png` (gamma, конфиг без ключа → «SSL trusted») vs `light.error_detail_host.png` (beta без cfg → «SSL untrusted»). **Дополнено в UX-4**: тот же дефолт-True в чекбоксе контекст-меню дерева (`tree_panel.py:613`, runtime: «Trust SSL certificate — trusted» на конфиге без ключа) — дефолт расхождений живёт в трёх местах |
| U3 | 🟡 U-LOW | Пустая командная палитра — голое тело без подсказки/последних команд (ввод есть, результата нет); совпадает с live-наблюдением. Кадр: `breeze_dark.palette.png` |
| U4 | 🟡 U-LOW | Add Server: password-плейсхолдер «********» читается как заполненное значение (плейсхолдер маскирует сам себя). Кадр: `breeze.add_server_dialog.png` |
| U5 | 🟡 U-LOW (вкусовое) | Полностью пустое приложение показывает «Hosts: 0/0 VMs: 0/0 CPU: 0% RAM: 0%» — честно, но шумно; кандидат на скрытие до первого парка. Кадр: `light.empty_scene.png` |

**A7 (UX-1) — подтверждено визуально и численно.** PBS-панель, заполненная в
light и переключённая в graphite без обновления данных: текст «Updated just
now» держит застывший light-TEXT_SEC — измеренный цвет текста #55524f на
фоне #232323 ≈ **1.6:1 (нечитаем)**; после повторного заполнения в graphite —
#a9adb1 ≈ 7:1. Кадры: `graphite.pbs_stale_a7.png` vs `graphite.pbs_panel.png`.
Механизм по коду: `pbs_panel` не подписан на смену темы, captured QColor
живут до следующего `_render_ops`/fill.

### Кросс-свидетельство live-находок (на заглушках)

- **L1/L5** — offline-хост: график мониторинга крутит «Loading...» без
  состояния «нет данных (offline)» (`light.error_detail_host.png`).
- **L6/L7** — заголовок VM во всех темах без VMID (`light.vm_selected.png`,
  `breeze_dark.detail_vm.png`, `graphite.detail_vm.png`).
- **L10** — пустой dock задач: заголовки+фильтр без empty-state
  (`light.error_scene.png`, `light.partial_scene.png`).
- Кандидат UX-0 №2 (Create/Cancel за скроллом): кадр
  `graphite.create_vm_dialog.png` — при дефолтной высоте футер не виден
  (форма обрезана на BIOS-строке) — свидетельство в пользу кандидата.

### Положительное (эталон)

- PBS usage-цвета — семантические абсолютные hex: честно переживают смену
  темы; «—» вместо выдуманных цифр у датастора с битым статусом (D1).
- Fleet Health на данных — образец рубрики: семантические цвета, честный
  футер «10 issues on 2 clusters», «Up to date» без декоративного зелёного.
- Empty-state дерева с действием-подсказкой «Press + to add».
- Графики корректно перекрашиваются в тёмных темах (dark plot bg, сетка,
  оси — `breeze_dark.detail_vm.png`, `graphite.detail_vm.png`).
- Честные disabled: Start у running VM, Resume у не-paused, тосты округлы и
  читаемы (белый на семантическом фоне ≈ 4.5:1+).
- Формы (Create VM, Add Server): секции с разделителями, двухколоночная
  сетка, информативные плейсхолдеры, helper-текст про API-токен.

---

## UX-3. Состояния загрузки, ошибок и пустые (2026-10-16)

### Метод

Код-верификация пар «loading → результат/ошибка» по всем поверхностям +
прицельные кадры: стартовое окно до первых данных (`ux3/startup_loading.png`),
PBS-панель до выбора сервера (`ux3/pbs_initial.png`); переиспользованы кадры
UX-0 (`fleet_health.png` — 0 целей, `search_dialog.png` — пустой поиск) и UX-2
(error/partial/empty сцены). Инвентаризация таймаутов транспорта.

### Инвентарь состояний (свод)

| Поверхность | Loading | Ошибка | Пустое | Вердикт |
|---|---|---|---|---|
| Дерево | спиннер-иконки хостов/кластера; VM optimistic-спиннер (confirm/rollback) | красная иконка error-ноды | «No servers added» + подсказка ✅ | структура прыгает (U9); tooltip без причины (U10) |
| Статус-бар | брайль-спиннер 12px, самогасится (`_tick_spinner` по `_soft_refresh_active`) | — | счётчики 0/0 (U5) | завершение перцептуально не видно (U8) |
| Detail хост | «Loading detailed info...» | блок «❌ {host} is unavailable» + `parse_pve_error` (DANGER, `_host_tabs.py:749-760`) | «Select object in tree» ✅ | образцовая пара |
| Quorum-карточка | `start_loading()` (значение скрыто) | `stop_loading` + «Cluster status unavailable» WARN (`_host_tabs.py:2020-2024`) | «—» до загрузки ✅ | обработан; live L9 — следствие U8 (нет дедлайна worker'а) |
| PBS-панель | статус-лейбл молчит при загрузке датасторов (`_start` не сигнализирует) | `_on_worker_failed` → красный текст статуса ✅ | до выбора сервера — голые заголовки (U7); «—» у битого датастора ✅ | тихая загрузка |
| Задачи dock | `set_placeholder(«Loading tasks...»)` (`mainwindow.py:2321`) | ошибки тасков — не в dock | финал с 0 задач и старт — голые заголовки (U12; рефайн L10) | placeholder не доиспользован |
| Fleet | worker → таблица | «N with incomplete data» + snapshot-scan дисклеймеры ✅ | 0 целей → «No issues found» (U6) | футер честный, кроме 0 целей |
| Поиск / палитра | мгновенные (локальные) | — | голое тело (U3, U11) | |
| Транспорт | timeout 15s: `_session.py:92`, `pbs/client.py:37` | raise → error-сигналы | — | дедлайна worker'а нет (U8) |

### Находки UX-3

| # | Серьёзность | Находка |
|---|---|---|
| U6 | 🟡 U-MEDIUM | **Fleet Health при 0 целей пишет «No issues found»** — проверка не выполнялась, текст читается как «проверено, чисто» (наследие D4 «молчание = норма»). Код: `fleet_health.py:190-192` (bundles=[] → total_issues=0 → ветка else; guard'ы `incomplete`/`scan_failed` при 0 бандлов не срабатывают). Кадр: `ux0/fleet_health.png` — пустая таблица + «No issues found». Закрывает кандидата UX-0 №6. Фикс-словарь: «No clusters configured» / «Add targets to run the check» |
| U7 | 🟡 U-MEDIUM | **PBS-панель до выбора сервера — каркас без контента и без подсказки**: ни титула (лейбл пуст до `show_server`), ни статуса, ни «Select a backup server» — только шапка таблицы датасторов и горизонтальный скроллбар. Кадр: `ux3/pbs_initial.png`; `pbs_panel._build_ui/show_server:286-301`. Закрывает кандидата UX-0 №7 (там LOW/MEDIUM — после рендера видно, что состояние регулярное: auto-select первого сервера нет) |
| U8 | 🟡 U-MEDIUM | **Нет дедлайна worker'а и явного сигнала завершения обновления**: транспортные таймауты 15s есть (`_session.py:92`, `pbs/client.py:37`), но мульти-запросные workers (cluster status, detail config+rrd, PBS `status→datastores→snapshots→namespaces`) умножают ожидание — минуты спиннеров при деградации сети (live L5, L9). Завершение обновления обозначается только исчезновением 12px серого брайль-спиннера (`theme.py:839` — font-size 12px, `TEXT_SEC`) — перцептуально неотличимо от «ничего не было»; штампа «обновлено в HH:MM» в главном окне нет (паттерн уже есть в PBS — «Updated just now»). Live-корни: L5, L9 |
| U9 | 🟡 U-LOW | **Структура дерева прыгает между loading и loaded**: на старте видны только спиннер-строки хостов/кластера плоско, группы (PROD/STAGING) и PBS-сервер появляются с данными — rep1 перескакивает под группу, соседи возникают. Нет стабильного скелетона. Кадр: `ux3/startup_loading.png` vs `ux2/light.hosts_no_selection.png` |
| U10 | 🟡 U-LOW | Tooltip ноды в дереве — CPU/RAM/Uptime (`tree_panel.py:122-126`), поля error нет: у недоступного хоста показываются бессмысленные метрики, причина отказа («SSL: certificate verify failed») видна только по клику в detail. Для error-ноды tooltip должен начинаться с причины |
| U11 | 🟡 U-LOW | Пустой GlobalSearchDialog — заголовки TYPE/NAME/LOCATION без подсказки («Start typing…» / недавние объекты). Кадр: `ux0/search_dialog.png` |
| U12 | 🟡 U-LOW | Задачи dock: плейсхолдер существует (`cluster_tasks_widget.py:330`, вызов только в loading-пути `mainwindow.py:2321`), но финальное «0 задач» и стартовое состояние — голые заголовки с фильтром. Переиспользовать `set_placeholder(«No tasks in the last 24h»)`. Рефайн L10 |

### Положительное (эталон)

- Пара loading/error у detail-хоста: спиннер → «❌ {host} is unavailable» с
  человекочитаемой причиной (`parse_pve_error`) — модель честного отказа.
- PBS: ошибки — красным в статус-строке; «—» вместо выдуманных цифр у
  датастора с недоступным статусом (D1); честный отказ при
  `_MAX_PBS_WORKERS`.
- Quorum: «—» до загрузки, WARN-лейбл при отказе — спиннер не застревает
  (обработчик `_on_cluster_status_error` есть; live-застревание — следствие
  U8, а не отсутствия обработчика).
- Таймауты 15s на обоих транспортах; optimistic-pending разрешается
  confirm/rollback следующим циклом.
- Пустое дерево — единственное empty-state с действием-подсказкой.

---

## UX-4. Карта «действие × точка входа» (2026-10-16)

### Метод

Код-разбор реестра (`action_registry.py`, `action_specs.py`, 44 spec'а) +
**runtime-матрица**: реальное дерево на populated-сцене, для каждого типа
элемента — построенное контекст-меню (`_build_context_menu`, без exec) и
палитра (`build_registry(mw).search("")`) с вычисленными enabled/disabled;
дамп: `/tmp/opencode/ux_audit/ux4/matrix.txt` (8 типов элементов × меню +
палитра + списки скрытых-но-выключенных). Сверка точек входа: 8 ручных
QShortcut, 8 тулбар-кнопок, трей (4 пункта), контекст-меню.

### Матрица «действие × точка входа» (свод)

| Тип | Контекст-меню | Палитра (видимых) | Расхождения |
|---|---|---|---|
| vm running | 16, disabled по статусу ✅ | 19 (глобал+11 vm) | дубль «Delete»/«Delete VM» |
| vm stopped | 16, зеркально ✅ | 15 | — |
| ct | как vm, без Convert | 19 | — |
| template | Clone/Convert to VM/Delete VM ✅ | **только глобал+«Delete»** | **U14**: скоупы без SCOPE_TEMPLATE |
| host | 6 спек + Trust SSL + группы + note | 14 | menu-only по дизайну |
| cluster | 4 + группы + note | 12 | `create_storage` виден в палитре всегда, в меню — только в режиме storages |
| group | Rename/Delete/note | 10 | дубль Delete: рабочий + нооп |
| storage | Edit/Delete (api-host) + note | — (не в hosts-режиме) | object.delete — нооп |
| pool | **None** | 8 (глобал+нооп Delete) | **U13** |
| pbs | None (код: fall-through → None) | глобал+нооп Delete | **U13** |
| пусто | — | 7 глобальных | — |

Меню показывает выключенные (семантика меню), палитра скрывает —
задокументированная разница, реализована последовательно ✅.

### Находки UX-4

| # | Серьёзность | Находка |
|---|---|---|
| U13 | 🔴 U-HIGH | **`object.delete` — включённое действие-нооп для 4 из 9 типов объектов.** Spec: scopes = все object-типы, `enabled = not sel.is_empty` (`action_specs.py:331-337`); invoke → `request_delete_current` (`tree_panel.py:1511-1535`), который ветвится только по vm/host/cluster — group/storage/pbs/pool **молча** ничего не делают. При этом клавиша Del (/mainwindow.py:390) бьёт в тот же handler, а контекст-меню group/storage удаляет рабочими спеками: оператор видит в палитре «Delete ⌫» рядом с рабочим «Delete group» и не может предсказать, что выполнится. Runtime: CTX [pool] = None, PALETTE [pool] содержит «Delete <Del>». Закрывает кандидата UX-0 №1 (predicted HIGH). Фикс: удалить `object.delete` (пер-типовые спеки уже существуют: vm/host/cluster/group/storage.delete) и биндить Del через реестр по selection |
| U14 | 🟡 U-MEDIUM | **Шаблон выпадает из палитры**: `vm.clone`/`vm.convert_*`/`vm.delete` имеют scopes `_VM_SCOPES = {vm, ct}` без `SCOPE_TEMPLATE`, при этом их enabled-правила написаны под шаблон (`convert_to_vm.enabled = sel.vm.template`). Runtime: CTX [template] — Clone/Convert to VM/Delete VM доступны; PALETTE [template] — только 7 глобальных + нооп-Delete. Оператор, нашедший действие в меню, не найдёт его в «едином реестре действий». Фикс: добавить SCOPE_TEMPLATE в scopes трёх спеков |
| U15 | 🟡 U-MEDIUM | **Fleet Health вне палитры** — единственное действие окна без spec: тулбар + трей + Ctrl+Shift+F есть, палитра (и с ней единый механизм discovery) — нет. Закрывает кандидата №3. Фикс: spec `global.fleet` (shortcut Ctrl+Shift+F) в `build_registry` |
| U16 | 🟡 U-LOW | **Скрытый F5 и ручные биндинги**: Refresh физически висит на Ctrl+R и F5 (`mainwindow.py:386-387`), но F5 не показан нигде (тултипы и палитра говорят Ctrl+R; keyword «f5» ищется, но не отображается). Все 8 шорткатов — ручные QShortcut мимо декларативных `spec.shortcut`; сегодня расхождений нет (Ctrl+N/R/F/Q/Del согласованы), защита от дрейфа — только дисциплина. Закрывает кандидатов №4 (переформулирован: 5 точек входа Refresh консистентны) и №9. Фикс: один источник — биндить QShortcut из реестра; F5 либо показывать, либо убрать |
| U17 | 🟡 U-LOW | **Деструктивные пункты меню непоследовательны**: у VM «Delete VM» последним (конвенция), у host/cluster/group — вторым-третьим сверху; `dangerous` подсвечивает красным палитру, но не меню (`_add_action_specs` не стилизует). Плюс смысловой дубль в палитре: «Delete VM» + «Delete» для VM. Фикс: деструктивные — внизу после разделителя во всех меню; стилизовать dangerous; убрать object.delete (U13 снимает дубль) |
| U18 | 🟡 U-LOW | **«Delete VM» на шаблоне** — label не отражает тип объекта (в меню и в спеке vm.delete); «Delete template» честнее. Микротекст, идёт в общий словарь фиксов |

### Положительное (эталон)

- Архитектура реестра: один ActionSpec — источник лейбла, иконки, enabled и
  invoke для меню и палитры; расхождение «меню показывает disabled / палитра
  скрывает» — осознанное и реализованное последовательно.
- Статусные enabled-правила VM: Start только у stopped, Console/noVNC только
  у running, Convert to Template запрещён running, Migrate запрещён шаблону —
  меню честно зеркалит состояние (матрица, `ux4/matrix.txt`).
- Bulk-действия реальны: ExtendedSelection + vm_keys, disabled при
  одиночном выборе, видны в меню серым.
- Тултипы тулбара несут шорткаты; dangerous в палитре подсвечен красным.
- Menu-only элементы (Trust SSL, Move to group, Edit note, Refresh token,
  Create cluster) — динамические лейблы/присутствие, задокументированы в
  докстринге `action_specs.py` как сознательный дизайн.

---

## UX-5. Формы и диалоги (2026-10-16)

### Метод

Детальный разбор двух главных форм (`create_vm_dialog.py` 637 строк,
`add_server_dialog.py` 424) + код-скан остальных ~20 диалогов по общим
критериям (кнопки вне скролла, валидация с текстом, статусы). Рендеры
(`ux5/`): `create_vm_small.png` (стартовая высота 430px),
`create_vm_tall.png` (полная), `add_server_pve.png`, `add_server_pbs.png`.
Численный замер: контент формы Create VM — **717px**, вьюпорт при
минимальной высоте окна — **408px**.

### Находки UX-5

| # | Серьёзность | Находка |
|---|---|---|
| U19 | 🟡 U-MEDIUM | **Create VM: кнопки Create/Cancel внутри скроллируемого контента** — кандидат UX-0 №2 подтверждён кодом и рендером. Footer добавлен в `form` до `scroll.setWidget(content)` (`create_vm_dialog.py:424-446`); контент 717px против вьюпорта 408px на старте (`setMinimumSize(700, 400)`) — диалог **всегда** открывается без кнопок: Disk, Network и footer за пределами первого экрана, финальные чекбоксы («Start after creation») тоже. Контраст: add_server (:214-235) и storage_config (:130-144) держат кнопки вне скролла — анатомия непоследовательна. Фикс: `layout.addWidget(scroll, 1)` + footer после скролла |
| U20 | 🟡 U-MEDIUM | **Add Server: токен не инвалидируется при изменении входов** — после «Get token» правка Host/User/Proxy/Trust SSL не сбрасывает `_token_data`; Add активна и создаёт подключение с токеном от другого хоста или с чужими настройками — обнаружится только 401 после добавления. Пароль очищается после токена (:360), что усугубляет: пользователь не может и перелогиниться, не заметив проблему. Фикс: `textChanged` → `_token_data = None`, `add_btn` disabled, статус «Token outdated — get a new one» |
| U21 | 🟡 U-LOW | **Create VM: тихие фоллбеки вместо валидации** — при пустом `storage_combo` (нода без storage) диск молча уйдёт в несуществующий `local-lvm:SIZE` (`:553`); bridge по умолчанию `vmbr0` без проверки существования; единственная валидация — пустое имя, и та без текста (красный бордер `:532`, причины нет). VMID-конфликт не проверяется в форме (только ответ API). Фикс: сообщения у полей по образцу vzdump-хинта |
| U22 | 🟡 U-LOW | **Create VM: персистентность настроек теряет index-0** — `_restore_settings` восстанавливает через `if data.get("ostype")` (`:159-178`): сохранённый index 0 — falsy и пропускается. Для `ostype` дефолт = 1, поэтому выбор «Other» теряется при каждом перезапуске; всего затронуто 9 комбо (ostype/cpu/vga/chipset/bios/scsi/bus/cache/model). Чекбоксы сделаны правильно (`is not None`) — паттерн в файле уже есть. Фикс: единый `is not None` |
| U23 | 🟡 U-LOW | **Add Server: PBS-режим оставляет сирот** — лейбл «Cluster:» скрыт, а поле `cluster_input` осталось видимым без подписи (`_pve_only_labels` не включает само поле, `:221-223`); после скрытия Token-секции висит парный разделитель (кадр `add_server_pbs.png` — пустая секция между Connection и Node settings); кнопка «Show» видна до получения токена — `_on_type_changed` включает все PVE-виджеты разом (`:258`), перекрывая конструкторский `setVisible(False)` |
| U24 | 🟡 U-LOW | **Микро-пачка форм**: Port-валидатор `\d{1,5}` пропускает 99999 (нет диапазона 0-65535, `add_server_dialog.py:110`); ни одна форма не ставит `setLabelBuddy`/мнемоники — клавиатурный ввод по Tab работает, по Alt+букве нет; Enter не сабмитит Create (нет `setDefault(True)`) — сабмит только мышью |

### Положительное (эталон)

- **Add Server — образец формы**: кнопки вне скролла; токен-флоу с явными
  состояниями (Connecting → Token created · Cluster detected (N nodes));
  inline-проверка дубликатов имён (Stage 5.1); port auto-switch PVE/PBS с
  сохранением кастомного порта; пароль очищается после токена; Show/Hide
  значения; PBS-добавление проверяется реальным запросом перед accept;
  `closeEvent` отписывает воркеры; trust_ssl дефолт False — **согласован с
  сессией** (в отличие от трёх мест U2).
- Create VM: секции с разделителями, выравнивание лейблов, информативные
  плейсхолдеры («auto», «0 — no VLAN», «auto» для Queues через
  specialValueText), персистентность всех значений между запусками
  (кроме бага U22), акцентная Create.
- vzdump: честный inline-хинт «No backup storage available» красным —
  образец валидации с сообщением.
- Остальные диалоги (migrate, clone, group, token, storage_config, role):
  компактны, кнопки вне скроллов, disabled-кнопка вместо молчаливых
  ошибок (migrate: target обязателен), скроллы — только вокруг длинного
  контента (список привилегий role), не вокруг форм.

## UX-6. Тексты, i18n, RTL (2026-10-16)

### Метод

Извлечение всех `tr()`-ключей из кода (`virtdeck/ui/**`, 1064 ключа) и сверка
с пятью словарями (ru/ar/zh/fr/es, по 1354 записи): missing/stale/покрытие.
Терминологические группы по плану (storage/datastore, host/node/server,
task/job, delete/remove, vm/guest, refresh) с ru-значениями — дамп в
`/tmp/opencode/ux_audit/ux6/terms_out.txt`. Плюрал-кандидаты (ключи с
`{count}`/`{}` + счётливое существительное). Рендеры ключевых поверхностей в
трёх локалях ru/ar/zh — главное окно (populated) + Create VM, 6 кадров в
`ux6/`; для арабского — `Qt.RightToLeft`. fr/es — латиница, оценены
программно по длинам строк (без рендеров). Каждая находка верифицирована
кодом; смешение языков воспроизведено управляемым экспериментом
(`ux6/probe.py`: свежий процесс с lang=ar даёт корректный арабский —
следовательно, русский текст в zh/ar-кадрах приходит из запекания при
импорте, а не из словарей).

**Ограничение среды**: в offscreen-песочнице нет CJK/арабских глифов —
тексты этих локалей на кадрах пусты (доказательство: пусты даже нативные
имена языков в комбо статус-бара, которые не переводятся вообще).
Структурное зеркалирование RTL от глифов не зависит и оценивалось отдельно.

### Терминологическая таблица (ru)

| Понятие | Варианты в ru | Примеры ключей |
|---|---|---|
| PVE-нода (член кластера) | узел / нода | `Nodes`→«Узлы», `Compare nodes`→«Сравнить узлы», но `Cluster detected: {name} ({count} nodes)`→«{count} нод» |
| Подключение (host-запись) | хост / сервер | `Delete host`→«Удалить хост», `Host`→«Хост» (колонка задач), `Add Server`→«Добавить сервер» |
| Гость (VM) | ВМ / VM | `VM create failed`→«Ошибка создания ВМ», но `ID VM:`, `VM Task`→«Задача VM» |
| Хранилище PVE и датастор PBS | хранилище (обе) | `Create storage…`→«Создать хранилище…», `Datastore`→«Хранилище» |
| Фоновое задание | задание / задача / бэкап-джоб | `Backup Jobs`→«Задания резервного копирования», `Job started`→«Задача запущена», `Not covered by any backup job`→«…бэкап-джобом» |

### Находки UX-6

| # | Серьёзность | Находка |
|---|---|---|
| U25 | 🟡 U-MEDIUM | **Терминологический дрейф «одна сущность — четыре слова»**: дерево/задачи — «хост» (`Delete host`, колонка `Host`), Create VM — «Узел:», кластерные операции — «узел» (`Nodes`→«Узлы», «На этом узле…»), fleet-тост — «нода» («{count} нод»), Add Server — «сервер». Оператор сам удерживает тождество хост=узел=сервер=нода. Плюс падеж: `Hosts`→«Хостов» (родительный вместо именительного) — заголовок карточки детальной панели хоста (`_host_tabs.py:355,381`) |
| U26 | 🔴 U-HIGH | **11 ключей без перевода во всех 5 локалях** (missing идентичен в ru/ar/zh/fr/es — словари синхронны): заголовок окна склеивается из переведённой и непереведённой частей — «Добавить сервер to cluster» (`add_server_dialog.py:46-48`); placeholder «auto (detected from server)» (`:207`); хвост сводки «… and {count} more» (`mainwindow.py:615`); пустое состояние дерева «No servers added.\nPress + to add» (`tree_panel.py:321`); «Update timed out — showing last known data», «Configuration exported to:\n{path}» (`:585`), `Delay:`, `Edit:`, `Shutdown:`, `Theme failed to load` (`:2654`). Англицизмы видны в базовых сценариях. Фикс: дополнить словари + CI-гейт «все tr()-ключи кода ⊆ каждый словарь» |
| U27 | 🟡 U-MEDIUM | **«ВМ» и «VM» вперемешку**: «Ошибка создания ВМ» рядом с «Запустить VM», «ID VM:», «Имя VM:», «Задача VM», «VM {vid}: параметр изменён». Два написания одного термина в соседних строках одного интерфейса |
| U28 | 🟡 U-MEDIUM | **PBS «Datastore» слит с PVE storage**: оба → «Хранилище» (`Datastore`→«Хранилище», `Verify datastore {store}`→«Проверка хранилища {store}» против `Create storage…`→«Создать хранилище…»). Разные сущности домена неразличимы в ru — в тостах и сводках не понять, о чём речь. Фикс: «Датастор» или «Хранилище (PBS)» |
| U29 | 🟡 U-LOW | **задание / задача / бэкап-джоб**: `Backup Jobs`→«Задания…», `Job started`→«Задача запущена», `Not covered by any backup job`→«Не покрыт ни одним бэкап-джобом» — три слова для смежных понятий в одном флоу бэкапа |
| U30 | 🟡 U-MEDIUM | **Плюрализации нет системно** (`tr` — плоский dict, `i18n/__init__.py:86-91`, ngettext отсутствует): «{count} нод»→«1 нод», «скан снимков неполный: {} гостей не проверено»→«1 гостей», «{} проблем на {} кластерах»→«1 проблем», «Доступно обновлений пакетов: {count}»→«: 1». Ломаются тосты fleet-сводки и кластерных операций. Фикс: плюральная функция (ru — 3 формы) или падежно-нейтральные формулировки («Узлов в кластере: N») |
| U31 | 🟡 U-MEDIUM | **tr() запекается на уровне модулей**: `VGA_TYPES`/`SCSI_CONTROLLERS`/`DISK_CACHE`/`CPU_TYPES` — module-level списки с `tr()` (`create_vm_dialog.py:43-80`), вычисляются при первом импорте. Прод спасает только порядок `main.py:41` (set_language до импорта MainWindow) — любой перенос импорта или ленивый плагин даст смешанный язык; смена языка без рестарта воспроизведена: в zh/ar-диалогах Create VM русские «Без кэша», «host (рекомендуется)» (кадры `zh/ar_create_vm.png`). Там же дубль: `DISK_CACHE` в `vm_device_editors.py:24` с другим ключом — одна опция кэша называется «Без кэша» в Create VM и «Нет» (`None`) в редакторе устройства. Фикс: значения-фабрики или явный retranslate |
| U32 | 🟡 U-LOW | **Формулировки**: `No media`→«Не использовать носители» — глагольная форма вместо состояния («Без носителя»), x3 к длине исходника (риск усечения в узких комбо); `host (recommended)`→«host (рекомендуется)» — гибрид латиницы и кириллицы в одной строке |
| U33 | 🟡 U-LOW | **Гигиена словарей**: 305/1354 stale-ключей (22%) во всех 5 словарях; дубликаты с разной пунктуацией (`empty = all nodes` / `empty — all nodes`); перевод пустого состояния существует под неполным ключом (`No servers added.`) тогда как используемый вариант с `\n` не переведён (см. U26) — ручная синхронизация без инструмента |

### Положительное (эталон)

- **RTL структурно корректен** (кадр `ar_main.png`): тулбар, дерево, тулбар-
  панель и доки зеркалятся глобальным LayoutDirection; bidi-токены (IP-адреса)
  отображаются правильно. Направленные иконки не оценивались (иконки вне объёма).
- Смена языка — с подтверждением и честным рестартом (`mainwindow.py:2674-2680`,
  «Restart now?»), порядок `set_language` до импортов UI в `main.py:39-46` —
  единственный на сегодня надёжный retranslate-механизм (латентный риск — U31).
- Капс заголовков таблиц сделан на уровне представления — `text-transform:
  uppercase` в QSS (`theme.py:366`), код локале-независим; в ru заголовки
  длиннее (учтено в контексте A9).
- Словари 5 локалей структурно синхронны (одинаковое покрытие и одинаковые
  дыры — U26 как процесс, не как рассинхрон).
- fr/es: критичных раздуваний строк нет (топ-ратио — короткие ключи «on»,
  «Set», «Sync» — до x4.5, в фиксированных контейнерах не критично).

### Артефакты

`/tmp/opencode/ux_audit/ux6/` — кадры `ru_main.png`, `ru_create_vm.png`,
`ar_main.png`, `ar_create_vm.png`, `zh_main.png`, `zh_create_vm.png`,
`_hdr_zoom.png`; дампы `terms_out.txt`, `keys.txt`; скрипты: `ux6_render.py`,
`ux6/terms.py`, `ux6/missing.py`, `ux6/probe.py` (доказательство запекания).

## UX-7. Доступность и эргономика (2026-10-16)

### Метод

Keyboard-only проход runtime-скриптом (`ux7_runtime.py`): таб-цепочки
главного окна (26 шагов) и Create VM (30 шагов) через `focusNextChild`
с дампом виджетов; пиксельная проверка видимости фокуса (grab кнопки
до/после `setFocus`, подсчёт изменившихся пикселей); дамп тулбара
(текст/иконка/tooltip/accessibleName/размеры); замеры целей нажатия
(строки дерева, кнопки, комбо, спины, чекбоксы). Инвентарь кеглей по коду
(`font-size`/`setPointSize`/`setPixelSize`). HiDPI: рендер при
`QT_SCALE_FACTOR=2` (`ux7_dpr2.py`) + проба devicePixelRatio пиксмапа
иконки. Шорткаты и мнемоники — код-скан + инвентарь. Все находки
верифицированы кодом; QSS-правила сверены (`theme.py`).

### Находки UX-7

| # | Серьёзность | Находка |
|---|---|---|
| U34 | 🔴 U-HIGH | **Фокус клавиатуры невидим на всех кнопках приложения** — пиксельное доказательство: grab кнопки Cancel до/после `setFocus()` совпадает бит-в-бит (changed_pixels=0). Причина: QPushButton стилизован QSS (`theme.py:424-450`) с `:hover/:pressed/:disabled`, но **без `:focus`** — Qt подавляет нативное фокус-кольцо у QSS-стилизованных кнопок. Затронуты все кнопки диалогов и панелей; WCAG 2.4.7 (Focus Visible) нарушен. Для полей фокус показан (`QLineEdit/QComboBox/QSpinBox:focus`, `:602/614/707`) — асимметрия. Фикс: правило `QPushButton:focus { border: … ACCENT }` (+ `QCheckBox:focus`) |
| U35 | 🔴 U-HIGH | **Тулбар недостижим с клавиатуры**: Tab-цепочка главного окна — цикл из 9 виджетов (комбо режима → дерево → «Collapse all» → задачи → фильтр → 3 комбо статус-бара), ни одна из 9 QToolButton тулбара (и сам QToolBar) в цепочку не входит. У Export/Import configuration и About нет ни шортката, ни меню (менюбара в приложении нет) — **действия вообще без клавиатурного пути**, WCAG 2.1.1 (Keyboard). У Add server/Refresh/Search/Fleet/Quit шорткаты есть, у Create VM (главное действие) — нет (при Ctrl+N у второстепенного Add Server). Начальный фокус после старта — на комбо режима, не на дереве. Фикс: focusPolicy тулбара/кнопок (StrongFocus + стрелки внутри панели) или шорткаты на оставшиеся действия |
| U36 | 🟡 U-MEDIUM | **HiDPI: иконки рендерятся в 1x и растягиваются** — `_make_icon` строит `QPixmap(size, size)` без `setDevicePixelRatio` (`icons.py:70-74`); проба при DPR 2: пиксмап иконки 24×24 **dpr=1.0** на экране dpr=2.0. На кадре `dpr2_main.png` текст и QSS-вектор идеально резкие (2x), SVG-иконки — мягкие (кадры `dpr2_toolbar_crop.png`, `dpr2_tree_crop.png`). При DPR 2 весь иконный слой в полразрешения. Фикс: рендерить pixmap в `size × devicePixelRatio` с обратным setDevicePixelRatio |
| U37 | 🟡 U-LOW | **Ровно один AccessibleName на всё приложение** (`refresh_spinner`, `mainwindow.py:262`). Комбобоксы статус-бара (режим/язык/тема) и тулбар-кнопки — `accessibleName=''`: у кнопок Qt падает на text/tooltip (имя озвучивается, но это фоллбек), у комбо без текста-контекста скринридер озвучивает только текущее значение («Русский» — без «язык») |
| U38 | 🟡 U-LOW | **Мелкие кегли**: инвентарь — 26×11px, 21×12px, 19×13px, 3×**10px** (`card_list.py:90,130,144` — статус-метки карточек), минимум 10px при базовом 13px; 11px подсказки идут в паре с TEXT_SEC — двойной удар по читаемости (контраст — A7, размер здесь). Шрифтовой шкалы-токена нет (A6). Фикс: минимум 11→12px для текста, токены шкалы на v2 |
| U39 | 🟡 U-LOW | **Цели нажатия**: чекбоксы форм 18px (box) при кнопках 34px — узкая зона попадания; «Collapse all» 30×30 — на грани рекомендуемых 24px+; остальное в норме (строки дерева 28px, кнопки 34px, комбо 28px, спины 35px, тулбар 43×35) |

### Keyboard-only сводка

Шорткаты (9, без конфликтов): Ctrl+R/F5 refresh, Ctrl+Q quit, Ctrl+N
add server, Del delete (нет-op для большинства типов — U13), Ctrl+F search,
Ctrl+Shift+F fleet, Ctrl+K палитра (44 действия — клавиатурный доступ есть).
Мнемоник (`&`) нет вообще — конфликтов нет by absence (U24: нет и
setLabelBuddy). Дерево клавиатурно полноценное: стрелки →
`currentItemChanged` → detail обновляется; Esc=reject у диалогов. Таб-порядок
Create VM логичен (30 шагов: секции сверху вниз → чекбоксы → Create → Cancel).

### Положительное (эталон)

- Дерево: полная клавиатурная навигация с живым detail-обновлением —
  keyboard-only сценарий «выбрать и посмотреть» работает без мыши.
- Тултипы тулбара с шорткат-хинтами («Refresh data (Ctrl+R)») — образец
  discoverability шорткатов.
- Палитра Ctrl+K покрывает клавиатурой все 44 действия реестра.
- Пиксельная асимметрия фокуса локализована точно: поля показывают фокус,
  кнопки нет — фикс U34 — одно QSS-правило.
- Размерный каркас здоров: строки 28px, кнопки 34-35px, комбо 28px.

### Артефакты

`/tmp/opencode/ux_audit/ux7/` — дампы `tab_chain_main.txt`,
`tab_chain_dlg.txt`, `toolbar_a11y.txt`, `targets.txt`; пиксель-пруф
`btn_unfocused.png` / `btn_focused.png`; HiDPI `dpr2_main.png`,
`dpr2_toolbar_crop.png`, `dpr2_tree_crop.png`; скрипты `ux7_runtime.py`,
`ux7_dpr2.py`.

## UX-8. Консолидация (2026-10-16)

### Итог серии

60 находок: **A1–A11** (эстетика), **U1–U39** (usability), **L1–L10**
(live-факты). Severity: **4 🔴 U-HIGH**, **17 🟡 MEDIUM**, **28 🟡 LOW**,
1 системазев (A6), 10 L-фактов с рут-маршрутизацией. Все 10 кандидатов UX-0
закрыты с маршрутами. Объём верификации: 26 поверхностей, 47 кадров UX-2 +
6 локалей + 2 DPR-режима, runtime-матрица действий (44 спеки × 8 типов
элементов × 2 точки входа), таб-цепочки, пиксель-пруф фокуса, 5 словарей ×
1354 записи.

### Свод по severity

**🔴 U-HIGH (4)**

| ID | Суть | Фикс |
|---|---|---|
| U13 | `object.delete` — включённый нооп для 4 из 9 типов объектов | маленький: `spec.enabled` по типу |
| U26 | 11 непереведённых ключей во всех 5 локалях; «Добавить сервер to cluster» | данные + CI-гейт покрытия |
| U34 | Фокус клавиатуры невидим на всех кнопках (pixel-proof: 0 пикселей) | одно QSS-правило `:focus` |
| U35 | Тулбар вне Tab-цепочки; Export/Import/About без клавиатурного пути | focusPolicy + шорткаты |

**🟡 MEDIUM (17)**

| ID | Суть | ID | Суть |
|---|---|---|---|
| A1 | inline-QSS меню противоречит теме | U14 | шаблон вне scopes палитры |
| A8 | пороги WARN/ERR разные на поверхностях | U15 | Fleet Health вне палитры |
| U1 | члены кластера бездетные, VM без ноды | U19 | Create VM: кнопки в скролле (717/408px) |
| U2 | SSL-метка против дефолтов сессии (trust_ssl ×3) | U20 | Add Server: токен не инвалидируется |
| U6 | «No issues found» при 0 целей | U25 | хост/узел/сервер/нода вперемешку |
| U7 | PBS-панель — каркас без подсказки | U27 | «ВМ» и «VM» вперемешку |
| U8 | нет дедлайна воркера/сигнала завершения — корень L1/L2/L5/L9 | U28 | PBS Datastore слит с PVE storage |
| U30 | плюрализации нет системно («1 нод») | U31 | module-level tr() запекание |
| U36 | иконки 1x на DPR2 (без setDevicePixelRatio) | | |

**🟡 LOW (28)** — тематические пачки: токен-литералы (A2–A5), смена темы не
доходит до pbs_panel (A7), таблицы — усечения и единицы (A9, A10), Quit
без иконки (A11); empty-states и подсказки (U3, U11, U12, U6-семейство
L4/L10), палитра/поиск пустые (U3, U11), действия (U16 скрытый F5, U17/U18
деструктивные пункты, U14-смежное), формы (U21 тихие фоллбеки, U22 index-0,
U23 PBS-сироты, U24 микро-пачка, U4 password-плейсхолдер, U39 чекбоксы
18px), дерево (U9 прыжки структуры, U10 tooltip без error, U5 нулевая
сводка), i18n (U29 задание/задача, U32 формулировки, U33 гигиена словарей),
a11y (U37 AccessibleName, U38 кегли 10–11px).

**системазев**: A6 — токены шрифтовой шкалы и отступов (контракт v2).

**L-факты (10)**: L1/L2/L5/L9 → корень U8; L3 — знаменатель сводки;
L4/L10 — empty-state формулировки → U6/U12; L6 — dropdown на disabled;
L7 — VMID вне заголовка VM; L8 — факт персистенции режима дерева.

### Итоги матриц

- **UX-0 (кандидаты)**: 10/10 закрыты — №1→U13, №2→U19, №3→U15,
  №4/№9→U16, №5→A11, №6→U6, №7→U7, №8→A1, №10→U13/U14-контекст.
- **UX-4 (действия × точки входа)**: 44 спеки; меню показывает disabled
  серым, палитра скрывает — расхождения U13/U14/U15; физические биндинги —
  8 ручных QShortcut, скрытый F5 (U16).
- **UX-6 (i18n)**: 1064 ключей кода, 5 словарей × 1354, missing=11
  идентичен во всех локалях, stale 22%; RTL структурно корректен.
- **UX-7 (эргономика)**: таб-цепочки 26/30 шагов; фокус-пруф 0 пикселей;
  DPR-проба 1.0@2.0.

### План фиксов (после утверждения владельцем)

| Приоритет | Работы | Закрывает | Оценка |
|---|---|---|---|
| P0 | QSS `QPushButton:focus`/`QCheckBox:focus` | U34 | S |
| P0 | `enabled` по типу объекта для delete | U13 | S |
| P0 | focusPolicy тулбара + шорткаты Export/Import/About/Create VM | U35 | S–M |
| P0 | дополнить 11 ключей × 5 словарей + CI-гейт «ключи кода ⊆ словари» | U26 | M |
| P1 | дедлайн воркера + сигнал завершения обновления | U8, L1/L2/L5/L9 | M |
| P1 | footer Create VM вне скролла | U19 | S |
| P1 | инвалидация токена Add Server | U20 | S |
| P1 | trust_ssl: единый дефолт False (3 места + сессия) | U2 | S |
| P1 | devicePixelRatio в `_make_icon` | U36 | S |
| P1 | `is not None` в `_restore_settings`; пороги WARN/ERR | U22, A8 | S |
| P2 | плюральная функция; значения-фабрики вместо module-level tr(); дедуп DISK_CACHE | U30, U31 | M |
| P2 | терминологический словарь (решение владельца: хост/узел, ВМ/VM, датастор) | U25, U27, U28, U29 | M |
| P2 | гигиена словарей (tool-скрипт stale/дубли) | U33, U32 | S |
| P3 | LOW-пачки по подсистемам: empty-states (U6/U7/U12/L4/L10), формы (U21/U23/U24/U4/U39), действия (U14–U18), таблицы (A9/A10), токен-литералы (A1–A5, A7, A11), дерево (U1/U9/U10), a11y-имена и кегли (U37/U38) | | M |
| v2 | токены шрифтовой шкалы и отступов | A6 | — |

S ≤ часа, M — до дня (одиночные правки без рефакторинга).

### За рамками аудита

- Иконная тема: направленные RTL-иконки, дизайн самих иконок, наложение
  статус-точек на иконки (факт в кадрах UX-6/UX-7).
- Healthy-состояния PBS не отрендерены полностью (нужны worker-данные);
  live-проход ограничен инфраструктурой (1 хост, 7 VM, firewall).
- Сайт virtdeck-site — отдельный просмотр; brand.py и API-контракты воркеров
  не затронуты.
- L8 (персистенция режима дерева) — зафиксирован как дизайн-факт.





