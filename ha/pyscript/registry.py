"""Runtime-реестр платформы.

Строит удобные структуры доступа из dict-манифеста.
НЕ зависит от Pydantic и Home Assistant, поэтому используется:
  - в CLI-тестах (как модуль пакета),
  - внутри pyscript (копируется в <config>/pyscript/ и работает глобально)."""
from __future__ import annotations


class ManifestError(Exception):
    """Ошибка при построении реестра из манифеста."""


class RuntimeRegistry:
    """Развернутые ссылки манифеста для быстрого доступа в runtime."""

    def __init__(self, manifest: dict):
        self._raw = manifest or {}
        self._devices_by_id = {}
        self._entity_to_device = {}
        self._features = {}
        self._build()

    # ---- построение ----
    def _build(self):
        devices = self._raw.get("devices", {}) or {}
        for group_name, group in devices.items():
            for dev in group or []:
                did = dev.get("id")
                if not did:
                    raise ManifestError(f"Устройство без id в devices.{group_name}")
                if did in self._devices_by_id:
                    raise ManifestError(f"Дублирующийся device id: {did}")
                self._devices_by_id[did] = dev
                entity = dev.get("entity") or dev.get("relay_entity")
                if entity:
                    self._entity_to_device[entity] = did

        for fname, fcfg in (self._raw.get("features", {}) or {}).items():
            self._features[fname] = fcfg or {}

    # ---- доступ к устройствам ----
    def device(self, device_id):
        return self._devices_by_id.get(device_id)

    def device_for_entity(self, entity_id):
        did = self._entity_to_device.get(entity_id)
        return self._devices_by_id.get(did) if did else None

    def entity_for_device(self, device_id):
        dev = self._devices_by_id.get(device_id) or {}
        return dev.get("entity") or dev.get("relay_entity")

    def all_devices(self):
        return dict(self._devices_by_id)

    # ---- доступ к фичам ----
    def feature(self, name):
        return self._features.get(name, {})

    def feature_enabled(self, name):
        f = self._features.get(name)
        if not isinstance(f, dict):
            return True
        return bool(f.get("enabled", True))

    def features(self):
        return dict(self._features)

    # ---- helpers provisioning ----
    def required_helpers(self):
        """helper entity_id, которые должны существовать в HA."""
        helpers = set()
        # по одному toggle на фичу
        for fname in self._features:
            if not isinstance(self._features[fname], dict):
                continue
            helpers.add(f"input_boolean.feature_{fname}")
        # setpoints климата (input_number.*)
        for zone in self.feature("climate").get("zones", []):
            for sp in (zone.get("setpoints") or {}).values():
                if isinstance(sp, dict):
                    src = sp.get("source","")
                    if isinstance(src, str) and src.startswith("input_number."):
                        helpers.add(src)
        # глобальные режимы (input_boolean.*)
        for mode in (self._raw.get("globals", {}).get("modes", {}) or {}).values():
            entity = (mode or {}).get("entity","")
            if isinstance(entity, str) and entity.startswith("input_boolean."):
                helpers.add(entity)
        return sorted(helpers)

    def summary(self):
        return {"instance": (self._raw.get("instance", {}) or {}).get("id"),"devices": len(self._devices_by_id),"features": {n: self.feature_enabled(n) for n in self._features},"required_helpers": self.required_helpers(),
        }


def build_registry(manifest: dict) -> RuntimeRegistry:
    return RuntimeRegistry(manifest)