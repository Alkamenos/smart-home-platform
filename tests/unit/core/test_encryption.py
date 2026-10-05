"""Тесты шифрования токенов (спека 009, FR-006, FR-007).

Четыре теста шифрования жили в `tests/security/verify_security.py`, который
pytest **не собирает**: имя файла не начинается с `test_`, а тесты находятся
под `if __name__ == "__main__"`. Ни один из них не выполнялся ни разу.

Перенос сюда закрывает FR-006. Дополнительно покрыты ветви, оставшиеся
непроверенными: `__init__` с ключом из окружения, ветвь «ключ не в формате
Fernet» с запасным кодированием и `generate_encryption_key`.

Герметичность: ключ, взятый из `HOME_ASSISTANT_ENCRYPTION_KEY`, сделал бы
результат зависящим от машины, поэтому переменная окружения изолируется
фикстурой `clean_encryption_env` — иначе тест прошёл бы на одной машине и
упал бы на другой.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from core.security.encryption import (
    EncryptionKeyError,
    TokenEncryptor,
    generate_encryption_key,
)


@pytest.fixture(autouse=True)
def clean_encryption_env(monkeypatch):
    """Убирает ключ шифрования из окружения на время теста.

    Args:
        monkeypatch: Фикстура подмены окружения.

    Returns:
        None.
    """
    monkeypatch.delenv("HOME_ASSISTANT_ENCRYPTION_KEY", raising=False)


class TestTokenRoundTrip:
    """Шифрование и расшифровка."""

    def test_encrypt_decrypt_returns_original_token(self):
        """Токен после round-trip совпадает с исходным."""
        encryptor = TokenEncryptor()
        original = "test_token_12345"

        encrypted = encryptor.encrypt(original)
        assert encrypted != original, "зашифрованный токен обязан отличаться от исходного"
        assert encryptor.decrypt(encrypted) == original

    def test_encryption_output_is_not_plaintext(self):
        """Исходный токен не читается в зашифрованном виде."""
        encrypted = TokenEncryptor().encrypt("super_secret_token")

        assert "super_secret_token" not in encrypted
        assert encrypted  # непустая строка

    def test_repeated_encryption_differs(self):
        """Два шифрования одного токена дают разный вывод (случайный IV)."""
        encryptor = TokenEncryptor()
        token = "test_token_12345"

        first = encryptor.encrypt(token)
        second = encryptor.encrypt(token)

        assert first != second, "Fernet обязан использовать случайный IV"
        assert encryptor.decrypt(first) == token
        assert encryptor.decrypt(second) == token

    def test_empty_token_round_trip(self):
        """Пустой токен шифруется и расшифровывается."""
        encryptor = TokenEncryptor()

        assert encryptor.decrypt(encryptor.encrypt("")) == ""

    def test_long_token_round_trip(self):
        """Длинный токен не обрезается."""
        encryptor = TokenEncryptor()
        token = "x" * 4096

        assert encryptor.decrypt(encryptor.encrypt(token)) == token

    def test_unicode_token_round_trip(self):
        """Не-ASCII токен не ломает кодирование."""
        encryptor = TokenEncryptor()
        token = "токен-ключ-🔑-секрет"

        assert encryptor.decrypt(encryptor.encrypt(token)) == token


class TestDecryptFailures:
    """Отказы дешифрования."""

    def test_invalid_token_raises_value_error(self):
        """Негодный ввод даёт ValueError, а не молчаливую порчу."""
        with pytest.raises(ValueError, match="Ошибка расшифровки токена"):
            TokenEncryptor().decrypt("invalid_encrypted_token")

    def test_token_encrypted_by_other_key_is_rejected(self):
        """Токен, зашифрованный другим ключом, не расшифровывается."""
        other = TokenEncryptor(encryption_key=generate_encryption_key())
        foreign = other.encrypt("test_token_12345")

        with pytest.raises(ValueError):
            TokenEncryptor(encryption_key=generate_encryption_key()).decrypt(foreign)

    def test_error_names_the_cause(self):
        """Сообщение называет причину, а не молчит."""
        with pytest.raises(ValueError) as excinfo:
            TokenEncryptor().decrypt("не-base64-вовсе")

        assert str(excinfo.value).startswith("Ошибка расшифровки токена:")
        assert excinfo.value.__cause__ is not None, "причина должна быть сохранена в __cause__"


class TestKeySources:
    """Источники ключа шифрования."""

    def test_key_is_taken_from_environment(self, monkeypatch):
        """Ключ из переменной окружения используется — и данные им читаются."""
        key = generate_encryption_key()
        monkeypatch.setenv("HOME_ASSISTANT_ENCRYPTION_KEY", key)

        encryptor = TokenEncryptor()
        assert encryptor.decrypt(encryptor.encrypt("test_token_12345")) == "test_token_12345"

        # Другой экземпляр с тем же ключом обязан прочитать те же данные:
        # иначе ключ из окружения игнорировался бы.
        assert TokenEncryptor().decrypt(encryptor.encrypt("test_token_12345")) == "test_token_12345"

    def test_explicit_key_wins_over_environment(self, monkeypatch):
        """Явно переданный ключ имеет приоритет над окружением."""
        monkeypatch.setenv("HOME_ASSISTANT_ENCRYPTION_KEY", generate_encryption_key())
        explicit = TokenEncryptor(encryption_key=generate_encryption_key())

        assert explicit.decrypt(explicit.encrypt("test_token_12345")) == "test_token_12345"
        with pytest.raises(ValueError):
            TokenEncryptor().decrypt(explicit.encrypt("test_token_12345"))

    def test_without_key_a_stored_key_file_is_created(self, tmp_path, monkeypatch):
        """Без ключа и переменной создаётся файл ключа, и он переживает
        «перезапуск».

        Раньше здесь стояло `test_generated_key_differs_between_instances`:
        тест закреплял дефект как норму, утверждая, что каждый экземпляр
        получает СВОЙ ключ. Из-за этого сохранённые токены нельзя было
        расшифровать после перезапуска, а `sources.py` при неудачной
        расшифровке молча подставлял шифротекст вместо токена (Known Issue
        #47, #53).

        Теперь ключ берётся из файла в каталоге данных, поэтому два
        экземпляра — это два «запуска» с одним и тем же ключом.
        """
        monkeypatch.delenv("HOME_ASSISTANT_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("ENCRYPTION_KEY_PATH", raising=False)
        monkeypatch.setenv("DATA_PATH", str(tmp_path))

        first = TokenEncryptor()
        key_file = tmp_path / "encryption.key"

        assert key_file.is_file(), "файл ключа должен быть создан"
        # Второй экземпляр — это «перезапуск»: он обязан прочитать данные,
        # записанные первым.
        second = TokenEncryptor()
        assert second.decrypt(first.encrypt("test_token_12345")) == "test_token_12345"

    def test_explicit_path_beats_environment_variable(self, tmp_path, monkeypatch):
        """Путь из ENCRYPTION_KEY_PATH приоритетнее пути по умолчанию."""
        monkeypatch.delenv("HOME_ASSISTANT_ENCRYPTION_KEY", raising=False)
        monkeypatch.setenv("DATA_PATH", str(tmp_path / "data"))
        elsewhere = tmp_path / "secrets"
        monkeypatch.setenv("ENCRYPTION_KEY_PATH", str(elsewhere / "key"))

        TokenEncryptor()

        assert (elsewhere / "key").is_file()
        assert not (tmp_path / "data" / "encryption.key").exists()

    def test_existing_key_file_is_not_overwritten(self, tmp_path, monkeypatch):
        """Существующий ключ читается, а не заменяется новым.

        Если бы файл перезаписывался, каждый запуск получал бы новый ключ и
        все ранее зашифрованные токены становились бы невосстановимыми.
        """
        monkeypatch.delenv("HOME_ASSISTANT_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("ENCRYPTION_KEY_PATH", raising=False)
        monkeypatch.setenv("DATA_PATH", str(tmp_path))
        key_file = tmp_path / "encryption.key"
        existing = generate_encryption_key()
        key_file.write_text(existing, encoding="utf-8")

        encryptor = TokenEncryptor()

        assert key_file.read_text(encoding="utf-8").strip() == existing
        # Ключ из файла настоящий: им зашифровано значение читается обратно.
        expected = TokenEncryptor(encryption_key=existing)
        assert encryptor.decrypt(expected.encrypt("test_token_12345")) == "test_token_12345"

    def test_key_file_is_not_world_readable(self, tmp_path, monkeypatch):
        """Файл ключа доступен только владельцу.

        Иначе токены читаются любым пользователем хоста, и шифрование теряет
        смысл.
        """
        monkeypatch.delenv("HOME_ASSISTANT_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("ENCRYPTION_KEY_PATH", raising=False)
        monkeypatch.setenv("DATA_PATH", str(tmp_path))

        TokenEncryptor()

        mode = (tmp_path / "encryption.key").stat().st_mode & 0o777
        assert mode == 0o600, f"ожидались права 600, получено {mode:o}"

    def test_empty_key_file_raises_instead_of_regenerating(self, tmp_path, monkeypatch):
        """Пустой файл ключа — ошибка, а не повод сгенерировать новый ключ.

        Новый ключ здесь означал бы, что платформа продолжит работу и
        зашифрует уже сохранённые значения повторно, то есть токены будут
        разрушены безвозвратно.
        """
        monkeypatch.delenv("HOME_ASSISTANT_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("ENCRYPTION_KEY_PATH", raising=False)
        monkeypatch.setenv("DATA_PATH", str(tmp_path))
        key_file = tmp_path / "encryption.key"
        key_file.write_text("   \n", encoding="utf-8")

        with pytest.raises(EncryptionKeyError):
            TokenEncryptor()

        # Файл не перезаписан: пустой остался пустым.
        assert not key_file.read_text(encoding="utf-8").strip()

    def test_short_arbitrary_key_is_accepted_via_fallback(self):
        """Ключ произвольной длины приводится к корректному через запасное кодирование.

        Ветвь `except` в `__init__` существует именно для этого: произвольная
        строка не является ключом Fernet, и без запасного пути конструктор
        падал бы.
        """
        encryptor = TokenEncryptor(encryption_key="short-secret-key")

        assert encryptor.decrypt(encryptor.encrypt("test_token_12345")) == "test_token_12345"

    def test_long_arbitrary_key_is_accepted_via_fallback(self):
        """Ключ длиннее 32 байт обрезается до допустимого размера."""
        encryptor = TokenEncryptor(encryption_key="k" * 100)

        assert encryptor.decrypt(encryptor.encrypt("test_token_12345")) == "test_token_12345"

    def test_bytes_key_is_accepted(self):
        """Ключ типа bytes передаётся Fernet напрямую."""
        encryptor = TokenEncryptor(encryption_key=Fernet.generate_key())

        assert encryptor.decrypt(encryptor.encrypt("test_token_12345")) == "test_token_12345"


class TestKeyGeneration:
    """Генерация ключа."""

    def test_generated_key_is_valid_fernet_key(self):
        """Сгенерированный ключ принимается Fernet без преобразований."""
        key = generate_encryption_key()

        assert Fernet(key.encode())

    def test_generated_keys_differ(self):
        """Ключи не повторяются."""
        assert generate_encryption_key() != generate_encryption_key()

    def test_generated_key_length_is_fernet_compatible(self):
        """Длина ключа совпадает с ожидаемой для Fernet (44 символа)."""
        assert len(generate_encryption_key()) == 44

    def test_generated_key_works_with_encryptor(self):
        """Сгенерированный ключ пригоден для шифровальщика без преобразований."""
        key = generate_encryption_key()
        encryptor = TokenEncryptor(encryption_key=key)

        assert encryptor.decrypt(encryptor.encrypt("test_token_12345")) == "test_token_12345"
