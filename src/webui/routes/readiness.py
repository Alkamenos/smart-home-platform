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

from loguru import logger

from core.persistence.paths import resolve_data_dir
from core.security.encryption import DEFAULT_KEY_FILENAME


#: Порог «свежести» снимка сторожа: два интервала сторожа с запасом.
WATCHDOG_STALE_SEC = 180.0

#: Порог «свежести» синхронизации источника по умолчанию: сутки.
SYNC_STALE_SEC = 86_400

#: Переменная окружения с порогом устаревания синхронизации.
SYNC_STALE_ENV = "SYNC_STALE_SEC"


def sync_stale_sec() -> float:
    """Прочитать порог устаревания синхронизации.

    Некорректное значение (не число, ноль, отрицательное) заменяется значением
    по умолчанию с предупреждением: сбой настройки не должен ни ронять старт, ни
    превращать проверку в вечно зелёную.

    Returns:
        Порог в секундах.
    """
    raw = os.getenv(SYNC_STALE_ENV)
    if raw is None:
        return float(SYNC_STALE_SEC)
    try:
        value = float(raw)
    except ValueError:
        logger.warning(f"{SYNC_STALE_ENV}={raw!r} is not a number; using default")
        return float(SYNC_STALE_SEC)
    if value <= 0:
        logger.warning(f"{SYNC_STALE_ENV}={raw!r} is not positive; using default")
        return float(SYNC_STALE_SEC)
    return value


def _age_seconds(stamp: Any) -> float | None:
    """Посчитать возраст метки времени в секундах.

    Метка источника хранится наивным временем UTC (`datetime.utcnow()`), а из
    JSON-хранилища может прийти строкой. Разбор без часового пояса считал бы её
    местным временем, и в контейнере с не-UTC-смещением возраст оказался бы
    на часы больше настоящего — то есть либо вечно протухшим, либо вечно свежим.

    Args:
        stamp: Метка времени: `datetime`, строка ISO-8601 или `None`.

    Returns:
        Возраст в секундах либо `None`, если метки нет или она не разобрана.
    """
    if stamp is None:
        return None

    if isinstance(stamp, datetime):
        taken = stamp
    else:
        try:
            taken = datetime.fromisoformat(str(stamp))
        except ValueError:
            return None

    if taken.tzinfo is None:
        taken = taken.replace(tzinfo=UTC)

    return max(0.0, time.time() - taken.timestamp())


async def check_source_sync(persistence: Any, stale_sec: float | None = None) -> dict[str, Any]:
    """Проверить, что данные источников не устарели.

    Синхронизация запускается только вручную, поэтому её возраст не растёт
    сам и не выглядит поломкой — её просто никто не запускает. Пока `/ready` о
    ней молчал, оператор видел исправную систему и список устройств наполненным,
    а данные в нём были на момент последнего ручного нажатия: устройство,
    появившееся или исчезнувшее за это время, платформа не знала.

    Отсутствие источников отказом не считается: синхронизировать нечего.
    Недоступное хранилище — наоборот, отказ: это уже не отсутствие данных, а
    невозможность их прочитать.

    Args:
        persistence: Персистентность платформы либо ``None``.
        stale_sec: Порог устаревания в секундах; по умолчанию из окружения.

    Returns:
        Словарь с ключом ``ok``, ``sources``, ``stale``, ``not_connected``,
        ``oldest_age_sec``, ``stale_after_sec`` и ``detail``.
    """
    limit = sync_stale_sec() if stale_sec is None else stale_sec
    result: dict[str, Any] = {
        "ok": False,
        "sources": 0,
        "stale": [],
        "not_connected": [],
        "oldest_age_sec": None,
        "stale_after_sec": limit,
    }

    try:
        store = getattr(persistence, "sources", None)
    except Exception as exc:  # noqa: BLE001 — причина попадает в отчёт
        result["detail"] = f"хранилище источников недоступно: {exc}"
        return result

    if store is None:
        result["detail"] = "хранилище источников не найдено"
        return result

    try:
        sources = await store.load_all_sources()
    except Exception as exc:  # noqa: BLE001 — причина попадает в отчёт
        result["detail"] = f"источники не прочитаны: {exc}"
        return result

    if not sources:
        result["ok"] = True
        result["detail"] = "источников нет: синхронизировать нечего"
        return result

    stale: list[dict[str, Any]] = []
    not_connected: list[str] = []
    ages: list[float] = []

    for source in sources:
        age = _age_seconds(getattr(source, "last_sync", None))

        if str(getattr(source, "status", "")) != "connected":
            not_connected.append(str(getattr(source, "name", "источник без имени")))

        if age is None or age > limit:
            stale.append(_stale_source_entry(source, age, limit))

        if age is not None:
            ages.append(age)

    oldest = max(ages) if ages else None
    result["sources"] = len(sources)
    result["stale"] = stale
    result["not_connected"] = not_connected
    result["oldest_age_sec"] = round(oldest, 1) if oldest is not None else None
    result["ok"] = not stale

    if stale:
        listed = "; ".join(
            f"{entry['name']} — {entry['reason']}"
            + (f" ({int(entry['age_sec'])} с)" if entry["age_sec"] is not None else "")
            for entry in stale
        )
        result["detail"] = (
            f"данные источников устарели: {listed}. Обновите вручную: "
            f"POST /api/v1/devices/sources/<id>/sync — по расписанию синхронизация "
            f"не запускается"
        )
    else:
        result["detail"] = f"синхронизация не старше {int(limit)} с, источников — {len(sources)}"

    if not_connected:
        result["detail"] += f"; отключены: {', '.join(not_connected)}"

    return result


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


