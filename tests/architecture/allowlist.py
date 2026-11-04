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
    "src/adapters/ha_adapter.py": 1249,
    "src/core/fsm/engine.py": 1548,
    "src/app/container.py": 1602,
    "src/services/device_service.py": 1475,
    "src/services/watchdog.py": 1242,
    "src/adapters/ha_websocket.py": 923,
    "src/core/metrics.py": 961,
    "src/core/fsm/factory.py": 857,
    "src/core/models/manifest.py": 900,
    "src/webui/routes/devices/devices.py": 900,
}

#: Временные нарушения направления зависимостей.
#:
#: Ключ — пара `(из, в)`; значение — файл → причина. Нарушение должно исчезнуть
#: в указанной задаче, иначе тест напомнит.
IMPORT_ALLOWLIST: dict[tuple[str, str], dict[str, str]] = {
    ("webui", "adapters"): {
        "src/webui/routes/devices/sources.py": "REST-клиент discovery; вынести в сервис (T058)",
    },
}

#: Временные параллельные доменные модели: `путь:Класс` → причина.
PARALLEL_MODEL_ALLOWLIST: dict[str, str] = {
    "src/core/models/device_config.py:DeviceConfig": "метаданные прибора, не манифест",
    "src/core/models/room.py:RoomConfig": "агрегация комнаты, не манифест",
}

#: Мёртвые production-сервисы, ожидающие решения/удаления.
DEAD_SERVICE_ALLOWLIST: dict[str, str] = {
    "src/services/backup_service.py": "удаляется в T076 (B14)",
}
