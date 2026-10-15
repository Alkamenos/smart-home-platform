"""
Слой персистентности для источников Home Assistant.

Обеспечивает сохранение и загрузку конфигурации источников HA из файловой системы.
"""

import json
import logging
from pathlib import Path
from uuid import UUID

from core.models.ha_source import HASource
from core.persistence.atomic import (
    PersistenceCorruptedError,
    atomic_write_json,
    preserve_corrupt_file,
)
from core.persistence.paths import resolve_data_dir
from core.security.encryption import TokenEncryptor


logger = logging.getLogger(__name__)


class SourceTokenError(Exception):
    """Сохранённый токен источника не расшифровывается текущим ключом.

    Отдельный тип, чтобы вызывающий мог отличить «ключ не тот» от «запись
    повреждена» и не записать шифротекст поверх настоящего токена.
    """


class HASourcePersistence:
    """Управляет сохранением и загрузкой источников Home Assistant."""

    def __init__(
        self, data_dir: Path | str | None = None, encryptor: TokenEncryptor | None = None
    ) -> None:
        """Инициализация персистентности.

        Args:
            data_dir: Директория данных. По умолчанию — ``DATA_PATH`` из
                окружения, иначе ``data`` (см. ``paths.resolve_data_dir``).
            encryptor: Шифровальщик для токенов (опционально)
        """
        self.data_dir = resolve_data_dir(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.sources_file = self.data_dir / "sources.json"
        self.encryptor = encryptor

    async def save_source(self, source: HASource) -> None:
        """Сохраняет источник в файл.

        Args:
            source: Источник для сохранения
        """
        try:
            # Получаем существующие источники
            sources_data = await self._load_sources_data()

            # Создаем копию для сохранения
            source_dict = source.model_dump(mode="json")

            # Шифруем токен
            if self.encryptor:
                source_dict["token"] = self.encryptor.encrypt(source.token)

            sources_data[str(source.id)] = source_dict

            # Сохраняем в файл
            atomic_write_json(self.sources_file, sources_data)

            logger.info(f"Источник {source.id} сохранен в {self.sources_file}")

        except Exception as e:
            logger.error(f"Ошибка сохранения источника: {e}")
            raise

    async def load_source(self, source_id: UUID) -> HASource | None:
        """Загружает источник по ID.

        Args:
            source_id: Идентификатор источника

        Returns:
            HASource если найден, None иначе
        """
        try:
            sources_data = await self._load_sources_data()
            source_data = sources_data.get(str(source_id))

            if not source_data:
                return None

            # Дешифруем токен. Раньше здесь стояло
            # `with contextlib.suppress(ValueError)`, и при неудачной
            # расшифровке объект возвращался с токеном-шифротекстом — та же
            # порча данных, что и в load_all_sources (Known Issue #53).
            source_data = dict(source_data)
            source_data["token"] = self._decrypt_token(
                source_data.get("token", ""), source_data.get("name", "?")
            )

            return HASource(**source_data)

        except Exception as e:
            logger.error(f"Ошибка загрузки источника {source_id}: {e}")
            return None

    async def load_all_sources(self) -> list[HASource]:
        """Загружает все источники.

        Returns:
            Список всех источников. Источник, токен которого не расшифровывается,
            НЕ возвращается: см. ``_decrypt_token``.
        """
        try:
            sources_data = await self._load_sources_data()
            sources = []

            for source_data in sources_data.values():
                try:
                    source_data = source_data.copy()
                    source_data["token"] = self._decrypt_token(
                        source_data.get("token", ""), source_data.get("name", "?")
                    )

                    source = HASource(**source_data)
                    sources.append(source)
                except Exception as e:
                    logger.warning(f"Ошибка загрузки источника: {e}")
                    continue

            logger.info(f"Загружено {len(sources)} источников")
            return sources

        except PersistenceCorruptedError:
            # Испорченный файл источников — не «источников нет»: иначе поломка
            # выглядит как пустая установка (аудит 2026-10-16, К-6).
            raise
        except Exception as e:
            logger.error(f"Ошибка загрузки источников: {e}")
            return []

    def _decrypt_token(self, stored_token: str, source_name: str) -> str:
        """Расшифровать сохранённый токен.

        Раньше здесь стояло ``except ValueError: pass``, и это молча портило
        данные: источник создавался с токеном-шифротекстом, выглядел рабочим,
        а следующая запись шифровала шифротекст ещё раз. Каждый перезапуск с
        новым ключом добавлял слой, и восстановить токен становилось невозможно
        (Known Issue #53).

        Args:
            stored_token: Значение из хранилища.
            source_name: Имя источника для сообщения об ошибке.

        Returns:
            Расшифрованный токен. Если шифрование не настроено, значение
            возвращается как есть.

        Raises:
            SourceTokenError: Токен не расшифровывается текущим ключом.
        """
        if not self.encryptor or not stored_token:
            return stored_token

        try:
            return self.encryptor.decrypt(stored_token)
        except ValueError as exc:
            raise SourceTokenError(
                f"Токен источника «{source_name}» не расшифровывается текущим "
                f"ключом: {exc}. Источник НЕ загружен, чтобы не записать "
                f"шифротекст поверх настоящего токена. Восстановите ключ "
                f"шифрования (файл в томе данных или переменная "
                f"HOME_ASSISTANT_ENCRYPTION_KEY) либо введите токен заново."
            ) from exc

    async def delete_source(self, source_id: UUID) -> bool:
        """Удаляет источник.

        Args:
            source_id: Идентификатор источника для удаления

        Returns:
            True если удален успешно
        """
        try:
            sources_data = await self._load_sources_data()

            if str(source_id) in sources_data:
                del sources_data[str(source_id)]

                atomic_write_json(self.sources_file, sources_data)

                logger.info(f"Источник {source_id} удален")
                return True

            return False

        except Exception as e:
            logger.error(f"Ошибка удаления источника: {e}")
            return False

    async def _load_sources_data(self) -> dict:
        """Загружает данные о всех источниках из файла.

        Returns:
            Словарь с данными источников
        """
        if not self.sources_file.exists():
            return {}

        try:
            with open(self.sources_file) as f:
                return json.load(f)
        except json.JSONDecodeError as exc:
            # Молчаливый возврат пустого словаря приводил к тому, что
            # следующая запись перезаписывала файл пустым состоянием —
            # источники и их токены исчезали бессрочно (Блокер 2).
            backup = preserve_corrupt_file(self.sources_file)
            raise PersistenceCorruptedError(
                f"Файл {self.sources_file} повреждён ({exc}); копия: {backup}. "
                f"Данные не перезаписываются — восстановите их вручную."
            ) from exc
