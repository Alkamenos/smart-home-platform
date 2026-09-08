"""
Dashboard - интеграция с Home Assistant Dashboard

Создает entities, sensors и automations в HA для мониторинга и управления
"""
from .dashboard import DashboardIntegration

__all__ = ['DashboardIntegration']
