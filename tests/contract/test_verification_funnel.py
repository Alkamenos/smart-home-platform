"""Контракт воронки проверок (спека 009, US3, `contracts/verification-funnel.md`).

Проверяет соглашение о запуске, а не поведение тестов. Существует потому, что
расхождение между путями проверки **было невидимым**: локальная команда
исключала 163 теста, нигде не сообщая об этом, и никто этого не замечал
потому, что по дороге она падала с кодом 2, не выполнив ни одного теста.

Если тесты воронки падают — почти наверняка кто-то изменил `Makefile`,
`pyproject.toml` или `run_checks.sh` так, что пути проверки снова разошлись.
Это дешёвый способ обнаружить такое на ранней стадии.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent.parent

#: Файл, где pytest объявляет состав набора и исключения.
PYPROJECT = ROOT / "pyproject.toml"

#: Локальные команды проверки.
MAKEFILE = ROOT / "Makefile"

#: Скрипт автоматической проверки.
RUN_CHECKS = ROOT / ".ai" / "scripts" / "run_checks.sh"


@pytest.fixture(scope="module")
def pytest_config() -> dict:
    """Читает секцию конфигурации pytest.

    Returns:
        Словарь `tool.pytest.ini_options`.
    """
    with PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)["tool"]["pytest"]["ini_options"]


@pytest.fixture(scope="module")
def makefile_text() -> str:
    """Читает Makefile.

    Returns:
        Содержимое файла.
    """
    return MAKEFILE.read_text(encoding="utf-8")


def _recipe(text: str, target: str) -> str:
    """Извлекает тело рецепта make.

    Args:
        text: Содержимое Makefile.
        target: Имя цели.

    Returns:
        Строки рецепта либо пустая строка, если цели нет.
    """
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if line.strip().split(":")[0] == target and not line.startswith(" "):
            recipe = []
            for following in lines[index + 1 :]:
                if not following.startswith("\t"):
                    break
                recipe.append(following.strip())
            return "\n".join(recipe)
    return ""


class TestCollectionWorks:
    """Прогон обязан собирать тесты при любом способе запуска."""

    def test_repo_root_is_on_pythonpath(self, pytest_config):
        """Корень репозитория объявлен в `pythonpath`.

        Без этого консольный скрипт `pytest` падал на коллекции с
        `ModuleNotFoundError: No module named 'src'` в шести модулях: режим
        `importlib` не добавляет корень в путь, а console-script не добавляет
        и текущий каталог — в отличие от `python -m pytest`. Локальная команда
        проверки при этом завершалась с кодом 2, не выполнив ни одного теста.
        """
        assert pytest_config.get("pythonpath") == ["."], (
            "корень репозитория должен быть в pythonpath, иначе pytest "
            "не собирает модули, импортирующие src.*"
        )

    def test_importlib_mode_is_declared(self, pytest_config):
        """Режим импорта объявлен явно — от него зависит путь в модулях."""
        assert "--import-mode=importlib" in pytest_config["addopts"], (
            "режим importlib нужен из-за коллизии одинаковых имён тестовых модулей (Known Issue #3)"
        )

    def test_testpaths_points_at_tests(self, pytest_config):
        """Набор берётся из каталога тестов."""
        assert pytest_config["testpaths"] == ["tests"]


class TestExclusionsAreDeclared:
    """Исключения обязаны нести причину."""

    def test_browser_tests_left_the_backend_suite(self, pytest_config):
        """Браузерные тесты старого интерфейса удалены вместе с ним (спека 017).

        Раньше файл исключался из общего прогона; теперь его нет: интерфейс
        проверяется Playwright во фронтенде (`frontend/tests/e2e`), отдельной
        целью — исключать в `addopts` нечего.
        """
        assert "test_webui_playwright.py" not in pytest_config["addopts"], (
            "файла больше нет — исключение устарело"
        )
        assert not (ROOT / "tests" / "test_webui_playwright.py").exists(), (
            "старые браузерные тесты должны быть удалены вместе со старым интерфейсом"
        )

    def test_every_ignore_in_addopts_is_documented(self, pytest_config):
        """Каждое исключение в `addopts` объяснено комментарием.

        Исключений может и не быть — тогда документировать нечего. Проверка
        поштучная: молчаливое сокращение набора опаснее явного.
        """
        text = PYPROJECT.read_text(encoding="utf-8")
        comments = [line for line in text.splitlines() if line.strip().startswith("#")]
        ignores = [
            token.split("=")[-1]
            for token in re.split(r"\s+", pytest_config["addopts"])
            if token.startswith("--ignore=")
        ]

        for target in ignores:
            name = Path(target).name
            assert any(name in line for line in comments), (
                f"исключение {target} не объяснено ни одной строкой комментария"
            )


class TestLocalAndAutomatedAgree:
    """Локальная и автоматическая проверки обязаны запускать одно и то же."""

    def test_make_test_does_not_silently_drop_integration(self, makefile_text):
        """Локальная команда проверки не исключает интеграционные тесты молча.

        Исключение `tests/integration/` убирало **163 теста** в 14 файлах, то
        есть 8.4% набора, и нигде не сообщало об этом. Раньше расхождение не
        было видно: команда падала с кодом 2 раньше, чем оно могло проявиться.
        """
        recipe = _recipe(makefile_text, "test")

        assert recipe, "цель `test` должна существовать"
        assert "tests/integration" not in recipe, (
            "локальная команда проверки исключает интеграционные тесты; "
            "исключение должно быть объявлено явно, а не молча"
        )

    def test_make_test_matches_canonical_invocation(self, makefile_text):
        """Локальная команда не задаёт собственный состав набора.

        Свой `--ignore` в Makefile — это второй источник правды о том, что
        запускается. Канонический состав задаётся в `pyproject.toml`.
        """
        recipe = _recipe(makefile_text, "test")

        for token in recipe.split():
            if token.startswith("--ignore"):
                raise AssertionError(
                    f"Makefile задаёт собственное исключение {token!r}; "
                    "состав набора должен определяться в одном месте"
                )

    def test_all_test_targets_share_one_composition(self, makefile_text):
        """Агрегирующие команды проверки не расходятся между собой."""
        aggregates = {
            target: _recipe(makefile_text, target)
            for target in ("test", "test-verbose", "test-fast")
        }
        ignores = {
            target: sorted(re.findall(r"--ignore[= ](\S+)", recipe))
            for target, recipe in aggregates.items()
            if recipe
        }

        assert ignores, "должна быть хотя бы одна агрегирующая цель"
        distinct = {tuple(value) for value in ignores.values()}
        assert len(distinct) == 1, f"цели проверки задают разные исключения: {ignores}"


class TestAutomatedChecksRunTests:
    """Автоматическая проверка обязана запускать тесты."""

    def test_run_checks_executes_tests(self):
        """Скрипт проверки запускает тесты и учитывает их провал.

        Блок «Tests» был закомментирован с 2026-09-21 (`36c710f fix: disable
        pre-push tests`), при том что `.githooks/pre-push` вызывает только этот
        скрипт и подписан «тесты + линтер + покрытие». Скрипт завершался с
        кодом 0, не выполнив ни одного теста.

        Проверяется не буквальное наличие слова «tests» в команде — набор
        задаётся `testpaths` в `pyproject.toml`, — а то, что провал тестов
        влияет на итоговый код возврата скрипта.
        """
        text = RUN_CHECKS.read_text(encoding="utf-8")

        invocations = [
            line
            for line in text.splitlines()
            if "pytest" in line
            and not line.strip().startswith("#")
            and "REQUIRED_TOOLS" not in line
            and "command -v" not in line
        ]
        assert invocations, "скрипт проверки не запускает тесты ни разу"

        # Отделённый блок тестов обязан влиять на итоговый статус.
        after = text.split(invocations[0], 1)[1]
        assert "FAILED=1" in after, "провал тестов не влияет на код возврата скрипта"

    def test_run_checks_declares_browser_exclusion(self):
        """Браузерные тесты не входят в прогон, и это сказано вслух.

        После спеки 017 браузерные тесты живут во фронтенде
        (``frontend/tests/e2e``). Скрипт обязан называть исключение и способ их
        запустить — иначе человек прочтёт отчёт как «проверено всё».
        """
        text = RUN_CHECKS.read_text(encoding="utf-8")

        assert "test_webui_playwright.py" not in text, (
            "скрипт ссылается на удалённый файл браузерных тестов"
        )
        assert "frontend" in text and "e2e" in text, (
            "скрипт обязан сказать, где живут браузерные тесты и как их запустить"
        )

    def test_run_checks_distinguishes_tool_presence_from_actual_run(self):
        """Проверка наличия бинаря не выдаётся за запуск тестов.

        Скрипт делает и то, и другое, и это законно: сначала убеждается, что
        инструмент установлен, затем запускает его. Проверка следит, чтобы
        упоминание `pytest` в списке инструментов **не было единственным** —
        именно такая подмена и прятала отключённый блок тестов.
        """
        text = RUN_CHECKS.read_text(encoding="utf-8")
        lines = [line for line in text.splitlines() if "pytest" in line]

        presence = [line for line in lines if "REQUIRED_TOOLS" in line or "command -v" in line]
        runs = [line for line in lines if line not in presence and not line.strip().startswith("#")]

        assert presence, "скрипт должен проверять наличие инструментов"
        assert runs, "pytest упоминается только в проверке бинаря — тесты не запускаются"
        assert all("no-cov" in line or "tests" in line for line in runs), (
            f"запуск pytest должен указывать набор тестов: {runs}"
        )


class TestNoSilentExclusions:
    """Невыполненное должно быть видно."""

    def test_documented_exclusions_are_enumerated(self):
        """Известные исключения перечислены явно, а не подразумеваются.

        Список живёт в контракте воронки; проверка гарантирует, что он не
        разойдётся с реальностью.
        """
        contract = ROOT / "specs" / "009-test-coverage" / "contracts" / "verification-funnel.md"
        text = contract.read_text(encoding="utf-8")

        assert "test_webui_playwright.py" in text, (
            "контракт должен называть исключение браузерных тестов явно"
        )

    def test_every_ignore_path_exists(self, pytest_config):
        """Исключаемые пути существуют — иначе исключение устарело.

        Исключение несуществующего пути выглядит безобидно, но означает, что
        набор изменился, а объявление — нет.
        """
        for token in re.split(r"\s+", pytest_config["addopts"]):
            if not token.startswith("--ignore="):
                continue
            target = ROOT / token.split("=", 1)[1]
            assert target.exists(), f"исключённый путь не существует: {target}"
