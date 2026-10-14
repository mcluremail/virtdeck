# Процедура релиза virtdeck

Принцип: релиз — это не только бамп версий. Документация (
[CHANGELOG.md](../CHANGELOG.md), [README.md](../README.md),
[FEATURES_BACKLOG.md](../FEATURES_BACKLOG.md), [ROADMAP.md](../ROADMAP.md))
описывает продукт для внешнего читателя — отстающий README хуже отсутствующего.
Пункты ниже закрывают типовые промахи; исторически забывали именно README —
поэтому он в чеклисте отдельным шагом.

Правила окружения — в [DEV_PROCESS.md](DEV_PROCESS.md): без `uv run`, только
`.venv/bin/python` / `.venv/bin/pytest` / `.venv/bin/ruff`.

## Версионирование

| Изменение | Паттерн | Пример |
|---|---|---|
| Багфикс | `2.9.X` | 2.9.1, 2.9.2, ... |
| Новая фича | `2.X.0` | 2.10.0, 2.11.0, ... |
| Глобальные изменения | `X.0.0` | 3.0.0 |

Версия живёт в трёх местах — меняем все:

- `pyproject.toml` (`[project] version`);
- `virtdeck/__init__.py` (`__version__`);
- `uv.lock` — перегенерация `uv lock` (меняется строка `version` пакета
  `virtdeck`). **Закоммитить обновление**, не откатывать (в отличие от
  рутинных прогонов, где дрейф uv.lock откатывается).

## Процедура (порядок шагов)

1. **CHANGELOG.md** — секция `## vX.Y.Z — <заголовок>` поверх существующих.
   Разделы: New features / Bug fixes / Performance / Internal. Формулировки —
   по-английски, по коммитам (`git log --format='%h %s%n%b---' <prev>..HEAD`)
   и закрытым фичам из FEATURES_BACKLOG.
2. **FEATURES_BACKLOG.md** — для каждой фичи релиза: заголовок пометить
   `✅ (vX.Y.Z)`, вписать краткое описание реализации (эндпоинты, файлы,
   ограничения). Незавершённые ветки — не трогать.
3. **ROADMAP.md** — секция релиза `✅ (выпущено в vX.Y.Z)`; исключённое из
   объёма — зачёркнуто с указанием кандидата на следующую версию.
4. **README.md** — часто забываемый шаг, проверять обязательно:
   - `Latest release:` ссылка на новый тег;
   - раздел Features: новые возможности пользователя (фича «для дерева»
     попадает в Interface, фича с API-действиями — в Monitoring/Management/...);
   - переименованные/переформулированные фичи — синхронно с CHANGELOG.
5. **Сайт virtdeck.mclure.ru** — второй обязательный шаг (источник правды для
   установочных команд — README; сайт синхронизируется с ним):
   - source-checkout сайта: `/home/taurus/Work/pvecenter/virtdeck-site/public/`
     (`index.html` + `i18n.js`; ключи i18n обязаны быть в паритете во всех 6
     языках — проверяет `check-site.js`);
   - `./update-version.sh <old> <new> [date]` — переписывает версии, локализованные
     даты (включая футер «Site updated»), HEAD-проверяет все ссылки на assets
     релиза; после — сверить apt/dnf-блоки сайта с README вручную (команды
     должны быть дословно те же);
   - автоматическая сверка с README: `python3 scripts/check_release.py
     --site-dir <checkout сайта>` — версия wheel-ссылок, дословность pip-команды,
     наличие предупреждения PEP 668, формат отпечатка. Сайт живёт в отдельном
     checkout вне этого репозитория — CI его проверить не может, шаг ручной
     (ограничение зафиксировано, а не забыто);
   - проверки: `node check-site.js` (i18n-паритет, баланс тегов, устаревшие
     версии) и `node check-contrast.js`;
   - деплой: `rsync -a public/ repo.mclure.ru:/srv/virtdeck/public/`
     (nginx отдаёт каталог как есть, рестартовать ничего не нужно);
   - live-проверка: `curl -s https://virtdeck.mclure.ru/ | grep -c "vX.Y.Z"`.
