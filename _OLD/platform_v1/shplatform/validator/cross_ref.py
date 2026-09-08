"""Проверки связности манифеста (cross-references)."""
from __future__ import annotations

from dataclasses import dataclass, field

from shplatform.schema import Manifest


@dataclass
class ValidationIssue:
    path: str
    code: str
    message: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.path}: {self.message}"


@dataclass
class ValidationReport:
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def add(self, path: str, code: str, message: str) -> None:
        self.issues.append(ValidationIssue(path, code, message))


def validate_manifest(manifest: Manifest) -> ValidationReport:
    report = ValidationReport()
    device_ids = manifest.devices.all_ids()

    _check_duplicate_device_ids(manifest, report)
    _check_lighting_refs(manifest, device_ids, report)
    _check_irrigation_refs(manifest, device_ids, report)
    _check_climate_refs(manifest, device_ids, report)
    _check_climate_priorities(manifest, report)

    return report


def _check_duplicate_device_ids(manifest: Manifest, report: ValidationReport) -> None:
    seen: dict[str, int] = {}
    for group in (manifest.devices.hybrid_switches, manifest.devices.lights,
                  manifest.devices.sensors, manifest.devices.actuators,
                  manifest.devices.valves):
        for dev in group:
            seen[dev.id] = seen.get(dev.id, 0) + 1

    for did, count in seen.items():
        if count > 1:
            report.add(
                f"devices.{did}", "DUPLICATE_DEVICE_ID",
                f"Device id '{did}' встречается {count} раз. ID должны быть уникальны.",
            )


def _check_lighting_refs(manifest: Manifest, device_ids: set[str],
                         report: ValidationReport) -> None:
    for i, zone in enumerate(manifest.features.lighting.zones):
        base = f"features.lighting.zones[{i}]"
        for ref in zone.device_refs:
            if ref not in device_ids:
                report.add(f"{base}.device_refs", "UNKNOWN_DEVICE_REF",
                           f"'{ref}' не найден в devices")


def _check_irrigation_refs(manifest: Manifest, device_ids: set[str],
                           report: ValidationReport) -> None:
    for i, zone in enumerate(manifest.features.irrigation.zones):
        base = f"features.irrigation.zones[{i}]"
        if zone.valve_ref and zone.valve_ref not in device_ids:
            report.add(f"{base}.valve_ref", "UNKNOWN_DEVICE_REF",
                       f"'{zone.valve_ref}' не найден в devices")
        if zone.moisture_sensor_ref and zone.moisture_sensor_ref not in device_ids:
            report.add(f"{base}.moisture_sensor_ref", "UNKNOWN_DEVICE_REF",
                       f"'{zone.moisture_sensor_ref}' не найден в devices")


def _check_climate_refs(manifest: Manifest, device_ids: set[str],
                        report: ValidationReport) -> None:
    for i, zone in enumerate(manifest.features.climate.zones):
        base = f"features.climate.zones[{i}]"
        if zone.temp_sensor_ref and zone.temp_sensor_ref not in device_ids:
            report.add(f"{base}.temp_sensor_ref", "UNKNOWN_DEVICE_REF",
                       f"'{zone.temp_sensor_ref}' не найден в devices")
        for j, act in enumerate(zone.actuators):
            if act.ref not in device_ids:
                report.add(f"{base}.actuators[{j}].ref", "UNKNOWN_DEVICE_REF",
                           f"'{act.ref}' не найден в devices")


def _check_climate_priorities(manifest: Manifest, report: ValidationReport) -> None:
    for i, zone in enumerate(manifest.features.climate.zones):
        base = f"features.climate.zones[{i}].actuators"
        priorities: dict[int, str] = {}
        for act in zone.actuators:
            if act.priority in priorities:
                report.add(
                    base, "DUPLICATE_PRIORITY",
                    f"Приоритет {act.priority} занят '{priorities[act.priority]}' "
                    f"и '{act.ref}'. Приоритеты в зоне должны быть уникальны.",
                )
            else:
                priorities[act.priority] = act.ref
