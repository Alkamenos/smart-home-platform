"""Условия платформы.

Живая система условий — `builtin.py` (реестр) и модули по домам: `context`,
`lighting`, `climate`, `ventilation`, `covers`. Здесь остаётся только то, что
действительно используется: `is_within_schedule` — расписание из параметров
поведения (его берёт фабрика автоматов).

Старый каркас условий (`BaseGuard`, `CompositeGuard`, `NumericGuard`,
`StateGuard`, `TimeGuard`, `GuardFactory`) удалён 2026-10-16: его не вызывал ни
один рабочий модуль, но он создавал ложное ощущение, что конфиг вида ``guards:``
или ``policy:`` где-то читается (аудит 2026-10-16, К-16).
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from .schedule_guard import is_within_schedule


__all__ = ["is_within_schedule"]
