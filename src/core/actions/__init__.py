"""Действия платформы по доменам (B80).

Все 31 действие раньше жили в одном модуле ``core/action_handlers.py``.
Теперь домены разошлись по файлам, а ``core.action_handlers`` остаётся
публичным фасадом: реестр, регистрация и прежние импорты.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
