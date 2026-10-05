"""Импорт `main` не должен собирать приложение (Known Issue K7).

Дефект: `src/main.py` выполнял `app = create_app()` на уровне модуля «для
TestClient-совместимости». Продакшен запускается как `python -m src.main`, то
есть **импортирует** модуль, и в этот момент собиралось второе приложение со
вторым контейнером, вторым экземпляром реестра и вторым снимком манифеста —
по пути из образа, а не из тома.

Доказано запуском контейнера: при одном старте `Registered 10 action handlers`
печатается дважды, а `Discovery routes initialized` — с двумя разными
манифестами, `/app/instances/leonids_house/manifest.yaml` и
`/config/behavioral_platform/manifest.yaml`.

Последствия не косметические: два экземпляра держат два независимых
`ManifestStore`, и изменение, сделанное одним, не видно другому — ровно тот
дефект, из-за которого `POST /api/v1/devices/apply` не находил комнату.

Тест запускает подпроцесс: состояние модуля уже импортированного `main` нельзя
изолировать в том же процессе, а именно изоляция здесь и проверяется.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture
def root() -> str:
    """Корень репозитория строкой — подпроцесс получает его как аргумент.

    Returns:
        Путь к корню репозитория.
    """
    return str(Path(__file__).resolve().parents[2])


PREAMBLE = """
import sys
sys.path.insert(0, {root!r})
import webui.app as webui_app

calls = []
_original = webui_app.create_app


def _counting(*args, **kwargs):
    calls.append(1)
    return _original(*args, **kwargs)


webui_app.create_app = _counting
"""


def _run(root: str, body: str) -> str:
    """Выполняет код в подпроцессе и возвращает stdout.

    Args:
        root: Корень проекта (каталог с пакетом `src`).
        body: Код для выполнения после подмены `create_app`.

    Returns:
        Вывод подпроцесса.
    """
    script = PREAMBLE.format(root=root) + body
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=root,
        check=False,
    )
    assert result.returncode == 0, result.stderr[-2000:]
    return result.stdout.strip()


def test_import_main_should_not_build_application(root: str) -> None:
    """Импорт `src.main` не должен ни разу вызвать `create_app`.

    Args:
        root: Корень проекта.
    """
    out = _run(root, "import src.main\nprint('calls=', len(calls))")
    assert out == "calls= 0", (
        f"импорт src.main собрал приложение: {out}. "
        "Продакшен импортирует модуль перед run_platform и получает второй "
        "контейнер со вторым манифестом."
    )


def test_accessing_app_attribute_should_build_application_once(root: str) -> None:
    """Обращение к `main.app` по-прежнему собирает приложение — ровно один раз.

    Контрактные тесты импортируют `from main import app`, поэтому ленивая сборка
    обязана сохранить эту возможность.

    Args:
        root: Корень проекта.
    """
    out = _run(
        root,
        "import src.main\n"
        "first = src.main.app\n"
        "second = src.main.app\n"
        "print('calls=', len(calls))\n"
        "print('same=', first is second)\n",
    )
    assert "calls= 1" in out, f"ожидалась ровно одна сборка, получено: {out}"
    assert "same= True" in out, f"повторное обращение дало другое приложение: {out}"


def test_run_platform_should_be_the_only_builder(root: str) -> None:
    """`run_platform` остаётся единственным местом, собирающим продакшен-приложение.

    Args:
        root: Корень проекта.
    """
    out = _run(
        root,
        "import inspect, src.main\n"
        "source = inspect.getsource(src.main.run_platform)\n"
        "print('builds=', source.count('create_app('))\n",
    )
    assert out == "builds= 1", f"run_platform должен собирать приложение один раз: {out}"


def test_main_module_has_no_module_level_create_app_call(root: str) -> None:
    """На уровне модуля вызова `create_app()` быть не должно.

    Проверка по исходнику, а не по поведению: поведение зависит от того, успел
    ли импорт что-то вызвать, а запрет здесь структурный.

    Args:
        root: Корень проекта.
    """
    source = Path(root, "src", "main.py").read_text(encoding="utf-8")
    module_level = [
        line
        for line in source.split("\n")
        if line.startswith("app = create_app(") or line.startswith("app = create_app()")
    ]
    assert not module_level, f"в src/main.py остался вызов на уровне модуля: {module_level}"


def test_singleton_is_cached_between_accesses(root: str) -> None:
    """Повторные обращения не пересобирают приложение и не плодят контейнеры.

    Args:
        root: Корень проекта.
    """
    out = _run(
        root,
        "import src.main\n"
        "apps = [src.main.app for _ in range(5)]\n"
        "print('calls=', len(calls))\n"
        "print('unique=', len({id(a) for a in apps}))\n",
    )
    assert "calls= 1" in out, f"при пяти обращениях ожидалась одна сборка: {out}"
    assert "unique= 1" in out, f"приложения разошлись: {out}"


def test_import_main_should_not_read_manifest_from_image_copy(root: str) -> None:
    """Импорт `src.main` не должен открывать манифест из каталога `instances`.

    Именно этот путь брал второй контейнер в контейнере: образ содержит
    `/app/instances/leonids_house/manifest.yaml`, а том — `/config/behavioral_platform/manifest.yaml`.
    Расхождение этих двух файлов и было причиной «комната не найдена, хотя /api/rooms её показывает».

    Args:
        root: Корень проекта.
    """
    out = _run(
        root,
        "import pathlib, builtins\n"
        "opened = []\n"
        "_open = builtins.open\n"
        "def tracking_open(file, *args, **kwargs):\n"
        "    try:\n"
        "        name = str(file)\n"
        "    except Exception:\n"
        "        name = ''\n"
        "    if name.endswith('manifest.yaml'):\n"
        "        opened.append(name)\n"
        "    return _open(file, *args, **kwargs)\n"
        "builtins.open = tracking_open\n"
        "import src.main\n"
        "print('image_copy=', sum(1 for p in opened if '/instances/' in p))\n"
        "print('total=', len(opened))\n",
    )
    assert "image_copy= 0" in out, f"импорт открыл манифест из образа: {out}"
    assert "total= 0" in out, f"импорт вообще что-то читал: {out}"
