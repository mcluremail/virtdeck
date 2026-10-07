"""M4.0: тестовый харнесс — фейковые PVE/PBS API и record/replay.

Fleet Health фан-аутится по всем кластерам сразу — живыми кластерами не
тестируем. Харнесс подменяет транспорт на уровне `requests`: реальный
провайдер (proxmoxer, PBS-клиент) работает против in-memory сценария или
replay-фикстуры, записанной с живого кластера. Сетевых сокетов в тестах
нет — адаптер перехватывает запросы до TLS.

Компоненты:
- `fake_pve.FakePveApi` — in-memory состояние кластера (ноды/гости/джобы/
  хранилища/rrddata/снапшоты/таски) + fluent-сценарии;
- `fake_pbs.FakePbsApi` — минимальный PBS (ticket + datastores/snapshots);
- `adapter.FakeApiAdapter` — requests-адаптер над обработчиком фейка;
- `adapter.ReplayAdapter` / `save_fixture` / `load_fixture` — record/replay
  по JSON-фикстурам (формат см. FIXTURE_FORMAT).

Швы монтирования:
- PVE: `install_fake_pve(monkeypatch, api)` — патчит `ProxmoxAPI` в
  `provider._session` (реальный объект proxmoxer, fake-адаптер на его
  внутренней `requests.Session` из `_store["session"]`; token-auth сетевого
  round-trip'а не делает — адаптер получает и «аутентификацию»);
- PBS: `PbsClient(cfg, http=session)` — опциональная сессия с адаптером.
"""

from .adapter import load_fixture, save_fixture
from .fake_pbs import FakePbsApi
from .fake_pve import FakePveApi
from .install import fake_pve_cfg, install_fake_pve, install_replay_pve, pbs_session

__all__ = [
    "FakePbsApi",
    "FakePveApi",
    "fake_pve_cfg",
    "install_fake_pve",
    "install_replay_pve",
    "load_fixture",
    "pbs_session",
    "save_fixture",
]
