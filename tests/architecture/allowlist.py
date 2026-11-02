"""Явные исключения архитектурных проверок.

Правило простое: исключение живёт здесь, а не в тесте. У каждого — причина и
срок снятия. Пустой `reason` запрещён: «исторически так сложилось» — не причина.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations


#: Бюджет размера нового модуля, строк.
SIZE_BUDGET = 800

#: Существующие крупные модули: текущий предел и цель сокращения.
#:
#: Ключ — путь от корня репозитория. Значение — максимально допустимый размер
#: на время рефакторинга. Цель Wave D — сократить каждый не менее чем на 50 %;
#: после этого запись удаляется.
LEGACY_SIZE_ALLOWLIST: dict[str, int] = {
    "src/adapters/ha_adapter.py": 2534,
    "src/core/fsm/engine.py": 1976,
    "src/core/container.py": 1679,
    "src/services/device_service.py": 1475,
    "src/services/watchdog.py": 1434,
    "src/adapters/ha_websocket.py": 923,
    "src/core/metrics.py": 961,
    "src/core/fsm/factory.py": 857,
}

#: Временные нарушения направления зависимостей.
#:
#: Ключ — пара `(из, в)`; значение — файл → причина. Нарушение должно исчезнуть
#: в указанной задаче, иначе тест напомнит.
IMPORT_ALLOWLIST: dict[tuple[str, str], dict[str, str]] = {
    ("core", "adapters"): {
        "src/core/container.py": "composition root; переносится в src/app/ (T054)",
    },
}

#: Временные параллельные доменные модели.
PARALLEL_MODEL_ALLOWLIST: dict[str, str] = {
    "src/webui/models.py": "дубли манифеста удаляются в T017",
}

#: Мёртвые production-сервисы, ожидающие решения/удаления.
DEAD_SERVICE_ALLOWLIST: dict[str, str] = {
    "src/services/backup_service.py": "удаляется в T076 (B14)",
}