6. **Бамп версий** (три места, см. выше) + `uv lock`.
7. **Гейты**: `.venv/bin/ruff check virtdeck tests &&
   .venv/bin/pytest -q` и `python3 scripts/check_release.py` — зелёные.
   Smoke: `grep -rn "3\.0\.[0-9]" README.md`
   — не осталось старых упоминаний версии там, где ожидается новая.
8. **Коммит** `release: vX.Y.Z — <заголовок>` (по явной команде, как всегда).
9. **Тег** `vX.Y.Z` на релизный коммит.

## Точка аудита перед релизом

Релизная дельта не должна содержать неаудированного кода: перед релизом
пройти инкрементальный аудит ([AUDIT_PROCESS.md](AUDIT_PROCESS.md)) с тегом
`audit/<дата>`, исправления — отдельным коммитом до релизного. Пример
последовательности: `... → аудит-коммит (тег audit/2026-09-10) → release-коммит (тег v2.13.0)`.

## После создания GitHub-релиза (обязательные шаги)

`release.yml` создаёт релиз с шаблонным телом и не подписывает артефакты.
Оба пробела закрываются сразу после зелёного прогона:

1. **Тело релиза** — boilerplate не показывает пользователю, что пофикшено.
   Заменить заглушку «What changed» секцией этой версии из CHANGELOG.md
   (для аудитных багфикс-релизов достаточно 2–5 пунктов «Fixed: …»; путь
   `gh release edit vX.Y.Z --notes-file <file>`). Инсталляционная часть тела
   поддерживается в актуальном составе платформ (Debian/Ubuntu/Fedora-версии,
   отпечаток ключа).
2. **Подписи .asc для артефактов** — checksums.txt защищает только от битой
   загрузки; подпись тем же ключом, что и репозиторий, защищает от подмены.
   Приватный ключ подписи НЕ покидает сервер repo.mclure.ru, поэтому подпись
   делается там:
   ```
   gh release download vX.Y.Z -D /tmp/rel -R mcluremail/virtdeck   # локально
   rsync -a /tmp/rel/ repo.mclure.ru:/tmp/rel-vX.Y.Z/
   ssh repo.mclure.ru 'sudo -n sh -c "cd /tmp/rel-vX.Y.Z && for f in *; do gpg --batch --yes --armor --detach-sign --local-user 117DEABD3EA48810B219BA6B401F700FB97DE8B8 \$f; done"'
   rsync -a repo.mclure.ru:/tmp/rel-vX.Y.Z/*.asc /tmp/rel/
   gh release upload vX.Y.Z /tmp/rel/*.asc --clobber -R mcluremail/virtdeck
   ssh repo.mclure.ru 'sudo -n rm -rf /tmp/rel-vX.Y.Z'             # убрать за собой
   ```
   Пользователь проверяет: `gpg --verify <файл>.asc <файл>` против ключа,
   отпечаток которого сверен с README/сайтом/repo-корнем.
3. **Тело v3.0.2 было исправлено задним числом** (2026-10-12) — «Fixed: …»
   добавлены; при просмотре старых релизов учитывать, что до этой даты тело
   было boilerplate.

## Обзор платформ (раз в полгода, перед очередным релизом)

Матрица пакетов — не «настроил и забыл»: Fedora живёт ~13 месяцев, Ubuntu LTS
— 2 года, EOL-каталог в append-only репо замораживается, а не удаляется
(у пользователей dnf не ломается, но новые сборки туда не попадают).

- сверить поддерживаемые релизы Fedora (`endoflife.date/fedora`: актуальны
  две последние), Ubuntu LTS (апрель чётных лет) и Debian (stable/oldstable);
- при добавлении релиза: matrix в `release.yml` (сборка rpm на контейнере
  того же релиза — python3.Xdist-зависимости), matrix в `repo-packages.yml`
  (proxmoxer rpm на том же релизе; python3-pyside6 deb — если у релиза новый
  Python без wheel у текущего PySide6), каталог в `publish.sh` (`SUITES` /
  `RPM_RELS`), README/сайт/релизное тело;
- при EOL релиза: убрать из README/сайта/CI/`publish.sh`, каталог оставить
  замороженным, в README отметить «frozen, no updates»;
