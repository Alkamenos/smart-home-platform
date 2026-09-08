"""
Phase 4 Integration Tests - Тесты для финальной фазы

Проверяет:
- CLI deploy команду
- Hot-reload функциональность
- Migration tool
- Dashboard integration
"""
import pytest
import os
import json
import tempfile
from pathlib import Path


class TestPhase4Deploy:
    """Тесты для CLI deploy команды"""
    
    def test_deploy_dry_run(self):
        """Тест dry-run режима деплоя"""
        from loader import PyscriptLoader
        
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = PyscriptLoader(ha_config_dir=tmpdir)
            
            # Проверяем что loader создан корректно
            assert loader.ha_config_dir == Path(tmpdir)
            assert loader.pyscript_dir == Path(tmpdir) / "pyscript"
    
    def test_deploy_creates_structure(self):
        """Тест создания структуры файлов при деплое"""
        from loader import PyscriptLoader
        
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = PyscriptLoader(ha_config_dir=tmpdir)
            
            # Выполняем деплой
            pyscript_dir = Path(tmpdir) / "pyscript"
            
            # Копируем файлы
            core_files = loader.copy_core_files()
            features_files = loader.copy_features_files()
            adapters_files = loader.copy_adapters_files()
            
            # Проверяем что файлы скопированы
            assert len(core_files) > 0
            assert len(features_files) > 0
            assert len(adapters_files) > 0
            
            # Проверяем структуру
            assert (pyscript_dir / "platform_v3" / "core").exists()
            assert (pyscript_dir / "platform_v3" / "features").exists()
            assert (pyscript_dir / "platform_v3" / "adapters").exists()
    
    def test_deploy_creates_config(self):
        """Тест создания конфигурационных файлов"""
        from loader import PyscriptLoader
        
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = PyscriptLoader(ha_config_dir=tmpdir)
            pyscript_dir = Path(tmpdir) / "pyscript"
            
            # Создаём директорию pyscript заранее
            pyscript_dir.mkdir(parents=True, exist_ok=True)
            
            # Создаём конфиги
            pyscript_yaml = loader.create_pyscript_yaml()
            init_script = loader.create_init_script()
            
            # Проверяем существование
            assert pyscript_yaml.exists()
            assert init_script.exists()
            
            # Проверяем содержимое pyscript.yaml
            content = pyscript_yaml.read_text()
            assert "allow_all_imports: true" in content
            
            # Проверяем содержимое init скрипта
            content = init_script.read_text()
            assert "FSMEngine" in content
            assert "create_lighting_automations" in content


class TestPhase4HotReload:
    """Тесты для hot-reload функциональности"""
    
    def test_hot_reload_start_stop(self):
        """Тест запуска и остановки hot-reload"""
        from loader import PyscriptLoader
        import time
        
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = PyscriptLoader(ha_config_dir=tmpdir)
            
            callback_called = []
            
            def callback(changed_files):
                callback_called.append(changed_files)
            
            # Запускаем hot-reload
            loader.start_hot_reload(callback=callback)
            assert loader._watch_thread is not None
            assert loader._stop_watching is False
            
            # Ждём немного
            time.sleep(0.5)
            
            # Останавливаем
            loader.stop_hot_reload()
            assert loader._stop_watching is True
    
    def test_hot_reload_detects_changes(self):
        """Тест обнаружения изменений файлов"""
        from loader import PyscriptLoader
        import time
        
        with tempfile.TemporaryDirectory() as tmpdir:
            loader = PyscriptLoader(ha_config_dir=tmpdir)
            
            # Инициализируем хэши
            source_dir = Path(tmpdir) / "source"
            source_dir.mkdir()
            (source_dir / "core").mkdir()
            test_file = source_dir / "core" / "test.py"
            test_file.write_text("initial content")
            
            loader.source_dir = source_dir
            loader._update_file_hashes(source_dir / "core")
            
            # Изменяем файл
            test_file.write_text("modified content")
            
            # Проверяем изменения
            changed = loader._check_file_changes()
            assert "core/test.py" in changed


