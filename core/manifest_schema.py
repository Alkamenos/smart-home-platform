"""
Manifest Schema - Схема валидации манифеста платформы умного дома

Определяет структуру и правила валидации для manifest.yaml
"""

from typing import Any


MANIFEST_SCHEMA = {
    "version": {"type": "integer", "required": True},
    "instance": {
        "type": "dict",
        "required": True,
        "schema": {
            "id": {"type": "string", "required": True},
            "name": {"type": "string", "required": True},
            "owner": {"type": "string"},
            "created_at": {"type": "string"}
        }
    },
    "devices": {
        "type": "dict",
        "required": True,
        "schema": {
            "lighting": {"type": "list", "required": True, "schema": {
                "type": "dict",
                "schema": {
                    "id": {"type": "string", "required": True},
                    "name": {"type": "string", "required": True},
                    "room": {"type": "string", "required": True},
                    "motion_sensor": {"type": "string"},
                    "schedule": {"type": "string"},
                    "motion_timeout_sec": {"type": "integer"}
                }
            }},
            "climate": {"type": "list", "schema": {
                "type": "dict",
                "schema": {
                    "id": {"type": "string", "required": True},
                    "name": {"type": "string", "required": True},
                    "room": {"type": "string", "required": True},
                    "sensor": {"type": "string", "required": True},
                    "target": {"type": "float"},
                    "hysteresis": {"type": "float"},
                    "modes": {"type": "list"}
                }
            }},
            "ventilation": {"type": "list", "schema": {
                "type": "dict",
                "schema": {
                    "id": {"type": "string", "required": True},
                    "name": {"type": "string", "required": True},
                    "room": {"type": "string", "required": True},
                    "humidity_sensor": {"type": "string"},
                    "humidity_threshold": {"type": "float"},
                    "timeout_sec": {"type": "integer"}
                }
            }}
        }
    },
    "automation_rules": {
        "type": "dict",
        "schema": {
            "lighting": {"type": "dict"},
            "climate": {"type": "dict"},
            "ventilation": {"type": "dict"}
        }
    },
    "zones": {
        "type": "list",
        "required": True,
        "schema": {
            "type": "dict",
            "schema": {
                "id": {"type": "string", "required": True},
                "name": {"type": "string", "required": True},
                "floor": {"type": "integer"}
            }
        }
    },
    "dashboard": {
        "type": "dict",
        "schema": {
            "title": {"type": "string"},
            "show_motion_sensors": {"type": "boolean"},
            "show_climate": {"type": "boolean"},
            "show_history": {"type": "boolean"},
            "history_days": {"type": "integer"}
        }
    }
}


def get_schema() -> dict[str, Any]:
    """Возвращает схему манифеста"""
    return MANIFEST_SCHEMA
