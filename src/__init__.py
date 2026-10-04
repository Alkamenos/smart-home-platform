"""
Smart Home Platform - Интеграция с Home Assistant.

Основной пакет приложения.
"""

try:
    from core.security.encryption import TokenEncryptor, generate_encryption_key
except ImportError:
    # cryptography может быть не установлен - это опционально.
    # Имена намеренно остаются None, а не подменяются заглушками: вызывающий
    # код отличает «зависимости нет» по None. Аннотировать как
    # ``type[TokenEncryptor] | None`` нельзя — mypy не допускает присваивания
    # None имени, уже связанному с типом/функцией (misc + assignment), поэтому
    # здесь единственный честный вариант — подавить эти два кода.
    TokenEncryptor = None  # type: ignore[assignment,misc]
    generate_encryption_key = None  # type: ignore[assignment]

__version__ = "3.0.0"

__all__ = [
    "TokenEncryptor",
    "generate_encryption_key",
]
