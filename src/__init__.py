"""
Smart Home Platform - Интеграция с Home Assistant.

Основной пакет приложения.
"""

from src.core.security.encryption import TokenEncryptor, generate_encryption_key

__version__ = "3.0.0"

__all__ = [
    "TokenEncryptor",
    "generate_encryption_key",
]
