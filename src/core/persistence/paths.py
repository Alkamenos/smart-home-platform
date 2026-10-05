"""Разрешение пути каталога данных платформы.

Единственный источник истины для пути, куда пишутся хранилища. Введён
после того, как `DATA_PATH` оказался непрочитанным: переменная была
объявлена в `deploy/docker/Dockerfile` и `docker-compose.prod.yml`, но не
читалась ни одной строкой Python, поэтому данные писались в `/app/data`
внутри слоя контейнера, а монтировался том в `/data/behavioral_platform`.
Итог: любое пересоздание контейнера уничтожало конфигурацию установки
(Known Issue #44, доказано запуском контейнера).

## Почему разрешение в момент вызова, а не на импорте

`DATA_PATH` читается при каждом вызове :func:`resolve_data_dir`, а не один
раз при импорте модуля. Иначе подмена переменной в тесте (например через
`monkeypatch.setenv`) не имела бы эффекта: значение уже было бы зафиксировано
в константе на уровне модуля.
"""

from __future__ import annotations

import os
from pathlib import Path


#: Имя переменной окружения с путём к данным.
DATA_PATH_ENV = "DATA_PATH"

#: Значение по умолчанию, когда переменная не задана. Совпадает с прежним
#: поведением всех хранилищ: относительный путь от текущего каталога.
DEFAULT_DATA_DIR = "data"


def resolve_data_dir(explicit: Path | str | None = None) -> Path:
    """Вернуть каталог данных.

    Args:
        explicit: Явно заданный путь. Если передан, он имеет приоритет над
            переменной окружения — так сохраняется возможность указать
            каталог вручную (тесты, утилиты, миграции).

    Returns:
        Путь к каталогу данных. Если ничего не задано, берётся ``DATA_PATH``
        из окружения, иначе ``DEFAULT_DATA_DIR``.
    """
    if explicit is not None:
        return Path(explicit)

    from_env = os.environ.get(DATA_PATH_ENV)
    if from_env:
        return Path(from_env)

    return Path(DEFAULT_DATA_DIR)


def default_data_dir() -> Path:
    """Каталог данных без явного аргумента — для мест, где путь не передаётся.

    Returns:
        То же, что :func:`resolve_data_dir` без аргумента.
    """
    return resolve_data_dir(None)
