"""Раннер миграций для автоматического применения миграций при загрузке манифеста."""

import importlib
import pkgutil
from pathlib import Path

from smart_home.migrations import Migration


class MigrationRunner:
    """Раннер миграций для автоматического применения миграций к манифесту.
    
    Атрибуты:
        migrations: Список всех доступных миграций, отсортированных по версии.
    """
    
    def __init__(self):
        """Инициализировать раннер и загрузить все доступные миграции."""
        self.migrations: list[Migration] = []
        self._discover_migrations()
    
    def _discover_migrations(self) -> None:
        """Найти и загрузить все классы миграций из пакета migrations."""
        import smart_home.migrations as migrations_pkg
        
        # Получаем список всех модулей в пакете migrations
        package_path = Path(migrations_pkg.__file__).parent
        
        for module_info in pkgutil.iter_modules([str(package_path)]):
            if module_info.name.startswith("__"):
                continue
            
            # Импортируем модуль миграции
            full_name = f"smart_home.migrations.{module_info.name}"
            try:
                module = importlib.import_module(full_name)
            except Exception:
                continue
            
            # Находим все классы миграций в модуле
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and 
                    issubclass(attr, Migration) and 
                    attr is not Migration):
                    # Создаем экземпляр миграции
                    migration = attr()
                    self.migrations.append(migration)
        
        # Сортируем миграции по версии
        self.migrations.sort(key=lambda m: m.version)
    
    def get_current_version(self, manifest: dict) -> int:
        """Получить текущую версию манифеста.
        
        Args:
            manifest: Словарь с данными манифеста.
            
        Returns:
            int: Текущая версия манифеста или 0, если версия не указана.
        """
        return manifest.get("version", 0)
    
    def get_target_version(self) -> int:
        """Получить целевую версию (последнюю доступную миграцию).
        
        Returns:
            int: Номер последней версии.
        """
        if not self.migrations:
            return 0
        return max(m.version for m in self.migrations)
    
    def apply(self, manifest: dict) -> dict:
        """Применить все необходимые миграции к манифесту.
        
        Args:
            manifest: Словарь с данными манифеста.
            
        Returns:
            dict: Манифест после применения всех миграций.
        """
        current_version = self.get_current_version(manifest)
        target_version = self.get_target_version()
        
        if current_version >= target_version:
            # Манифест уже актуален
            return manifest
        
        # Применяем миграции последовательно
        result = dict(manifest)
        for migration in self.migrations:
            if migration.version > current_version:
                result = migration.up(result)
        
        # Устанавливаем финальную версию
        result["version"] = target_version
        
        return result
    
    def rollback(self, manifest: dict, target_version: int = 0) -> dict:
        """Откатить миграции до указанной версии.
        
        Args:
            manifest: Словарь с данными манифеста.
            target_version: Версия, до которой нужно откатиться.
            
        Returns:
            dict: Манифест после отката миграций.
        """
        current_version = self.get_current_version(manifest)
        
        if current_version <= target_version:
            # Откат не требуется
            return manifest
        
        # Откатываем миграции в обратном порядке
        result = dict(manifest)
        for migration in reversed(self.migrations):
            if migration.version <= target_version:
                break
            if migration.version <= current_version:
                result = migration.down(result)
        
        result["version"] = target_version
        
        return result
    
    def migrate(self, manifest: dict) -> dict:
        """Автоматически применить миграции при загрузке манифеста.
        
        Это основной метод, который следует вызывать при загрузке манифеста
        для автоматического обновления старых форматов.
        
        Args:
            manifest: Словарь с данными манифеста.
            
        Returns:
            dict: Манифест после применения всех необходимых миграций.
        """
        return self.apply(manifest)
