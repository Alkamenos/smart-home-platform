"""Миграции манифестов умного дома."""

from abc import ABC, abstractmethod


class Migration(ABC):
    """Базовый класс для миграций манифеста.
    
    Атрибуты:
        version: Версия манифеста, к которой применяется эта миграция.
        description: Описание того, что делает миграция.
    """
    
    version: int = 0
    description: str = ""
    
    @abstractmethod
    def up(self, manifest: dict) -> dict:
        """Применить миграцию к манифесту.
        
        Args:
            manifest: Словарь с данными манифеста.
            
        Returns:
            dict: Манифест после применения миграции.
        """
        pass
    
    @abstractmethod
    def down(self, manifest: dict) -> dict:
        """Отменить миграцию (откатить изменения).
        
        Args:
            manifest: Словарь с данными манифеста после применения миграции.
            
        Returns:
            dict: Манифест до применения миграции.
        """
        pass


__all__ = ["Migration"]
