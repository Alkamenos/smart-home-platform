"""Уровни журналов сторонних библиотек, не наследующие настройку платформы.

Зачем
----

`LOG_LEVEL=DEBUG` в развёртывании поднимает уровень **корневого** обработчика
стандартного журнала, и библиотеки, пишущие через `logging`, начинают выдавать
свой отладочный вывод целиком. В боевом журнале это давало 80% объёма:

```
DEBUG:    > PING b3 d2 62 82 [binary, 4 bytes]
DEBUG:    < PONG b3 d2 62 82 [binary, 4 bytes]
```

Это бинарный обмен WebSocket на каждое сообщение: ни одного полезного байта и
своя частота — heartbeat шлёт ping каждые 30 секунд, а HA отвечает событиями
десятки раз в минуту. Из-за этого в журнале не видно ничего о работе платформы:
чтобы найти переход, приходилось читать `history.db` напрямую, то есть обходить
собственный инструмент наблюдаемости.

Правило
-------

Тишина относится к конкретным библиотекам, а не ко всем сразу: уровень
поднимается у названных журналов, остальное продолжает следовать за `LOG_LEVEL`.
Глушить всё подряд нельзя — `sqlalchemy`, `asyncio` и прочее дают полезный
вывод на DEBUG, и вместе с ними мы потеряли бы диагностику.

Возврат отладочного вывода — настройка `FSM_LOG_LIBRARY_DEBUG=1`: разбирать дом
с бинарным обменом иногда нужно, и молчаливый запрет был бы обещанием без
действия.
"""

from __future__ import annotations

import logging
import os


# Имя переменной окружения, возвращающей отладочный вывод библиотек.
ENV_LIBRARY_DEBUG = "FSM_LOG_LIBRARY_DEBUG"

# Значения, которые её включают. Нераспознанное значение не включает: опечатка
# в настройке не должна возвращать 80% шума в журнал молча.
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

#: Журналы, отладочный вывод которых не несёт смысла для платформы.
#:
#: `websockets` пишет бинарный обмен (PING/PONG и кадры). `websockets.*` —
#: потому что библиотека различает `websockets.client`, `websockets.protocol`
#: и `websockets.server`, и каждый из них пишет отдельно.
QUIET_LIBRARIES = (
    "websockets",
    "websockets.client",
    "websockets.protocol",
    "websockets.server",
    "websockets.extensions",
    "websockets.handshake",
    "websockets.uri",
)


def _flag_enabled(name: str) -> bool:
    """Включён ли булев флаг окружения.

    Args:
        name: Имя переменной окружения.

    Returns:
        True, если переменная задана одним из значений «да».
    """
    return os.environ.get(name, "").strip().lower() in _TRUE_VALUES


def configure_library_logging(force: bool = False) -> list[str]:
    """Поднять уровень журналов библиотек, чей отладочный вывод бесполезен.

    Возвращается список заглушённых журналов — не для отчёта, а чтобы вызов был
    проверяемым снаружи: проверка «уровень стал INFO» проходит и при полном
    отсутствии вызова.

    Args:
        force: Принудительно установить уровень, даже если он уже был выше.
            Нужен для вызова после импорта библиотек, которые сбрасывают уровень.

    Returns:
        Имена журналов, уровень которых был поднят.
    """
    if _flag_enabled(ENV_LIBRARY_DEBUG):
        return []

    quiet_level = logging.INFO
    quieted: list[str] = []
    for name in QUIET_LIBRARIES:
        log = logging.getLogger(name)
        if force or log.level < quiet_level:
            log.setLevel(quiet_level)
            quieted.append(name)
    return quieted
