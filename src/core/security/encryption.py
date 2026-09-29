"""
Модуль для шифрования и дешифрования чувствительных данных.

Используется для защиты токенов Home Assistant и других конфиденциальных данных.
"""

import os
from base64 import b64decode, b64encode

from cryptography.fernet import Fernet


class TokenEncryptor:
    """Шифровальщик для токенов и чувствительных данных.

    Использует симметричное шифрование Fernet для защиты данных.
    """

    def __init__(self, encryption_key: str | None = None) -> None:
        """Инициализация шифровальщика.

        Args:
            encryption_key: Ключ шифрования. Если None, использует переменную окружения
                           HOME_ASSISTANT_ENCRYPTION_KEY или генерирует новый.
        """
        if encryption_key is None:
            encryption_key = os.environ.get("HOME_ASSISTANT_ENCRYPTION_KEY")

        if encryption_key is None:
            # Генерируем новый ключ если не передан и нет в env
            encryption_key = Fernet.generate_key().decode()

        # Убеждаемся, что ключ в правильном формате
        if isinstance(encryption_key, str):
            try:
                self._cipher = Fernet(
                    encryption_key.encode()
                    if len(encryption_key) == 44
                    else b64encode(encryption_key.encode())
                )
            except Exception:
                # Если ключ не в формате Fernet, кодируем его
                key = b64encode(encryption_key.encode()[:32].ljust(32))
                self._cipher = Fernet(key)
        else:
            self._cipher = Fernet(encryption_key)

    def encrypt(self, token: str) -> str:
        """Шифрует токен.

        Args:
            token: Токен для шифрования (строка).

        Returns:
            Зашифрованный токен в формате base64 строки.
        """
        encrypted = self._cipher.encrypt(token.encode())
        return b64encode(encrypted).decode()

    def decrypt(self, encrypted_token: str) -> str:
        """Дешифрует токен.

        Args:
            encrypted_token: Зашифрованный токен (base64 строка).

        Returns:
            Исходный токен.

        Raises:
            cryptography.fernet.InvalidToken: Если токен повреждён или неверный.
        """
        try:
            encrypted_bytes = b64decode(encrypted_token.encode())
            decrypted = self._cipher.decrypt(encrypted_bytes)
            return decrypted.decode()
        except Exception as e:
            raise ValueError(f"Ошибка расшифровки токена: {e}") from e


def generate_encryption_key() -> str:
    """Генерирует новый ключ шифрования.

    Returns:
        Новый ключ в формате base64.
    """
    return Fernet.generate_key().decode()
