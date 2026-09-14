"""
Manifest Validator - Валидатор манифеста платформы умного дома

Проверяет манифест на ошибки ДО запуска платформы:
1. Структуру (обязательные поля)
2. Типы данных
3. Форматы (расписания, entity_id)
4. Ссылочную целостность
5. Логические ограничения (значения в диапазоне)
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationError:
    """Ошибка валидации манифеста"""
    field: str
    message: str
    severity: str = "error"  # "error" | "warning"
    
    def __str__(self) -> str:
        return f"{self.field}: {self.message}"


class ManifestValidator:
    """
    Валидатор манифеста.

    Проверяет:
    1. Структуру (обязательные поля)
    2. Типы данных
    3. Форматы (расписания, entity_id)
    4. Ссылочную целостность
    5. Логические ограничения (значения в диапазоне)
    """

    def validate(self, manifest: Any) -> list[ValidationError]:
        """
        Валидирует манифест, возвращает список ошибок.
        Пустой список = манифест валиден.
        """
        errors = []
        
        if not isinstance(manifest, dict):
            errors.append(ValidationError("manifest", "Манифест должен быть словарём"))
            return errors
        
        # 1. Структурные проверки
        errors.extend(self._validate_structure(manifest))
        
        # 2. Типы данных
        errors.extend(self._validate_types(manifest))
        
        # 3. Форматы
        errors.extend(self._validate_formats(manifest))
        
        # 4. Ссылочная целостность
        errors.extend(self._validate_references(manifest))
        
        # 5. Логические ограничения
        errors.extend(self._validate_logic(manifest))
        
        return errors

    def _validate_structure(self, manifest: dict) -> list[ValidationError]:
        """Проверка обязательных полей"""
        errors = []

        if "version" not in manifest:
            errors.append(ValidationError("version", "Отсутствует версия манифеста"))

        if "instance" not in manifest:
            errors.append(ValidationError("instance", "Отсутствует секция instance"))
        elif "id" not in manifest.get("instance", {}):
            errors.append(ValidationError("instance.id", "Отсутствует ID инстанса"))
        elif "name" not in manifest.get("instance", {}):
            errors.append(ValidationError("instance.name", "Отсутствует имя инстанса"))

        if "devices" not in manifest:
            errors.append(ValidationError("devices", "Отсутствует секция devices"))
        
        if "zones" not in manifest:
            errors.append(ValidationError("zones", "Отсутствует секция zones"))

        return errors

    def _validate_types(self, manifest: dict) -> list[ValidationError]:
        """Проверка типов данных"""
        errors = []
        
        # Проверка version
        version = manifest.get("version")
        if version is not None and not isinstance(version, int):
            errors.append(ValidationError("version", f"Версия должна быть целым числом, получено {type(version).__name__}"))
        
        # Проверка instance
        instance = manifest.get("instance")
        if instance and not isinstance(instance, dict):
            errors.append(ValidationError("instance", "instance должен быть словарём"))
        
        # Проверка devices
        devices = manifest.get("devices")
        if devices and not isinstance(devices, dict):
            errors.append(ValidationError("devices", "devices должен быть словарём"))
        
        # Проверка zones
        zones = manifest.get("zones")
        if zones is not None and not isinstance(zones, list):
            errors.append(ValidationError("zones", "zones должен быть списком"))
        
        return errors

    def _validate_formats(self, manifest: dict) -> list[ValidationError]:
        """Проверка форматов строк"""
        errors = []

        # Проверка entity_id и расписаний для lighting
        for device in manifest.get("devices", {}).get("lighting", []):
            device_id = device.get("id", "")
            if not self._is_valid_entity_id(device_id):
                errors.append(ValidationError(
                    f"devices.lighting[{device_id}].id",
                    f"Невалидный entity_id: {device_id}"
                ))

            # Проверка расписания
            if "schedule" in device:
                if not self._is_valid_schedule(device["schedule"]):
                    errors.append(ValidationError(
                        f"devices.lighting[{device_id}].schedule",
                        f"Невалидный формат расписания: {device['schedule']}"
                    ))
            
            # Проверка motion_sensor
            if "motion_sensor" in device:
                sensor_id = device["motion_sensor"]
                if not self._is_valid_entity_id(sensor_id):
                    errors.append(ValidationError(
                        f"devices.lighting[{device_id}].motion_sensor",
                        f"Невалидный entity_id сенсора: {sensor_id}"
                    ))

        # Проверка climate устройств
        for device in manifest.get("devices", {}).get("climate", []):
            device_id = device.get("id", "")
            if not self._is_valid_entity_id(device_id):
                errors.append(ValidationError(
                    f"devices.climate[{device_id}].id",
                    f"Невалидный entity_id: {device_id}"
                ))
            
            # Проверка sensor
            if "sensor" in device:
                sensor_id = device["sensor"]
                if not self._is_valid_entity_id(sensor_id):
                    errors.append(ValidationError(
                        f"devices.climate[{device_id}].sensor",
                        f"Невалидный entity_id сенсора: {sensor_id}"
                    ))

        # Проверка ventilation устройств
        for device in manifest.get("devices", {}).get("ventilation", []):
            device_id = device.get("id", "")
            if not self._is_valid_entity_id(device_id):
                errors.append(ValidationError(
                    f"devices.ventilation[{device_id}].id",
                    f"Невалидный entity_id: {device_id}"
                ))

        return errors

    def _validate_references(self, manifest: dict) -> list[ValidationError]:
        """Проверка ссылочной целостности"""
        errors = []

        # Собираем все комнаты из zones
        zone_ids = {zone.get("id") for zone in manifest.get("zones", [])}

        # Проверяем что все устройства ссылаются на существующие комнаты
        for device_type in ["lighting", "climate", "ventilation"]:
            for device in manifest.get("devices", {}).get(device_type, []):
                room = device.get("room")
                if room and room not in zone_ids:
                    errors.append(ValidationError(
                        f"devices.{device_type}[{device.get('id')}].room",
                        f"Комната '{room}' не найдена в zones"
                    ))

        return errors

    def _validate_logic(self, manifest: dict) -> list[ValidationError]:
        """Логические проверки"""
        errors = []

        # Проверка уникальности ID устройств
        seen_ids = set()
        for device_type in ["lighting", "climate", "ventilation"]:
            for device in manifest.get("devices", {}).get(device_type, []):
                device_id = device.get("id")
                if device_id:
                    if device_id in seen_ids:
                        errors.append(ValidationError(
                            f"devices.{device_type}[{device_id}].id",
                            f"Дубликат ID: {device_id}"
                        ))
                    seen_ids.add(device_id)

        # Проверка уникальности ID зон
        zone_ids = set()
        for zone in manifest.get("zones", []):
            zone_id = zone.get("id")
            if zone_id:
                if zone_id in zone_ids:
                    errors.append(ValidationError(
                        f"zones[{zone_id}].id",
                        f"Дубликат ID зоны: {zone_id}"
                    ))
                zone_ids.add(zone_id)

        # Проверка диапазонов температур
        for device in manifest.get("devices", {}).get("climate", []):
            target = device.get("target")
            if target is not None:
                if not (10.0 <= target <= 35.0):
                    errors.append(ValidationError(
                        f"devices.climate[{device.get('id')}].target",
                        f"Целевая температура {target} вне диапазона 10-35"
                    ))
            
            hysteresis = device.get("hysteresis")
            if hysteresis is not None:
                if not (0.1 <= hysteresis <= 5.0):
                    errors.append(ValidationError(
                        f"devices.climate[{device.get('id')}].hysteresis",
                        f"Гистерезис {hysteresis} вне диапазона 0.1-5.0"
                    ))

        # Проверка порогов влажности для вентиляции
        for device in manifest.get("devices", {}).get("ventilation", []):
            threshold = device.get("humidity_threshold")
            if threshold is not None:
                if not (0 <= threshold <= 100):
                    errors.append(ValidationError(
                        f"devices.ventilation[{device.get('id')}].humidity_threshold",
                        f"Порог влажности {threshold} вне диапазона 0-100"
                    ))

        return errors

    @staticmethod
    def _is_valid_entity_id(entity_id: str) -> bool:
        """Проверка формата entity_id (domain.entity_name)"""
        if not entity_id or not isinstance(entity_id, str):
            return False
        return bool(re.match(r"^[a-z_]+\.[a-z0-9_]+$", entity_id))

    @staticmethod
    def _is_valid_schedule(schedule: str) -> bool:
        """Проверка формата расписания '07:00-23:00'"""
        if not schedule or not isinstance(schedule, str):
            return False
        return bool(re.match(r"^\d{2}:\d{2}-\d{2}:\d{2}$", schedule))


def validate_manifest(manifest: dict) -> list[ValidationError]:
    """Удобная функция для валидации манифеста"""
    validator = ManifestValidator()
    return validator.validate(manifest)
