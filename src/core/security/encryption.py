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

Пустое значение аргумента или переменной — это «ключ не задан», а не ключ из
пустой строки. Иначе строка ``HOME_ASSISTANT_ENCRYPTION_KEY=`` без значения
(как в образце ``.env``) отменяла бы файл ключа: ключ выводился бы из пустоты,
файл не создавался, а токены шифровались ключом, который воспроизводит кто
угодно (боевое развёртывание 2026-10-17).

Если файла нет, он создаётся один раз и сохраняется в томе данных, то есть
переживает перезапуск и пересоздание контейнера. Раньше ключ генерировался в
памяти при каждом старте, и это приводило к разрушению токенов: см. Known
Issue #47 и #53.

Если файл существует, но прочитать его не удалось, он пуст или не содержит
ключа Fernet, ключ НЕ генерируется заново и НЕ выводится из содержимого — иначе
платформа продолжила бы работу с другим ключом и зашифровала бы старые значения
повторно. В этом случае поднимается ``EncryptionKeyError``.

Ключ, заданный вручную (аргументом или переменной) и не являющийся ключом
Fernet, принимается как пароль: из него выводится ключ, но подстановка
называется предупреждением в журнале — молчаливая замена скрывала бы, каким
ключом на самом деле зашифрованы токены.
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
#: Переменная окружения с самим ключом шифрования.
KEY_ENV = "HOME_ASSISTANT_ENCRYPTION_KEY"
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
        EncryptionKeyError: Файл существует, но пуст, не читается или не содержит
            ключа Fernet. Ключ в этом случае НЕ генерируется заново и НЕ выводится
            из содержимого.
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

    _require_fernet_key(key, path)
    return key


def _require_fernet_key(key: str, path: Path) -> None:
    """Убедиться, что содержимое файла ключа — настоящий ключ Fernet.

    Проверка нужна, чтобы «ключ не разобран» не превратился в другой ключ: файл
    создаёт сама платформа и всегда настоящим ключом Fernet, поэтому постороннее
    содержимое означает потерю ключа, а не повод завести новый.

    Args:
        key: Прочитанное из файла значение.
        path: Путь к файлу — называется в сообщении об ошибке.

    Raises:
        EncryptionKeyError: Значение не является ключом Fernet.
    """
    try:
        Fernet(key.encode())
    except Exception as exc:
        detail = str(exc) or type(exc).__name__
        raise EncryptionKeyError(
            f"Файл ключа {path} не является ключом Fernet ({detail}). Ключ НЕ "
            f"выводится из содержимого — иначе сохранённые токены стали бы "
            f"нечитаемыми молча. Восстановите файл из резервной копии или создайте "
            f'новый: python -c "from core.security.encryption import '
            f'generate_encryption_key; print(generate_encryption_key())"'
        ) from exc


class TokenEncryptor:
    """Шифровальщик для токенов и чувствительных данных.

    Использует симметричное шифрование Fernet для защиты данных.
    """

    def __init__(self, encryption_key: str | bytes | None = None) -> None:
        """Инициализация шифровальщика.

        Args:
            encryption_key: Ключ шифрования — ключ Fernet, произвольная
                строка-пароль или ``bytes``. Если ``None`` или пустая строка,
                ключ берётся из переменной окружения
                ``HOME_ASSISTANT_ENCRYPTION_KEY``, а при её отсутствии — из файла
                ключа, который создаётся при первом обращении и сохраняется в
                томе данных.

        Raises:
            EncryptionKeyError: Файл ключа существует, но пуст, не читается или
                не является ключом Fernet.
        """
        # Пустое значение — это «ключ не задан», а не ключ из пустой строки.
        # Иначе `HOME_ASSISTANT_ENCRYPTION_KEY=` из образца `.env` отменяло бы
        # файл ключа: ключ выводился бы из пустоты, файл не создавался, а токены
        # шифровались бы ключом, который воспроизводит кто угодно (2026-10-17).
        if isinstance(encryption_key, str) and not encryption_key.strip():
            encryption_key = None

        source = "аргумент"
        if encryption_key is None:
            source = f"переменная {KEY_ENV}"
            encryption_key = os.environ.get(KEY_ENV)
            if isinstance(encryption_key, str) and not encryption_key.strip():
                encryption_key = None

        if encryption_key is None:
            source = "файл ключа"
            key_file = resolve_key_file()
            encryption_key = load_or_create_key_file(key_file)
            logger.info("Ключ шифрования токенов взят из файла %s", key_file)

        self._cipher = self._build_cipher(encryption_key, source)

    @staticmethod
    def _build_cipher(encryption_key: str | bytes, source: str) -> Fernet:
        """Собрать шифровальщик из ключа.

        Ключ Fernet берётся как есть; произвольная строка принимается как пароль,
        из которого ключ выводится. Подстановка не молчит: иначе оператор не узнал
        бы, что шифрует не тем ключом, который задал (пункт К-8 аудита 2026-10-16).

        Args:
            encryption_key: Ключ Fernet, строка-пароль или ``bytes``.
            source: Название источника ключа — попадает в предупреждение.

        Returns:
            Готовый шифровальщик.
        """
        if not isinstance(encryption_key, str):
            return Fernet(encryption_key)

        try:
            return Fernet(
                encryption_key.encode()
                if len(encryption_key) == 44
                else b64encode(encryption_key.encode())
            )
        except Exception:
            logger.warning(
                "Ключ шифрования из источника «%s» не в формате Fernet — "
                "используется ключ, выведенный из переданного значения. Для дома "
                "берите ключ, созданный generate_encryption_key: иначе сохранённые "
                "токены читаются не тем ключом, который задан.",
                source,
            )
            return Fernet(b64encode(encryption_key.encode()[:32].ljust(32)))

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
