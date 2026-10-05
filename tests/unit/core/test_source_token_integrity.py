"""Источники данных: токен-шифротекст не должен проходить как токен.

Продолжение Known Issue #53. В `sources.py` ошибка расшифровки глоталась
двумя способами — `except ValueError: pass` в `load_all_sources` и
`contextlib.suppress(ValueError)` в `load_source`. В обоих случаях источник
создавался с токеном-шифротекстом и выглядел рабочим, а следующая запись
шифровала шифротекст повторно. Каждый перезапуск с новым ключом добавлял
слой, и восстановить токен становилось невозможно.

Проверяется поведение, а не механизм: дефект должен приводить к заметному
отсутствию источника, а не к тихой порче данных.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

import json
import uuid
from pathlib import Path

import pytest

from core.persistence.sources import HASourcePersistence, SourceTokenError
from core.security.encryption import TokenEncryptor, generate_encryption_key


def _write_raw_source(data_dir: Path, token: str, name: str = "HA") -> uuid.UUID:
    """Записать источник напрямую в JSON, минуя шифрование.

    Нужно, чтобы положить в хранилище значение, зашифрованное чужим ключом.
    """
    source_id = uuid.uuid4()
    payload = {
        str(source_id): {
            "id": str(source_id),
            "name": name,
            "url": "http://ha.invalid:8123",
            "token": token,
            "status": "disconnected",
        }
    }
    (data_dir / "sources.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    return source_id


class TestTokenCiphertextIsNotAcceptedAsToken:
    """Токен, зашифрованный чужим ключом, не должен становиться токеном."""

    async def test_source_is_not_loaded_with_foreign_key(self, tmp_path: Path, monkeypatch):
        """Источник, зашифрованный другим ключом, не возвращается.

        Раньше возвращался — с шифротекстом в поле token.
        """
        monkeypatch.setenv("DATA_PATH", str(tmp_path))
        foreign = TokenEncryptor(encryption_key=generate_encryption_key())
        _write_raw_source(tmp_path, foreign.encrypt("REAL_TOKEN"))

        own = TokenEncryptor()
        loaded = await HASourcePersistence(data_dir=tmp_path, encryptor=own).load_all_sources()

        assert loaded == [], (
            "источник с нерасшифровываемым токеном не должен загружаться: "
            "иначе шифротекст уйдёт в запрос к HA и будет записан обратно "
            "зашифрованным ещё раз"
        )

    async def test_single_load_does_not_return_ciphertext(self, tmp_path: Path, monkeypatch):
        """load_source тоже не должен возвращать шифротекст как токен.

        Здесь ошибка глоталась через `contextlib.suppress(ValueError)`.
        """
        monkeypatch.setenv("DATA_PATH", str(tmp_path))
        foreign = TokenEncryptor(encryption_key=generate_encryption_key())
        source_id = _write_raw_source(tmp_path, foreign.encrypt("REAL_TOKEN"))

        own = TokenEncryptor()
        loaded = await HASourcePersistence(data_dir=tmp_path, encryptor=own).load_source(source_id)

        assert loaded is None, "источник с чужим ключом не должен возвращаться"

    async def test_stored_value_stays_decryptable_after_reload(self, tmp_path: Path, monkeypatch):
        """После чтения и повторной записи значение остаётся расшифровываемым.

        Главный ущерб был не в молчании, а в накоплении: каждая запись
        шифровала шифротекст ещё раз, и значение становилось нечитаемым ни
        одним ключом.

        Побайтовое равенство здесь неприменимо: Fernet использует случайный
        IV, поэтому повторное шифрование того же токена даёт другой
        шифротекст. Проверяется настоящий инвариант — значение остаётся
        расшифровываемым, то есть слоя ровно один.
        """
        monkeypatch.setenv("DATA_PATH", str(tmp_path))
        original_key = generate_encryption_key()
        correct_cipher = TokenEncryptor(encryption_key=original_key).encrypt("REAL_TOKEN")
        source_id = _write_raw_source(tmp_path, correct_cipher)

        good = TokenEncryptor(encryption_key=original_key)
        store = HASourcePersistence(data_dir=tmp_path, encryptor=good)
        loaded = await store.load_all_sources()
        assert len(loaded) == 1
        await store.save_source(loaded[0])

        stored_after = json.loads((tmp_path / "sources.json").read_text(encoding="utf-8"))
        rewritten = stored_after[str(source_id)]["token"]

        # Один слой: правильным ключом читается настоящий токен.
        assert TokenEncryptor(encryption_key=original_key).decrypt(rewritten) == "REAL_TOKEN", (
            "повторная запись зашифровала значение поверх уже зашифрованного — токен разрушен"
        )

        # И это не случайность расшифровки: повторное чтение тем же путём,
        # которым пользуется платформа, обязано дать настоящий токен.
        reread = await HASourcePersistence(
            data_dir=tmp_path, encryptor=TokenEncryptor(encryption_key=original_key)
        ).load_all_sources()
        assert [s.token for s in reread] == ["REAL_TOKEN"]


class TestTokenRoundTripWithStoredKey:
    """С файлом-ключом токен обязан переживать «перезапуск»."""

    async def test_token_survives_restart_with_key_file(self, tmp_path: Path, monkeypatch):
        """Токен, записанный одним запуском, читается другим.

        Это и есть то, чего не было: раньше ключ генерировался заново при
        каждом старте, и токен становился недоступен навсегда.
        """
        monkeypatch.delenv("HOME_ASSISTANT_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("ENCRYPTION_KEY_PATH", raising=False)
        monkeypatch.setenv("DATA_PATH", str(tmp_path))

        from core.models.ha_source import HASource

        first_run = HASourcePersistence(data_dir=tmp_path, encryptor=TokenEncryptor())
        source_id = uuid.uuid4()
        await first_run.save_source(
            HASource(id=source_id, name="HA", url="http://ha.invalid", token="REAL_TOKEN")
        )

        # «Перезапуск»: новый экземпляр хранилища и новый шифровальщик.
        second_run = HASourcePersistence(data_dir=tmp_path, encryptor=TokenEncryptor())
        loaded = await second_run.load_all_sources()

        assert len(loaded) == 1, "источник обязан пережить перезапуск"
        assert loaded[0].token == "REAL_TOKEN"

    async def test_error_names_the_recovery_path(self, tmp_path: Path, monkeypatch):
        """Сообщение об ошибке говорит, что делать оператору.

        Ошибка без указания пути восстановления приводит к тому, что её
        чинят выстрелом вслепую — обычно переустановкой платформы.
        """
        monkeypatch.setenv("DATA_PATH", str(tmp_path))
        foreign = TokenEncryptor(encryption_key=generate_encryption_key())
        _write_raw_source(tmp_path, foreign.encrypt("REAL_TOKEN"))

        store = HASourcePersistence(data_dir=tmp_path, encryptor=TokenEncryptor())

        with pytest.raises(SourceTokenError) as exc_info:
            store._decrypt_token(foreign.encrypt("x"), "Мой HA")

        message = str(exc_info.value)
        assert "Мой HA" in message, "в ошибке должно быть имя источника"
        assert "HOME_ASSISTANT_ENCRYPTION_KEY" in message, (
            "в ошибке должен называться способ восстановления ключа"
        )


class TestWithoutEncryptor:
    """Без настроенного шифрования значение не трогается."""

    async def test_token_returned_as_is_when_encryption_disabled(self, tmp_path: Path, monkeypatch):
        """При encryptor=None хранимое значение возвращается как есть.

        Осознанный отказ от шифрования — допустимый режим, но он должен быть
        явным, а не следствием исключения при импорте.
        """
        monkeypatch.setenv("DATA_PATH", str(tmp_path))
        _write_raw_source(tmp_path, "PLAIN_TOKEN")

        loaded = await HASourcePersistence(data_dir=tmp_path, encryptor=None).load_all_sources()

        assert len(loaded) == 1
        assert loaded[0].token == "PLAIN_TOKEN"
