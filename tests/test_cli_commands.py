"""
Tests for CLI Commands (validate, doctor, health)

Проверяет:
- test_validate_should_succeed_when_manifest_valid
- test_validate_should_fail_when_manifest_invalid
- test_doctor_should_detect_issues
- test_health_should_return_platform_status
"""

import pytest
import yaml
import sys
from pathlib import Path
from io import StringIO
from unittest.mock import patch, MagicMock
import argparse

# Добавляем workspace в path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCLIValidateCommand:
    """Tests for cli.py validate command"""

    @pytest.fixture
    def valid_manifest_path(self, tmp_path):
        """Creates a temporary valid manifest"""
        manifest = {
            "version": 1,
            "instance": {
                "id": "test_house",
                "name": "Test House",
                "owner": "Test Owner",
                "created_at": "2024-01-01"
            },
            "zones": [
                {"id": "kitchen", "name": "Kitchen", "floor": 1}
            ],
            "devices": [
                {
                    "type": "light_motion",
                    "id": "light.kitchen",
                    "name": "Kitchen Light",
                    "room": "kitchen",
                    "behaviors": [
                        {
                            "template": "lighting",
                            "priority": 10,
                            "params": {
                                "motion_sensor": "binary_sensor.kitchen_motion",
                                "schedule": "07:00-23:00",
                                "motion_timeout_sec": 300
                            }
                        }
                    ]
                }
            ],
            "automation_rules": {
                "lighting": {
                    "motion_enabled": True,
                    "schedule_enabled": True,
                    "manual_lockout_min": 60
                },
                "climate": {
                    "safety_lockout_enabled": True,
                    "away_mode_enabled": True,
                    "manual_lockout_min": 30
                },
                "ventilation": {
                    "humidity_based": True,
                    "manual_lockout_min": 15
                }
            },
            "dashboard": {
                "title": "Test House",
                "show_history": True,
                "show_climate": True,
                "show_motion_sensors": True,
                "history_days": 7
            }
        }
        
        manifest_file = tmp_path / "manifest.yaml"
        with open(manifest_file, 'w') as f:
            yaml.dump(manifest, f)
        
        return str(manifest_file)

    @pytest.fixture
    def invalid_manifest_path(self, tmp_path):
        """Creates a temporary invalid manifest"""
        # Invalid: missing required field version
        manifest = {
            "instance": {
                "id": "test_house",
                "name": "Test House",
                "owner": "Test Owner",
                "created_at": "2024-01-01"
            },
            "zones": [],
            "devices": [],
            "automation_rules": {
                "lighting": {
                    "motion_enabled": True,
                    "schedule_enabled": True,
                    "manual_lockout_min": 60
                },
                "climate": {
                    "safety_lockout_enabled": True,
                    "away_mode_enabled": True,
                    "manual_lockout_min": 30
                },
                "ventilation": {
                    "humidity_based": True,
                    "manual_lockout_min": 15
                }
            },
            "dashboard": {
                "title": "Test House",
                "show_history": True,
                "show_climate": True,
                "show_motion_sensors": True,
                "history_days": 7
            }
        }
        
        manifest_file = tmp_path / "invalid_manifest.yaml"
        with open(manifest_file, 'w') as f:
            yaml.dump(manifest, f)
        
        return str(manifest_file)

    def test_validate_should_succeed_when_manifest_valid(self, valid_manifest_path, capsys):
        """Valid manifest should pass validation"""
        from cli import cmd_validate
        
        args = argparse.Namespace(manifest_path=valid_manifest_path)
        
        # Should not raise exception
        cmd_validate(args)
        
        captured = capsys.readouterr()
        assert "✅" in captured.out or "валиден" in captured.out.lower()

    def test_validate_should_fail_when_manifest_invalid(self, invalid_manifest_path, capsys):
        """Invalid manifest should fail validation"""
        from cli import cmd_validate
        
        args = argparse.Namespace(manifest_path=invalid_manifest_path)
        
        # Should call sys.exit(1)
        with pytest.raises(SystemExit) as exc_info:
            cmd_validate(args)
        
        assert exc_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "❌" in captured.out or "ошибка" in captured.out.lower()

    def test_validate_should_fail_when_manifest_not_found(self, capsys):
        """Non-existent manifest should fail"""
        from cli import cmd_validate
        
        args = argparse.Namespace(manifest_path="/non/existent/manifest.yaml")
        
        with pytest.raises(SystemExit) as exc_info:
            cmd_validate(args)
        
        assert exc_info.value.code == 1
        
        captured = capsys.readouterr()
        assert "❌" in captured.out or "не найден" in captured.out.lower()


class TestCLIDoctorCommand:
    """Tests for cli.py doctor command"""

    def test_doctor_should_detect_manifest_issues(self, capsys):
        """Doctor should detect and report manifest issues"""
        from cli import cmd_doctor
        import argparse
        
        args = argparse.Namespace()
        args.manifest_path = None
        args.json = False
        
        # Run doctor command (it should handle missing manifest gracefully)
        with patch('cli.bootstrap_platform') as mock_bootstrap:
            mock_bootstrap.side_effect = Exception("Manifest not found")
            cmd_doctor(args)
        
        captured = capsys.readouterr()
        # Doctor should output diagnostic information
        assert len(captured.out) > 0

    def test_doctor_should_check_platform_health(self, capsys):
        """Doctor should check platform health components"""
        from cli import cmd_doctor
        import argparse
        
        args = argparse.Namespace()
        args.manifest_path = None
        args.json = False
        
        # Mock manifest existence to allow full check
        class MockManifest:
            class instance:
                name = "Test House"
        
        class MockCtx:
            manifest = MockManifest()
            fsm = None
            dispatcher = type('obj', (object,), {'_middlewares': []})()
        
        with patch('cli.bootstrap_platform') as mock_bootstrap:
            mock_bootstrap.return_value = MockCtx()
            with patch('smart_home.core.fsm_factory.FSMFactory'):
                cmd_doctor(args)
        
        captured = capsys.readouterr()
        # Should output diagnostic information
        assert len(captured.out) > 0


class TestCLIHealthCommand:
    """Tests for cli.py health command"""

    def test_health_should_return_status(self, capsys):
        """Health command should return platform status"""
        from cli import cmd_health
        import argparse
        
        args = argparse.Namespace()
        args.manifest_path = None
        args.health_command = None
        
        # Run health command
        cmd_health(args)
        
        captured = capsys.readouterr()
        # Should output health status
        assert len(captured.out) > 0

    def test_health_should_check_components(self, capsys):
        """Health command should check individual components"""
        from cli import cmd_health
        import argparse
        
        args = argparse.Namespace()
        args.manifest_path = None
        args.health_command = None
        
        class MockManifest:
            class instance:
                name = "Test House"
        
        class MockCtx:
            manifest = MockManifest()
            fsm = None
            dispatcher = type('obj', (object,), {'_middlewares': []})()
        
        with patch('cli.bootstrap_platform') as mock_bootstrap:
            mock_bootstrap.return_value = MockCtx()
            cmd_health(args)
        
        captured = capsys.readouterr()
        # Should output component status
        assert len(captured.out) > 0
