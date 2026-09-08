"""
Монитор изменений манифеста для автообновления дашборда.

Следит за файлом манифеста и при изменениях автоматически
перегенерирует дашборд.

Использование:
    python tools/dashboard_watcher.py --watch
    python tools/dashboard_watcher.py --manifest instances/leonids_house/manifest.yaml
"""

import argparse
import hashlib
import time
from pathlib import Path
from typing import Optional


class DashboardWatcher:
    """
    Мониторит изменения манифеста и автоматически обновляет дашборд.

    Алгоритм работы:
    1. Вычисляет MD5 хеш текущего манифеста
    2. Каждые N секунд проверяет хеш снова
    3. При изменении хеша → перегенерирует дашборд
    4. Логгирует все изменения
    """

    def __init__(
        self,
        manifest_path: str,
        output_dir: str = "generated_dashboards",
        check_interval_sec: int = 2,
        logger=None,
    ):
        """
        Инициализация наблюдателя.

        Args:
            manifest_path: Путь к файлу манифеста
            output_dir: Директория для сохранения дашбордов
            check_interval_sec: Интервал проверки изменений (секунды)
            logger: Логгер для вывода сообщений
        """
        self._manifest_path = Path(manifest_path).expanduser()
        self._output_dir = Path(output_dir)
        self._check_interval = check_interval_sec
        self._logger = logger or self._create_default_logger()
        self._last_hash: Optional[str] = None
        self._last_modified: float = 0.0
        self._update_count = 0

    @staticmethod
    def _create_default_logger():
        """Создаёт простой логгер по умолчанию"""
        import logging

        logger = logging.getLogger("dashboard_watcher")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(
                logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            )
            logger.addHandler(handler)
        return logger

    def _log(self, message: str, level: str = "info"):
        """Логгирование сообщения"""
        getattr(self._logger, level.lower(), self._logger.info)(message)

    def _get_file_hash(self, path: Path) -> Optional[str]:
        """
        Вычисляет MD5 хеш файла.

        Args:
            path: Путь к файлу

        Returns:
            str: HEX представление хеша или None если файл не доступен
        """
        try:
            with open(path, "rb") as f:
                return hashlib.md5(f.read()).hexdigest()
        except FileNotFoundError:
            self._log(f"Файл не найден: {path}", "error")
            return None
        except Exception as e:
            self._log(f"Ошибка чтения файла: {e}", "error")
            return None

    def _get_file_mtime(self, path: Path) -> float:
        """Получает время последней модификации файла"""
        try:
            return path.stat().st_mtime
        except Exception:
            return 0.0

    def _update_dashboard(self):
        """Обновляет дашборд при изменении манифеста"""
        import sys
        from pathlib import Path as PPath
        
        # Добавляем workspace в path для импортов
        workspace_dir = PPath(__file__).parent.parent
        if str(workspace_dir) not in sys.path:
            sys.path.insert(0, str(workspace_dir))
        
        from tools.dashboard_generator import DashboardGenerator
        import yaml

        try:
            # Загружаем манифест
            with open(self._manifest_path, "r", encoding="utf-8") as f:
                manifest = yaml.safe_load(f)

            # Создаём генератор
            generator = DashboardGenerator(manifest, self._logger)

            # Генерируем и сохраняем дашборд
            output_path = generator.generate_and_save(
                output_dir=str(self._output_dir),
                filename=f"dashboard_{manifest.get('instance', {}).get('id', 'smart_home')}.yaml"
            )

            self._update_count += 1
            self._log(f"✅ Дашборд обновлён (версия #{self._update_count}): {output_path}")

        except Exception as e:
            self._log(f"❌ Ошибка обновления дашборда: {e}", "error")

    def watch(self, duration_sec: Optional[int] = None):
        """
        Запускает мониторинг изменений.

        Args:
            duration_sec: Длительность мониторинга в секундах (None = бесконечно)
        """
        if not self._manifest_path.exists():
            self._log(f"❌ Манифест не найден: {self._manifest_path}", "error")
            return

        self._log(f"👀 Начало мониторинга: {self._manifest_path}")
        self._log(f"📝 Интервал проверки: {self._check_interval}с")
        self._log(f"📁 Выходная директория: {self._output_dir}")
        self._log("Press Ctrl+C to stop")

        # Инициализируем хеш
        self._last_hash = self._get_file_hash(self._manifest_path)
        self._last_modified = self._get_file_mtime(self._manifest_path)

        if self._last_hash:
            self._log(f"🔐 Начальный хеш: {self._last_hash[:8]}...")

        # Первая генерация дашборда
        self._log("🔄 Первая генерация дашборда...")
        self._update_dashboard()

        start_time = time.time()

        try:
            while True:
                # Проверяем длительность
                if duration_sec and (time.time() - start_time) > duration_sec:
                    self._log(f"⏰ Достигнут лимит времени ({duration_sec}с)")
                    break

                # Ждём интервал
                time.sleep(self._check_interval)

                # Проверяем изменения
                current_hash = self._get_file_hash(self._manifest_path)
                current_mtime = self._get_file_mtime(self._manifest_path)

                if current_hash != self._last_hash:
                    self._log("📝 Обнаружено изменение манифеста")
                    self._log(f"🔐 Хеш: {self._last_hash[:8]}... → {current_hash[:8]}...")
                    self._update_dashboard()
                    self._last_hash = current_hash
                    self._last_modified = current_mtime

        except KeyboardInterrupt:
            self._log("\n🛑 Мониторинг остановлен пользователем")
        finally:
            self._log(f"📊 Итого обновлений: {self._update_count}")


def main():
    """CLI интерфейс для dashboard_watcher"""
    parser = argparse.ArgumentParser(
        description="Монитор изменений манифеста для автообновления дашборда"
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Запустить мониторинг изменений",
    )
    parser.add_argument(
        "--manifest",
        type=str,
        default="instances/leonids_house/manifest.yaml",
        help="Путь к манифесту (по умолчанию: instances/leonids_house/manifest.yaml)",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="generated_dashboards",
        help="Директория для дашбордов (по умолчанию: generated_dashboards)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=2,
        help="Интервал проверки в секундах (по умолчанию: 2)",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=None,
        help="Длительность мониторинга в секундах (None = бесконечно)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Однократная генерация без мониторинга",
    )

    args = parser.parse_args()

    watcher = DashboardWatcher(
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        check_interval_sec=args.interval,
    )

    if args.once:
        # Однократная генерация
        watcher._update_dashboard()
    elif args.watch:
        # Запуск мониторинга
        watcher.watch(duration_sec=args.duration)
    else:
        # Показываем справку
        parser.print_help()


if __name__ == "__main__":
    main()
