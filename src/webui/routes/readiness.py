"""Проверки готовности платформы.

K6 продакшен-плана. `/health` отвечает константой и для диагностики бесполезен:
Docker считает контейнер здоровым при мёртвом Home Assistant и нечитаемом
каталоге данных.

Почему проверки живут здесь, а не в маршруте
--------------------------------------------
Каждая проверка вызывается и из HTTP-маршрута `/ready`, и напрямую из тестов.
Тест, который проверяет честность самой проверки, должен вызывать её без
HTTP-обвязки — иначе подмена «всегда хорошо» осталась бы незаметной.

Почему `/health` не меняется
----------------------------
Контракт спеки 003 (`contracts/operational-contracts.md` §1) требует, чтобы
`/health` оставался проверкой жизненности и не отдавал не-200 как «not ready».
Если начать отдавать 503 при недоступном Home Assistant, healthcheck в compose
убьёт контейнер, перезапустит, тот снова увидит недоступный HA — и получится
рестарт-цикл, в котором перезапуск ничего не исправляет.
"""

from __future__ import annotations

import contextlib
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.persistence.paths import resolve_data_dir
from core.security.encryption import DEFAULT_KEY_FILENAME


#: Порог «свежести» снимка сторожа: два интервала сторожа с запасом.
WATCHDOG_STALE_SEC = 180.0


def _base_data_dir(explicit: Path | str | None = None) -> Path:
    """Каталог данных: явно заданный или разрешённый через DATA_PATH.

    Args:
        explicit: Явно заданный путь.

    Returns:
        Путь к каталогу данных.
    """
    if explicit:
        return Path(explicit)
    return resolve_data_dir()


def check_data_dir(path: Path | str | None = None) -> dict[str, Any]:
    """Проверить, что в каталог данных можно писать и он читается.

    Проверка создаёт временный файл и удаляет его: каталог может существовать и
    при этом оказаться доступным только на чтение — это выясняется лишь записью.
    Проверка не оставляет следов, иначе сам мониторинг засорял бы данные.

    Args:
        path: Каталог для проверки. По умолчанию берётся из ``DATA_PATH``.

    Returns:
        Словарь с ключом ``ok``, ``path`` и ``detail``.
    """
    target = _base_data_dir(path)
    result: dict[str, Any] = {"ok": False, "path": str(target)}

    try:
        target.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        result["detail"] = f"каталог недоступен для создания: {exc}"
        return result

    probe = target / f".readiness-probe-{os.getpid()}"
    try:
        with open(probe, "w", encoding="utf-8") as handle:
            handle.write("ok")
            handle.flush()
            os.fsync(handle.fileno())
        probe.unlink()
        result["ok"] = True
        result["detail"] = "каталог доступен для чтения и записи"
    except OSError as exc:
        result["detail"] = f"запись не удалась: {exc}"
        return result
    finally:
        if probe.exists():
            with contextlib.suppress(OSError):
                probe.unlink()

    return result


def check_encryption_key(path: Path | str | None = None) -> dict[str, Any]:
    """Проверить наличие файла ключа шифрования токенов.

    Отсутствие ключа не ломает работу платформы, но означает, что ранее
    сохранённые токены Home Assistant расшифровать нельзя. Об этом полезно
    узнать из проверки готовности, а не из сообщения в логе при первом
    обращении к токену.

    Args:
        path: Каталог данных. По умолчанию берётся из ``DATA_PATH``.

    Returns:
        Словарь с ключом ``ok``, ``path`` и ``detail``.
    """
    key_path = _base_data_dir(path) / DEFAULT_KEY_FILENAME
    result: dict[str, Any] = {"ok": False, "path": str(key_path)}

    try:
        key = key_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        result["detail"] = f"файл ключа не прочитан: {exc}"
        return result

    if not key:
        result["detail"] = (
            "файл ключа пуст: ключ не генерируется заново намеренно, "
            "восстановите его из резервной копии"
        )
        return result

    result["ok"] = True
    result["detail"] = "ключ шифрования на месте"
    return result


def check_home_assistant(adapter: Any) -> dict[str, Any]:
    """Проверить связь адаптера с Home Assistant.

    Args:
        adapter: Адаптер Home Assistant либо ``None``.

    Returns:
        Словарь с ключом ``ok`` и ``detail``.
    """
    if adapter is None:
        return {"ok": False, "detail": "адаптер Home Assistant не создан"}

    try:
        connected = bool(adapter.is_connected)
    except Exception as exc:  # noqa: BLE001 - причина попадает в отчёт
        return {"ok": False, "detail": f"состояние адаптера неизвестно: {exc}"}

    if connected:
        return {"ok": True, "detail": "соединение установлено"}
    return {"ok": False, "detail": "нет соединения с Home Assistant"}


