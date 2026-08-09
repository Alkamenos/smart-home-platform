# Smart Home Platform

Data-driven платформа поверх Home Assistant: логика отделена от данных.
Весь инстанс описывается манифестом (YAML), движок читает его в runtime.

## Структура
- `shplatform/schema/` — Pydantic-схема манифеста (единый источник правды)
- `shplatform/validator/` — проверки связности (cross-references)
- `shplatform/loader/registry.py` — runtime-реестр (без зависимостей)
- `ha/pyscript/manifest_loader.py` — загрузчик манифеста в HA
- `ha/pyscript/climate_orchestrator.py` — климат (shadow/real)
- `manifests/` — манифесты инстансов
- `cli/` — `shplatform validate` / `schema`
- `tests/` — тесты схемы и реестра

## Workflow
1. `shplatform validate manifests/<name>.yaml`
2. `./deploy.sh --ha-config /config`
3. Полный перезапуск HA

## Текущий статус
- Климат: 4 зоны (гостиная/санузел/спальня/кабинет), shadow/real, дашборд.
- Дальше: Override Manager → real mode → свет/полив → Яндекс диалоги.