"""
Тесты для DashboardWatcher - мониторинг изменений манифеста и автообновление дашборда.
"""
import pytest
import tempfile
import time
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch, call

from tools.dashboard_watcher import DashboardWatcher


@pytest.fixture
def temp_files():
    """Создаёт временные файлы для тестов"""
    with tempfile.TemporaryDirectory() as tmpdir:
        manifest_path = Path(tmpdir) / "manifest.yaml"
        output_dir = Path(tmpdir) / "dashboards"
        output_dir.mkdir()
        
        # Начальный манифест
        manifest_path.write_text("""
version: 1
devices:
  lighting:
    - id: light.kitchen
      name: Свет на кухне
""")
        
        yield {
            "manifest_path": str(manifest_path),
            "output_dir": str(output_dir),
            "tmpdir": tmpdir
        }


class TestDashboardWatcherInit:
    """Тесты инициализации DashboardWatcher"""
    
    def test_watcher_created(self, temp_files):
        """Watcher создаётся корректно"""
        watcher = DashboardWatcher(
            manifest_path=temp_files["manifest_path"],
            output_dir=temp_files["output_dir"]
        )
        
        assert str(watcher._manifest_path) == temp_files["manifest_path"]
        assert str(watcher._output_dir) == temp_files["output_dir"]
        assert watcher._last_hash is None


class TestFileHash:
    """Тесты вычисления хэша файла"""
    
    def test_get_file_hash(self, temp_files):
        """Хэш файла вычисляется корректно"""
        watcher = DashboardWatcher(
            manifest_path=temp_files["manifest_path"],
            output_dir=temp_files["output_dir"]
        )
        
        hash1 = watcher._get_file_hash(temp_files["manifest_path"])
        assert hash1 is not None
        assert len(hash1) == 32  # MD5 hash length
        
        # Тот же файл → тот же хэш
        hash2 = watcher._get_file_hash(temp_files["manifest_path"])
        assert hash1 == hash2


class TestChangeDetection:
    """Тесты обнаружения изменений"""
    
    def test_watcher_detects_change(self, temp_files):
        """Изменения в манифесте детектируются"""
        watcher = DashboardWatcher(
            manifest_path=temp_files["manifest_path"],
            output_dir=temp_files["output_dir"]
        )
        
        # Получаем начальный хэш
        initial_hash = watcher._get_file_hash(temp_files["manifest_path"])
        
        # Изменяем манифест
        Path(temp_files["manifest_path"]).write_text("""
version: 1
devices:
  lighting:
    - id: light.kitchen
      name: Свет на кухне
    - id: light.living_room
      name: Свет в гостиной
""")
        
        # Получаем новый хэш
        new_hash = watcher._get_file_hash(temp_files["manifest_path"])
        
        # Хэши должны отличаться
        assert initial_hash != new_hash
    
    def test_watcher_no_update_without_change(self, temp_files):
        """Без изменений хэш не меняется"""
        watcher = DashboardWatcher(
            manifest_path=temp_files["manifest_path"],
            output_dir=temp_files["output_dir"]
        )
        
        hash1 = watcher._get_file_hash(temp_files["manifest_path"])
        time.sleep(0.01)  # Небольшая задержка
        hash2 = watcher._get_file_hash(temp_files["manifest_path"])
        
        assert hash1 == hash2


class TestDashboardUpdate:
    """Тесты обновления дашборда"""
    
    @patch('tools.dashboard_watcher.DashboardGenerator')
    def test_watcher_updates_dashboard(self, mock_generator_class, temp_files):
        """При изменении манифеста дашборд обновляется"""
        # Настраиваем мок генератора
        mock_generator = MagicMock()
        mock_generator_class.return_value = mock_generator
        
        watcher = DashboardWatcher(
            manifest_path=temp_files["manifest_path"],
            output_dir=temp_files["output_dir"]
        )
        
        # Вызываем метод обновления
        watcher._update_dashboard()
        
        # Проверяем что генератор был создан и использован
        mock_generator_class.assert_called_once()
        mock_generator.generate_full_dashboard.assert_called_once()
        mock_generator.write_to_ha.assert_called_once()


class TestWatchLoop:
    """Тесты цикла мониторинга"""
    
    @patch.object(DashboardWatcher, '_update_dashboard')
    def test_watch_loop_short_run(self, mock_update, temp_files):
        """Цикл мониторинга работает корректно (короткий запуск)"""
        watcher = DashboardWatcher(
            manifest_path=temp_files["manifest_path"],
            output_dir=temp_files["output_dir"]
        )
        
        # Запускаем watch в отдельном потоке на короткое время
        import threading
        
        stop_event = threading.Event()
        
        def run_watch():
            # Эмулируем короткий цикл watch
            for _ in range(3):
                current_hash = watcher._get_file_hash(watcher._manifest_path)
                if current_hash != watcher._last_hash:
                    watcher._update_dashboard()
                    watcher._last_hash = current_hash
                time.sleep(0.1)
        
        thread = threading.Thread(target=run_watch)
        thread.start()
        thread.join(timeout=1.0)
        
        # Проверяем что хотя бы один раз было обновление
        # (при старте last_hash=None, поэтому первое изменение всегда триггерит update)
        assert mock_update.call_count >= 1


class TestIntegration:
    """Интеграционные тесты"""
    
    @patch('tools.dashboard_watcher.DashboardGenerator')
    def test_full_watch_scenario(self, mock_generator_class, temp_files):
        """Полный сценарий: создание watcher → изменение манифеста → обновление"""
        mock_generator = MagicMock()
        mock_generator_class.return_value = mock_generator
        
        watcher = DashboardWatcher(
            manifest_path=temp_files["manifest_path"],
            output_dir=temp_files["output_dir"]
        )
        
        # Имитируем первый запуск (last_hash=None)
        initial_hash = watcher._get_file_hash(temp_files["manifest_path"])
        watcher._last_hash = initial_hash
        
        # Изменяем манифест
        Path(temp_files["manifest_path"]).write_text("""
version: 1
devices:
  lighting:
    - id: light.new_room
      name: Новый свет
""")
        
        # Проверяем изменения
        new_hash = watcher._get_file_hash(temp_files["manifest_path"])
        assert initial_hash != new_hash
        
        # Эмулируем проверку в цикле watch
        if new_hash != watcher._last_hash:
            watcher._update_dashboard()
            watcher._last_hash = new_hash
        
        # Проверяем что обновление произошло
        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_async_compatibility(temp_files):
    """Тест совместимости с async кодом"""
    watcher = DashboardWatcher(
        manifest_path=temp_files["manifest_path"],
        output_dir=temp_files["output_dir"]
    )
    
    # _get_file_hash должен работать в async контексте
    hash_result = watcher._get_file_hash(temp_files["manifest_path"])
    assert hash_result is not None
