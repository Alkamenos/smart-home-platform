"""
Smart Home Platform - Интеграция с Home Assistant.

Основной пакет приложения.
"""

try:
    from src.core.security.encryption import TokenEncryptor, generate_encryption_key
except ImportError:
    # cryptography может быть не установлен - это опционально
    TokenEncryptor = None
    generate_encryption_key = None

__version__ = "3.0.0"

__all__ = [
    "TokenEncryptor",
    "generate_encryption_key",
]
