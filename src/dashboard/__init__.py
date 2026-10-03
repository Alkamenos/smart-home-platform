"""Пакет дашбордов Home Assistant.

Модуль ``DashboardIntegration`` удалён вместе с фичей наблюдаемости (решение
D-3): он был недостижим из production-кода, а его собственные методы были
заглушками — создание вида лишь логировало, а создание сенсора вызывало
несуществующий сервис Home Assistant. Зеркалирование состояний автоматов в
Home Assistant выполняет ``services/fsm_state_bridge.py`` (specs/007).

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from dashboard.lovelace_generator import LovelaceGenerator


__all__ = ["LovelaceGenerator"]