def _stale_source_entry(source: Any, age: float | None, limit: float) -> dict[str, Any]:
    """Описать протухший источник для отчёта.

    Args:
        source: Источник Home Assistant.
        age: Возраст данных в секундах либо ``None``, если метки нет или она
            не разобрана.
        limit: Порог устаревания в секундах.

    Returns:
        Словарь с именем, возрастом и причиной.
    """
    name = str(getattr(source, "name", "источник без имени"))
    if age is None:
        raw_sync = getattr(source, "last_sync", None)
        reason = (
            "дата синхронизации не разобрана"
            if raw_sync is not None
            else "ни разу не синхронизирован"
        )
        return {"name": name, "age_sec": None, "reason": reason}
    return {
        "name": name,
        "age_sec": round(age, 1),
        "reason": f"данные старше {int(limit)} с",
    }


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


def check_deployment_mode(container: Any) -> dict[str, Any]:
    """Проверить, исполняет ли платформа обещанные команды.

    Режим развёртывания — не строчка в журнале, а часть готовности. Дефект #77
    был обратной стороной того же: `SHADOW_MODE` доходил до контейнера и не
    читался кодом, поэтому оператор считал систему безопасной, а она трогала
    дом. Теперь режим читается и блокирует выход — но без ответа в `/ready`
    оператор не увидит и обратного: события приходят, автоматы считают
    состояния, `ready: true`, а лампы не включаются.

    Поэтому в режиме тени готовность ложная: система принимает события и
    считает состояния, но не исполняет команды.

    Args:
        container: Контейнер платформы либо ``None``.

    Returns:
        Словарь ``ok``, ``mode`` и ``detail``.
    """
    deployment = getattr(container, "_deployment", None)
    if deployment is None:
        # Отсутствие менеджера — отсутствие данных, а не отказ: сборка без
        # развёртывания (тесты, локальный запуск) не должна падать на проверке,
        # которая для этой конфигурации ничего не утверждает.
        return {
            "ok": True,
            "mode": "unknown",
            "detail": "режим развёртывания не задан",
        }

    try:
        executes = bool(deployment.should_execute_action())
        mode = str(getattr(deployment.get_mode(), "value", "unknown"))
    except Exception as exc:  # noqa: BLE001 - причина попадает в отчёт
        return {
            "ok": False,
            "mode": "unknown",
            "detail": f"режим развёртывания неизвестен: {exc}",
        }

    if executes:
        return {
            "ok": True,
            "mode": mode,
            "detail": f"режим {mode}: команды исполняются",
        }

    return {
        "ok": False,
        "mode": mode,
        "detail": (
            f"режим {mode}: команды НЕ исполняются, платформа только считает "
            f"состояния. Чтобы включить выход в Home Assistant, задайте "
            f"SHADOW_MODE=false и перезапустите контейнер"
        ),
    }


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


async def collect_checks(request: Any) -> dict[str, dict[str, Any]]:
    """Собрать все проверки готовности.

    Каждая проверка выполняется независимо: отказ одной не скрывает остальные,
    иначе оператор увидел бы одну причину и не узнал бы о других. Поэтому
    проверка источников, которой нечем читать, даёт отказ в своём ключе, а не
    прерывает сбор остальных.

    Args:
        request: HTTP-запрос (используется ``request.app.state``).

    Returns:
        Словарь «имя проверки → результат».
    """
    state = getattr(request.app, "state", None)
    container = getattr(state, "container", None) if state is not None else None
    adapter = getattr(container, "_adapter", None) if container is not None else None
    persistence = getattr(state, "persistence", None) if state is not None else None

    return {
        "data_dir": check_data_dir(),
        "encryption_key": check_encryption_key(),
        "deployment_mode": check_deployment_mode(container),
        "home_assistant": check_home_assistant(adapter),
        "watchdog": check_watchdog(container),
        "fsm_engine": check_fsm_engine(container),
        "source_sync": await check_source_sync(persistence),
    }
