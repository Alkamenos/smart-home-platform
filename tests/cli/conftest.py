"""Инфраструктура тестов командной строки (спека 009, FR-009…FR-014, R-07).

Три обстоятельства определили устройство этих фикстур.

**Точка входа не принимает аргументы.** `main()` объявлен как `def main() -> int`
без параметров и читает аргументы через `parser.parse_args()`, то есть из
`sys.argv`. Вызов `main(["export-fsm", ...])` дал бы `TypeError`. Значит тесты
подменяют `sys.argv` — и это правильно: именно так команда вызывается
пользователем, и только так проверяются разбор аргументов и код возврата.
Проверка внутренней функции вместо этого не проверяла бы ровно то, где команда
ломается у пользователя.

**Тесты синхронные.** Подкоманды выполняются через `asyncio.run(...)` внутри
`set_defaults(func=...)` (`bulk_import.py:465,500`). Асинхронный тест упал бы с
«cannot be called from a running event loop».

**Интерактивный ввод надо заменить.** `bulk_import` задаёт до пяти вопросов на
одно устройство (`input()` в строках 276, 284, 297, 303, 357, 368, 407). Если
заготовленных ответов не хватит, тест упадёт с невнятным `StopIteration` — по
крайне мере приемлемая причина, но уводит от сути. Поэтому подмена даёт
итератор с запасом и осмысленным поведением при исчерпании.

Ни одна команда в тестах не обращается к внешней системе: адаптер подменяется
на уровне класса (`HAAdapter`), а пути конфигурации — на уровне домашнего
каталога. Иначе результат зависел бы от наличия Home Assistant в сети машины.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest

from smart_home.cli.main import main


@pytest.fixture
def run_cli(monkeypatch, capsys):
    """Выполняет команду через штатную точку входа и возвращает результат.

    Args:
        monkeypatch: Фикстура подмены.
        capsys: Фикстура перехвата вывода.

    Returns:
        Функция запуска: принимает аргументы, возвращает код возврата, строки
        и ошибку.
    """

    def _run(*argv: str) -> tuple[int, str, str]:
        """Запускает CLI с заданными аргументами.

        Args:
            *argv: Аргументы командной строки.

        Returns:
            Кортеж «код возврата, stdout, stderr».
        """
        monkeypatch.setattr(sys, "argv", ["smart-home", *argv])
        code = main()
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return _run


@pytest.fixture
def cli_home(monkeypatch, tmp_path) -> Iterator[Path]:
    """Подменяет домашний каталог на временный.

    Нужно команде `bulk-import config`, которая читает
    `~/.config/smart_home/bulk_import.yaml` (`bulk_import.py:140`). Без
    подмены тест читал бы и, в перспективе, писал бы в настоящую
    пользовательскую конфигурацию.

    Args:
        monkeypatch: Фикстура подмены.
        tmp_path: Временный каталог pytest.

    Yields:
        Путь к временному «домашнему» каталогу.
    """
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    yield home


@pytest.fixture
def scripted_input(monkeypatch):
    """Подменяет `input()` заранее подготовленными ответами.

    Args:
        monkeypatch: Фикстура подмены.

    Returns:
        Функция установки ответов: принимает список строк.
    """

    def _set(answers: Sequence[str]) -> None:
        """Устанавливает ответы на вопросы.

        Args:
            answers: Ответы по порядку вопросов.
        """
        pending = list(answers)
        asked: list[str] = []

        def _input(prompt: str = "") -> str:
            """Отвечает на один вопрос.

            Args:
                prompt: Текст вопроса.

            Returns:
                Подготовленный ответ либо пустая строка.
            """
            asked.append(prompt)
            if not pending:
                return ""
            return pending.pop(0)

        monkeypatch.setattr("builtins.input", _input)

    return _set


@pytest.fixture
def manifest_copy(tmp_path, project_root_manifest) -> Path:
    """Копия манифеста во временном каталоге.

    Копия нужна, а не сам манифест: команды `bulk-import apply` и `interactive`
    пишут в него, и тест не должен трогать манифест репозитория.

    Args:
        tmp_path: Временный каталог pytest.
        project_root_manifest: Исходный манифест.

    Returns:
        Путь к копии манифеста.
    """
    target = tmp_path / "manifest.yaml"
    target.write_text(project_root_manifest.read_text(encoding="utf-8"), encoding="utf-8")
    return target


@pytest.fixture
def project_root_manifest() -> Path:
    """Путь к манифесту проекта.

    Returns:
        Путь к манифесту.
    """
    root = Path(__file__).resolve().parent.parent.parent
    return root / "instances" / "leonids_house" / "manifest.yaml"


@pytest.fixture
def broken_manifest(tmp_path) -> Path:
    """Манифест с неразбираемым содержимым.

    Args:
        tmp_path: Временный каталог pytest.

    Returns:
        Путь к повреждённому манифесту.
    """
    path = tmp_path / "broken.yaml"
    path.write_text("rooms: [unclosed\n  - id: ???\n\ttabs:", encoding="utf-8")
    return path


class FakeHAAdapter:
    """Заглушка адаптера внешней системы для командной строки.

    `bulk-import` создаёт `HAAdapter(mode="websocket", ...)` и вызывает
    `start()`/`stop()`. Подмена класса целиком исключает и сетевой вызов, и
    чтение токена из окружения.

    Attributes:
        devices: Устройства, которые вернёт обход.
        start_calls: Сколько раз вызвали `start`.
        stop_calls: Сколько раз вызвали `stop`.
    """

    def __init__(self, mode: str = "websocket", ws_url: str = "", token: str = "") -> None:
        """Инициализирует заглушку.

        Args:
            mode: Режим адаптера — принимается и игнорируется.
            ws_url: Адрес внешней системы — принимается и игнорируется.
            token: Токен — принимается и игнорируется.
        """
        self.devices: list[dict[str, Any]] = []
        self.start_calls = 0
        self.stop_calls = 0

    async def start(self) -> None:
        """Имитирует запуск."""
        self.start_calls += 1

    async def stop(self) -> None:
        """Имитирует остановку."""
        self.stop_calls += 1

    async def get_states(self) -> list[dict[str, Any]]:
        """Возвращает подготовленные состояния.

        Returns:
            Список состояний устройств.
        """
        return self.devices


@pytest.fixture
def fake_ha(monkeypatch) -> type[FakeHAAdapter]:
    """Подменяет класс адаптера внешней системы.

    Args:
        monkeypatch: Фикстура подмены.

    Returns:
        Класс заглушки — им можно задать набор устройств перед запуском.
    """
    monkeypatch.setattr("src.adapters.ha_adapter.HAAdapter", FakeHAAdapter)
    return FakeHAAdapter
