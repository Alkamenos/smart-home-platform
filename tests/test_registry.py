import yaml

from shplatform.loader.registry import build_registry, ManifestError
import pytest


@pytest.fixture
def raw_manifest():
    return yaml.safe_load(open("manifests/ivanov_dacha.yaml", encoding="utf-8"))


def test_registry_builds(raw_manifest):
    reg = build_registry(raw_manifest)
    s = reg.summary()
    assert s["instance"] == "ivanov_dacha"
    assert s["devices"] > 0
    assert s["features"]["climate"] is True


def test_entity_to_device_lookup(raw_manifest):
    reg = build_registry(raw_manifest)
    dev = reg.device_for_entity("switch.valve_front_zb")
    assert dev is not None and dev["id"] == "front_lawn_valve"
    assert reg.entity_for_device("front_lawn_valve") == "switch.valve_front_zb"


def test_required_helpers_include_setpoints_and_toggles(raw_manifest):
    reg = build_registry(raw_manifest)
    helpers = reg.required_helpers()
    assert "input_number.lr_heat_target" in helpers
    assert "input_number.lr_cool_target" in helpers
    assert "input_boolean.feature_lighting" in helpers
    assert "input_boolean.party_mode" in helpers


def test_duplicate_device_id_raises(raw_manifest):
    raw_manifest["devices"]["lights"].append(
        {"id": "lr_main", "entity": "light.dup"}
    )
    with pytest.raises(ManifestError):
        build_registry(raw_manifest)