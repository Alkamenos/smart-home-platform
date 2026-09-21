"""Tests for DeviceClassifier."""

from src.core.discovery.classifier import DeviceClassifier
from src.core.discovery.models import DeviceCategory


class TestDeviceClassifier:
    def test_classify_light_auto_apply(self):
        category, template, auto_apply = DeviceClassifier.classify(
            "light.kitchen_main", "light", {}
        )
        assert category == DeviceCategory.LIGHTING
        assert template == "lighting"
        assert auto_apply is True

    def test_classify_climate_auto_apply(self):
        category, template, auto_apply = DeviceClassifier.classify(
            "climate.bedroom_ac", "climate", {}
        )
        assert category == DeviceCategory.CLIMATE_CONTROL
        assert template == "climate_control"
        assert auto_apply is True

    def test_classify_fan_auto_apply(self):
        category, template, auto_apply = DeviceClassifier.classify("fan.bathroom_vent", "fan", {})
        assert category == DeviceCategory.VENTILATION
        assert template == "humidity_ventilation"
        assert auto_apply is True

    def test_classify_sensor_no_auto_apply(self):
        category, template, auto_apply = DeviceClassifier.classify(
            "sensor.temperatura_v_teplitse_ogurtsy_humidity", "sensor", {}
        )
        assert category == DeviceCategory.TEMPERATURE_SENSOR
        assert template is None
        assert auto_apply is False

    def test_classify_plesen_monitoring(self):
        category, template, auto_apply = DeviceClassifier.classify(
            "sensor.ogurtsy_plesen", "sensor", {}
        )
        assert category == DeviceCategory.MONITORING_ONLY
        assert template is None
        assert auto_apply is False

    def test_classify_water_depth_monitoring(self):
        category, template, auto_apply = DeviceClassifier.classify(
            "sensor.datchik_urovnia_vody_v_bakakh_liquid_depth", "sensor", {}
        )
        assert category == DeviceCategory.MONITORING_ONLY

    def test_extract_room_name(self):
        assert DeviceClassifier.extract_room_name("light.kitchen_main") == "kitchen"
        assert DeviceClassifier.extract_room_name("binary_sensor.hallway_motion") == "hallway"
        assert DeviceClassifier.extract_room_name("sensor.living_room_temperature") == "living_room"

    def test_auto_apply_stats(self):
        class MockDevice:
            def __init__(self, auto_apply):
                self.auto_apply = auto_apply

        devices = [MockDevice(True), MockDevice(True), MockDevice(False)]
        stats = DeviceClassifier.get_auto_apply_count(devices)
        assert stats["auto_apply"] == 2
        assert stats["manual"] == 1