class TestPhase4Migration:
    """Тесты для migration tool"""
    
    def test_validate_v3_config(self):
        """Тест валидации V3 конфигурации"""
        from migration.migrate import MigrationTool
        
        tool = MigrationTool()
        
        # Валидная конфигурация
        valid_config = {
            'version': '3.0',
            'features': {
                'test_feature': {
                    'id': 'test_feature',
                    'type': 'lighting',
                    'initial_state': 'off',
                    'states': [{'id': 'off', 'name': 'Off'}],
                    'transitions': []
                }
            }
        }
        
        errors = tool.validate_v3_config(valid_config)
        assert len(errors) == 0
        
        # Невалидная конфигурация
        invalid_config = {
            'version': '2.0',  # Неправильная версия
            'features': {
                'bad_feature': {
                    # Отсутствуют обязательные поля
                }
            }
        }
        
        errors = tool.validate_v3_config(invalid_config)
        assert len(errors) > 0
    
    def test_migrate_from_v2_sync(self):
        """Тест миграции из V2 в V3 (синхронная версия)"""
        import asyncio
        from migration.migrate import MigrationTool
        import json
        
        async def run_migration():
            tool = MigrationTool()
            
            # Создаём тестовый конфиг V2
            v2_config = {
                'automations': {
                    'test_auto': {
                        'name': 'Test Automation',
                        'states': {
                            'off': {'name': 'Off', 'actions': []},
                            'on': {'name': 'On', 'actions': []}
                        },
                        'transitions': [
                            {'from': 'off', 'to': 'on', 'trigger': 'test', 'priority': 10}
                        ],
                        'entities': ['light.test']
                    }
                },
                'adapters': {},
                'settings': {}
            }
            
            with tempfile.TemporaryDirectory() as tmpdir:
                config_file = Path(tmpdir) / "v2_config.json"
                output_dir = Path(tmpdir) / "output"
                
                with open(config_file, 'w') as f:
                    json.dump(v2_config, f)
                
                # Запускаем миграцию
                report = await tool.migrate_from_v2(str(config_file), str(output_dir))
                
                # Проверяем отчет
                assert report.source_version == "2.0"
                assert report.target_version == "3.0"
                assert report.migrated == 1
                assert report.failed == 0
                
                # Проверяем выходной файл
                output_file = output_dir / "v3_config.yaml"
                assert output_file.exists()
        
        asyncio.run(run_migration())


class TestPhase4Dashboard:
    """Тесты для dashboard integration"""
    
    def test_dashboard_import(self):
        """Тест импорта dashboard модуля"""
        from dashboard.dashboard import DashboardIntegration
        assert DashboardIntegration is not None
    
    def test_dashboard_icons(self):
        """Тест получения иконок для фич"""
        from dashboard.dashboard import DashboardIntegration
        
        # Создаём мок для ha_adapter и event_bus
        class MockHA:
            is_connected = True
        
        class MockEventBus:
            def subscribe(self, *args):
                pass
        
        dashboard = DashboardIntegration(MockHA(), MockEventBus())
        
        # Проверяем иконки
        assert dashboard._get_icon_for_feature('lighting') == 'mdi:lightbulb'
        assert dashboard._get_icon_for_feature('climate') == 'mdi:thermometer'
        assert dashboard._get_icon_for_feature('ventilation') == 'mdi:fan'
        assert dashboard._get_icon_for_feature('unknown') == 'mdi:cog'
    
    def test_dashboard_state_options(self):
        """Тест получения списков состояний"""
        from dashboard.dashboard import DashboardIntegration
        
        class MockHA:
            is_connected = True
        
        class MockEventBus:
            def subscribe(self, *args):
                pass
        
        dashboard = DashboardIntegration(MockHA(), MockEventBus())
        
        # Проверяем опции состояний
        lighting_options = dashboard._get_state_options('lighting')
        assert 'off' in lighting_options
        assert 'on' in lighting_options
        
        climate_options = dashboard._get_state_options('climate')
        assert 'heat' in climate_options
        assert 'cool' in climate_options


class TestPhase4CLI:
    """Тесты для CLI команд Phase 4"""
    
    def test_cli_status_command(self):
        """Тест команды status"""
        import subprocess
        result = subprocess.run(
            ['python', 'cli.py', 'status'],
            cwd='/workspace/platform_v3',
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'light.living_room' in result.stdout
        assert 'OFF' in result.stdout
    
    def test_cli_status_json(self):
        """Тест команды status --json"""
        import subprocess
        import re
        result = subprocess.run(
            ['python', 'cli.py', 'status', '--json'],
            cwd='/workspace/platform_v3',
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        # Извлекаем JSON объект из вывода (между первой { и последней })
        match = re.search(r'(\{.*\})', result.stdout, re.DOTALL)
        if match:
            json_str = match.group(1)
            data = json.loads(json_str)
            assert 'light.living_room' in data
            assert data['light.living_room']['state'] == 'OFF'
    
    def test_cli_debug_command(self):
        """Тест команды debug"""
        import subprocess
        result = subprocess.run(
            ['python', 'cli.py', 'debug', 'light.living_room', '--state'],
            cwd='/workspace/platform_v3',
            capture_output=True,
            text=True
        )
        assert result.returncode == 0
        assert 'light.living_room' in result.stdout
        assert 'OFF' in result.stdout
