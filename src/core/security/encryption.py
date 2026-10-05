"""
Модуль для шифрования и дешифрования чувствительных данных.

Используется для защиты токенов Home Assistant и других конфиденциальных данных.

Хранение ключа
--------------
Ключ берётся из первого доступного источника:

1. явный аргумент конструктора;
2. переменная окружения ``HOME_ASSISTANT_ENCRYPTION_KEY``;
3. файл ключа — путь из ``ENCRYPTION_KEY_PATH``, иначе
   ``<DATA_PATH>/encryption.key``.

Если файла нет, он создаётся один раз и сохраняется в томе данных, то есть
переживает перезапуск и пересоздание контейнера. Раньше ключ генерировался в
памяти при каждом старте, и это приводило к разрушению токенов: см. Known
Issue #47 и #53.

Если файл существует, но прочитать его не удалось или он пуст, ключ НЕ
генерируется заново — иначе платформа продолжила бы работу с новым ключом и
зашифровала бы старые значения повторно. В этом случае поднимается
``EncryptionKeyError``.
"""

import logging
import os
from base64 import b64decode, b64encode
from pathlib import Path

from cryptography.fernet import Fernet

from core.persistence.atomic import atomic_write_text
from core.persistence.paths import resolve_data_dir


logger = logging.getLogger(__name__)

#: Переменная окружения с путём к файлу ключа.
KEY_FILE_ENV = "ENCRYPTION_KEY_PATH"
#: Имя файла ключа внутри каталога данных.
DEFAULT_KEY_FILENAME = "encryption.key"
#: Права на файл ключа: читать и писать может только владелец.
KEY_FILE_MODE = 0o600


class EncryptionKeyError(RuntimeError):
    """Файл ключа существует, но использовать его нельзя.

    Отдельно от ``ValueError`` при расшифровке: этот случай требует действий
    оператора (восстановить ключ), а не означает, что повреждён конкретный
    токен.
    """


def resolve_key_file(explicit_path: Path | str | None = None) -> Path:
    """Определить путь к файлу ключа.

    Args:
        explicit_path: Явно заданный путь. Приоритетнее переменной окружения.

    Returns:
        Путь к файлу ключа.
    """
    if explicit_path:
        return Path(explicit_path)

    from_env = os.environ.get(KEY_FILE_ENV)
    if from_env:
        return Path(from_env)

    return resolve_data_dir() / DEFAULT_KEY_FILENAME


def load_or_create_key_file(path: Path) -> str:
    """Прочитать ключ из файла, при необходимости создав его один раз.

    Создание файла логируется предупреждением намеренно: оператор должен знать,
    что ключ появился в томе данных и что этот том нужно включать в резервные
    копии. Потеря ключа означает невозможность расшифровать уже сохранённые
    токены.

    Args:
        path: Путь к файлу ключа.

    Returns:
        Ключ в формате Fernet.

    Raises:
        EncryptionKeyError: Файл существует, но пуст или не читается. Ключ в
            этом случае НЕ генерируется заново.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        key = Fernet.generate_key().decode()
        atomic_write_text(path, f"{key}\n", mode=KEY_FILE_MODE)
        logger.warning(
            "Файл ключа шифрования не найден, создан новый: %s. "
            "Храните его в резервных копиях вместе с данными: без этого файла "
            "сохранённые токены расшифровать невозможно.",
            path,
        )
        return key
    except OSError as exc:
        raise EncryptionKeyError(
            f"Не удалось прочитать файл ключа {path}: {exc}. Ключ НЕ генерируется "
            f"заново — иначе сохранённые токены станут невосстановимыми. "
            f"Восстановите файл из резервной копии или укажите {KEY_FILE_ENV}."
        ) from exc

    key = raw.strip()
    if not key:
        raise EncryptionKeyError(
            f"Файл ключа {path} пуст. Ключ НЕ генерируется заново: это привело бы "
            f"к повторному шифрованию уже сохранённых токенов. Восстановите ключ "
            f"из резервной копии."
        )

    return key


class TokenEncryptor:
    """Шифровальщик для токенов и чувствительных данных.

    Использует симметричное шифрование Fernet для защиты данных.
    """

    def __init__(self, encryption_key: str | None = None) -> None:
        """Инициализация шифровальщика.

        Args:
            encryption_key: Ключ шифрования. Если None, берётся из переменной
                окружения ``HOME_ASSISTANT_ENCRYPTION_KEY``, а при её отсутствии
                — из файла ключа, который создаётся при первом обращении и
                сохраняется в томе данных.

        Raises:
            EncryptionKeyError: Файл ключа существует, но пуст или не читается.
        """
        if encryption_key is None:
            encryption_key = os.environ.get("HOME_ASSISTANT_ENCRYPTION_KEY")

        if encryption_key is None:
            key_file = resolve_key_file()
            encryption_key = load_or_create_key_file(key_file)
            logger.info("Ключ шифрования токенов взят из файла %s", key_file)

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
            # Имя класса обязательно: у `InvalidToken` пустое сообщение, и без
            # него в логе остаётся «Ошибка расшифровки токена: .» — диагностика
            # обрывается на полуслове и нечем отличить «не тот ключ» от
            # «значение повреждено».
            detail = str(e) or type(e).__name__
            raise ValueError(f"Ошибка расшифровки токена: {detail}") from e


def generate_encryption_key() -> str:
    """Генерирует новый ключ шифрования.

    Returns:
        Новый ключ в формате base64.
    """
    return Fernet.generate_key().decode()