- PySide6: колесо конвертируется из официального manylinux; версии ≥ 6.10.1
  — abi3 (cp310+) и покрывают новые Python; 6.12.x держаться подальше
  (refcount-баг, зафиксирован в `tests/ui/conftest.py`). Диапазон зафиксирован
  в `pyproject.toml` (`>=6.5,<6.12`) — снимать кап только после сверки с
  changelog PySide и повторного прогона полного набора.

## Публикация в пакетный репозиторий (repo.mclure.ru)

После пуша тега конвейер `release.yml` работает так: сборка артефактов →
`publish-repo` (rsync .deb/.rpm в `/srv/repo/incoming/` по deploy-ключу) →
smoke-гейт, который ставит virtdeck из репозитория как пользователь
(apt: noble/resolute, dnf: fedora/43 и fedora/44) → create-release. Репозиторий
предоставляет то, чего нет в архивах дистрибутивов: PySide6 (полный,
включая WebEngine, сконвертирован из официального wheel; для deb-сьютов —
bookworm/noble/trixie/resolute) и proxmoxer (rpm, собранный на том же релизе
Fedora, что и virtdeck-rpm, чтобы автогенерированные `python3.Xdist(proxmoxer)`
requirements совпадали; fedora/43 и fedora/44).

- Каталог `fedora/41` заморожен (EOL 2025-12-15): файлы на месте, новые
  сборки туда не публикуются.
- Индексы перегенерирует и подписывает сервер (`/srv/repo/publish.sh`,
  systemd path-unit за каталогом `incoming/`); GPG-ключ подписи не покидает
  сервер, публичник — `https://repo.mclure.ru/KEY.gpg`, отпечаток
  `117D EABD 3EA4 8810 B219 BA6B 401F 700F B97D E8B8` опубликован отдельно
  (README, сайт, корень repo.mclure.ru) — менять ключ без синхронного
  обновления всех трёх мест нельзя. Способ машинной сверки скачанного ключа
  — в README («Machine check»); единообразие отпечатка во всех актуальных
  доках проверяет `scripts/check_release.py`.
- Секрет `REPO_DEPLOY_KEY` — ключ, ограниченный forced-command
  (`rrsync /srv/repo/incoming`) у пользователя `repo-upload`.
- Пересборка пакетов репозитория (новый релиз дистрибутива или питона):
  `.github/workflows/repo-packages.yml` (workflow_dispatch).
- Корень repo.mclure.ru отдаёт одностраничный index (`/srv/repo/public/index.html`)
  с командами подключения и отпечатком; `dists/` намеренно не листается
  (autoindex off) — это норма.
- Серверная часть на хосте repo.mclure.ru: nginx vhost `repo`
  (`127.0.0.1:8443 ssl proxy_protocol`, docroot `/srv/repo/public`), haproxy
  гоняет всё не-plvpn SNI в nginx по умолчанию, сертификаты — certbot webroot.

## Чеклист (свернуть в один проход перед коммитом)

- [ ] CHANGELOG: новая секция поверх, все фичи/фиксы релиза, английский
- [ ] FEATURES_BACKLOG: каждая фича помечена ✅ + версией, реализация описана
- [ ] ROADMAP: секция релиза закрыта ✅, исключения зачёркнуты
- [ ] **README: Latest release + Features актуальны**
- [ ] **Сайт: версия и установочные блоки синхронизированы с README, деплой выполнен, live-проверка**
- [ ] pyproject.toml + `__init__.py` + `uv lock` — версия согласована
- [ ] `ruff check` + `pytest -q` + `scripts/check_release.py` зелёные
- [ ] аудит дельты закрыт (тег `audit/<дата>` раньше релизного коммита)
- [ ] тег `vX.Y.Z` на релизный коммит
- [ ] push коммитов и тегов — по явной команде пользователя
- [ ] **после релиза: тело = секция CHANGELOG («Fixed: …»), .asc-подписи загружены**

## История

- v2.13.0 (2026-09-10): первый релиз по этой процедуре; выявленный промах —
  README остался на v2.11.3 после v2.12.0 (процедура введена постфактум).