def check_watchdog(container: Any, stale_sec: float = WATCHDOG_STALE_SEC) -> dict[str, Any]:
    """Проверить, что сторож публикует свежие снимки.

    Сторож — единственная часть платформы, которая должна работать постоянно:
    он замечает зависшие автоматы. Если снимки перестали обновляться, зависание
    никто не заметит, поэтому отсутствие свежего снимка — отказ готовности.

    Снимок содержит ещё и признак ``failed``: проверка, которая не смогла
    прочитать состояния, отличается от успешной, и обе должны быть видны.

    Args:
        container: Контейнер платформы либо ``None``.
        stale_sec: Порог устаревания снимка в секундах.

    Returns:
        Словарь с ключом ``ok``, ``age_sec``, ``problems`` и ``detail``.
    """
    if container is None:
        return {"ok": False, "detail": "контейнер платформы недоступен"}

    watchdog = getattr(container, "_watchdog", None)
    if watchdog is None:
        return {"ok": False, "detail": "сторож не создан"}

    snapshot = getattr(watchdog, "_last_snapshot", None)
    if snapshot is None:
        return {"ok": False, "detail": "сторож ещё не опубликовал ни одного снимка"}

    if getattr(snapshot, "failed", False):
        return {
            "ok": False,
            "detail": "последняя проверка сторожа завершилась сбоем",
        }

    taken_at = getattr(snapshot, "taken_at", None)
    if not taken_at:
        return {"ok": False, "detail": "снимок сторожа без метки времени"}

    try:
        taken = datetime.fromisoformat(str(taken_at))
    except ValueError:
        return {"ok": False, "detail": f"метка времени снимка не разобрана: {taken_at}"}

    # Метка сторожа — наивное время UTC: `_now_timestamp()` делает
    # `datetime.now(UTC).replace(tzinfo=None)`. Разбор без часового пояса считал
    # бы её местным временем, и в контейнере с не-UTC-смещением возраст снимка
    # оказывался бы на часы больше настоящего: свежий снимок выглядел бы
    # устаревшим на 18000 секунд.
    if taken.tzinfo is None:
        taken = taken.replace(tzinfo=UTC)

    age = max(0.0, time.time() - taken.timestamp())

    problems = int(getattr(snapshot, "problem_count", 0) or 0)
    if age > stale_sec:
        return {
            "ok": False,
            "age_sec": round(age, 1),
            "problems": problems,
            "detail": f"последний снимок сторожа устарел на {age:.0f} с",
        }

    return {
        "ok": True,
        "age_sec": round(age, 1),
        "problems": problems,
        "detail": "снимки сторожа свежие",
    }


def check_fsm_engine(container: Any) -> dict[str, Any]:
    """Проверить, что движок автоматов собран.

    Args:
        container: Контейнер платформы либо ``None``.

    Returns:
        Словарь с ключом ``ok``, ``devices`` и ``detail``.
    """
    if container is None:
        return {"ok": False, "detail": "контейнер платформы недоступен"}

    engine = getattr(container, "_fsm", None)
    if engine is None:
        return {"ok": False, "detail": "движок автоматов не создан"}

    try:
        devices = len(getattr(engine, "_states", {}))
    except Exception as exc:  # noqa: BLE001 - причина попадает в отчёт
        return {"ok": False, "detail": f"состояние движка неизвестно: {exc}"}

    return {"ok": True, "devices": devices, "detail": "движок собран"}


def collect_checks(request: Any) -> dict[str, dict[str, Any]]:
    """Собрать все проверки готовности.

    Каждая проверка выполняется независимо: отказ одной не скрывает остальные,
    иначе оператор увидел бы одну причину и не узнал бы о других.

    Args:
        request: HTTP-запрос (используется ``request.app.state``).

    Returns:
        Словарь «имя проверки → результат».
    """
    state = getattr(request.app, "state", None)
    container = getattr(state, "container", None) if state is not None else None
    adapter = getattr(container, "_adapter", None) if container is not None else None

    return {
        "data_dir": check_data_dir(),
        "encryption_key": check_encryption_key(),
        "home_assistant": check_home_assistant(adapter),
        "watchdog": check_watchdog(container),
        "fsm_engine": check_fsm_engine(container),
    }
