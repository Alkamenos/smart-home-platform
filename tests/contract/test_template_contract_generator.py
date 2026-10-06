"""Регенерация контракта не должна терять объявления параметров (#72).

Дефект был найден запуском, а не чтением кода: `tools/gen_template_contract.py`
формирует разделы `reachable`, `actions`, `guards`, `triggers`, `gaps` — и **не
формирует `params` ни для одного шаблона**. Все объявления параметров внесены
вручную поверх его вывода, поэтому запуск «освежающего» генератора удалял их
молча: 40 строк вместе с `brightness`, `motion_timeout_sec`, `target_temp`,
`hysteresis`.

Проверка запускает генератор с отдельным путём вывода и сверяет результат с
коммитом. Отдельный путь — обязателен: иначе проверке пришлось бы переписывать
файл в дереве, и падение посреди прогона оставило бы за собой мусор.

Прохождение проверки не означает, что контракт верен по существу: она доказывает
ровно одно — регенерация не отнимает то, что человек вписал руками.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
GENERATOR = ROOT / "tools" / "gen_template_contract.py"
CONTRACT = ROOT / "src" / "features" / "CONTRACT.yaml"


def _committed() -> dict[str, Any]:
    """Читает контракт из дерева.

    Returns:
        Разобранный контракт.
    """
    return yaml.safe_load(CONTRACT.read_text(encoding="utf-8")) or {}


def _regenerate(tmp_path: Path) -> dict[str, Any]:
    """Запускает генератор в отдельный файл и читает результат.

    Args:
        tmp_path: Каталог для результата.

    Returns:
        Разобранный результат генерации.

    Raises:
        AssertionError: если генератор не отработал.
    """
    target = tmp_path / "contract.yaml"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    result = subprocess.run(
        [sys.executable, str(GENERATOR), str(target)],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, f"генератор не отработал: {result.stderr.strip()}"
    assert target.exists(), "генератор не создал файл по указанному пути"
    return yaml.safe_load(target.read_text(encoding="utf-8")) or {}


def _params(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Собирает объявления параметров по шаблонам.

    Args:
        contract: Разобранный контракт.

    Returns:
        Словарь ``имя шаблона`` → параметры.
    """
    return {
        name: (spec or {}).get("params") or {}
        for name, spec in (contract.get("templates") or {}).items()
    }


class TestRegenerationKeepsParams:
    """Регенерация сохраняет объявления параметров."""

    def test_should_not_lose_any_param(self, tmp_path: Path) -> None:
        """Ни один объявленный параметр не пропадает.

        Args:
            tmp_path: Каталог для результата генерации.
        """
        before = _params(_committed())
        after = _params(_regenerate(tmp_path))

        assert before, "в контракте нет ни одного параметра — проверка бессмысленна"
        lost = [
            f"{template}.{param}"
            for template, params in before.items()
            for param in params
            if param not in after.get(template, {})
        ]
        assert not lost, (
            f"регенерация удалила параметры: {lost}. Форма правки поведений останется "
            "без этих полей, а изменить значение будет нечем"
        )

    def test_should_keep_param_settings_unchanged(self, tmp_path: Path) -> None:
        """Значения параметров переносятся без искажений.

        Args:
            tmp_path: Каталог для результата генерации.
        """
        before = _params(_committed())
        after = _params(_regenerate(tmp_path))

        assert before == after, (
            "регенерация изменила объявления параметров: диапазоны, отметки "
            "действенности или подписи не должны «переезжать» сами по себе"
        )

    def test_should_leave_committed_contract_untouched(self, tmp_path: Path) -> None:
        """Файл в дереве после проверки не меняется.

        Args:
            tmp_path: Каталог для результата генерации.
        """
        before = CONTRACT.read_bytes()
        _regenerate(tmp_path)

        assert CONTRACT.read_bytes() == before, (
            "проверка изменила контракт в дереве — она обязана проверять, а не переписывать файл"
        )


class TestGeneratorStructure:
    """Генератор объявляет о своей работе и разделе параметров."""

    def test_should_declare_params_are_carried_over(self) -> None:
        """В исходнике генератора сказано, что параметры переносятся.

        Args:
            None.
        """
        source = GENERATOR.read_text(encoding="utf-8")

        assert "_existing_params" in source, (
            "генератор не читает существующие объявления параметров — они будут "
            "удалены при первом же запуске"
        )
        assert '"    params:"' in source, "генератор не выводит секцию params"


@pytest.mark.parametrize("template", ["lighting", "climate_control"])
def test_contract_params_have_required_fields(template: str) -> None:
    """У каждого параметра есть тип, диапазон, отметка и подпись.

    Без диапазона форма не подскажет границы, без отметки действенности —
    не отличит рабочий параметр от инертного, а подпись объясняет пользователю,
    что произойдёт.

    Args:
        template: Имя шаблона.
    """
    params = _params(_committed())[template]

    assert params, f"у шаблона {template} нет параметров"
    for name, spec in params.items():
        assert spec.get("range"), f"у {template}.{name} нет диапазона"
        assert isinstance(spec.get("effective"), bool), (
            f"у {template}.{name} отметка действенности не булева"
        )
        assert spec.get("note"), f"у {template}.{name} нет подписи"
        assert "ИНЕРТЕН" not in spec["note"] or spec["effective"] is False, (
            f"подпись {template}.{name} говорит «ИНЕРТЕН», но effective=true: "
            "форма покажет пользователю поле, которое код читает, с пометкой "
            "обратного. Подпись осталась от состояния до оживления параметра"
        )
