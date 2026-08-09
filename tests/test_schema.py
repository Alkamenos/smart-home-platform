import pytest
import yaml
from pydantic import ValidationError

from shplatform.schema import Manifest
from shplatform.validator import validate_manifest


@pytest.fixture
def good_manifest_path():
    return "manifests/ivanov_dacha.yaml"


def _load(path):
    raw = yaml.safe_load(open(path, encoding="utf-8"))
    return Manifest.model_validate(raw)


def test_good_manifest_is_valid(good_manifest_path):
    manifest = _load(good_manifest_path)
    report = validate_manifest(manifest)
    assert report.ok, "\n".join(str(i) for i in report.issues)


def test_unknown_ref_is_caught(good_manifest_path):
    manifest = _load(good_manifest_path)
    manifest.features.lighting.zones[0].device_refs = ["nonexistent_light"]
    report = validate_manifest(manifest)
    assert not report.ok
    assert any(i.code == "UNKNOWN_DEVICE_REF" for i in report.issues)


def test_duplicate_priority_is_caught(good_manifest_path):
    manifest = _load(good_manifest_path)
    zone = manifest.features.climate.zones[0]
    zone.actuators[1].priority = zone.actuators[0].priority
    report = validate_manifest(manifest)
    assert any(i.code == "DUPLICATE_PRIORITY" for i in report.issues)


def test_bad_instance_id_rejected():
    raw = {
        "instance": {"id": "Bad-ID!", "name": "x", "timezone": "UTC", "version": "1"},
        "devices": {}, "features": {}, "globals": {},
    }
    with pytest.raises(ValidationError):
        Manifest.model_validate(raw)
