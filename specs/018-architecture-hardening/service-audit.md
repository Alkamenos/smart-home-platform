# Аудит CLI и ConfigWatcher (T078–T079)

**Дата:** 2026-11-07 | **Спека:** `018-architecture-hardening`, US6

## CLI

- `src/cli/health_check.py` — единственный потребитель Docker healthcheck
  (`python -m src.cli.health_check`); оставлен, покрыт `tests/cli/test_health_check.py`.
- `src/smart_home/cli/` — пользовательский `shp`: `bulk_import`, `export_fsm`,
  `generate_dashboard`, `shell`. Дублирования с `health_check` нет: первый — infra,
  второй — операторский интерфейс.
- `shell` переведён с удалённого `bootstrap.py` на `Container(...).build()`.

## ConfigWatcher

- Запускается только при `HOT_RELOAD=1`; по умолчанию выключен.
- Следит за YAML манифеста/шаблонов и Python-модулями, перерегистрирует
  guard/action после перезагрузки.
- Ошибки перезагрузки логируются и не останавливают watcher.
- `importlib.util` импортируется явно: раньше он был доступен случайно через
  соседний импорт, и вынос `yaml` из `factory.py` ломал загрузку модулей.
- Отдельный API и внешние зависимости не добавлялись.

**Вывод:** оба интерфейса оставлены; дублирования и мёртвых точек входа нет.
