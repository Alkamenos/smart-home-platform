"""Форма правки поведений: страница отдаётся, скрипт разбирается, логика считается.

Проверка трёх уровней, потому что форма — код на языке, который компилятор
проекта не проверяет:

1. Страница отдаётся и содержит разметку формы — ловит ошибку подключения
   частицы и шаблонизатора, из-за которой форма просто не появилась бы.
2. Скрипт формы разбирается движком JavaScript — ловит синтаксическую ошибку,
   которая иначе обнаружилась бы только в браузере пользователя.
3. Логика формы (разбор диапазона, сбор параметров, выбор режима) исполняется
   и даёт ожидаемые значения — единственная часть проверки, которая доказывает
   поведение, а не наличие текста.

Уровни 1 и 2 проверяют наличие и разбираемость, а не смысл: смысл доказывает
уровень 3. Утверждения об исходном тексте (например, «форма ходит в маршрут
правки») помечены отдельно — они не заменяют проверку поведения.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[2]
FORM_PATH = ROOT / "src" / "webui" / "templates" / "partials" / "behavior_editor.html"
INDEX_PATH = ROOT / "src" / "webui" / "templates" / "index.html"

requires_node = pytest.mark.skipif(
    shutil.which("node") is None, reason="node недоступен: скрипт не проверить"
)


def _form_script() -> str:
    """Достаёт код формы из частицы.

    Returns:
        Исходный текст скрипта формы.

    Raises:
        AssertionError: если в частице нет скрипта.
    """
    text = FORM_PATH.read_text(encoding="utf-8")
    match = re.search(r"<script>(.*?)</script>", text, re.S)
    assert match, "в частице формы нет блока <script>"
    return match.group(1)


class TestFormIsServed:
    """Страница отдаётся вместе с формой."""

    def test_should_include_form_partial(self, isolated_client: TestClient) -> None:
        """Разметка формы присутствует на странице.

        Args:
            isolated_client: HTTP-клиент от имени администратора.
        """
        response = isolated_client.get("/")

        assert response.status_code == 200, response.text
        body = response.text
        assert 'id="behavior-editor-template"' in body, "шаблон формы не подключён"
        assert "window.BehaviorEditor" in body, "скрипт формы не подключён"

    def test_should_show_behaviors_button_only_when_behaviors_exist(self) -> None:
        """Кнопка появляется по наличию поведений, а не всегда.

        Args:
            None.
        """
        source = INDEX_PATH.read_text(encoding="utf-8")

        assert "behaviorEditorButtonHtml" in source
        # Условие показа — непустой список поведений устройства.
        assert "!(device.behaviors || []).length" in source, (
            "кнопка правки показывается независимо от наличия поведений: "
            "устройство без них откроет пустую форму"
        )


@requires_node
class TestFormScriptParses:
    """Скрипт разбирается движком JavaScript."""

    def test_should_parse_without_syntax_error(self, tmp_path: Path) -> None:
        """Ошибка синтаксиса в форме роняет проверку.

        Args:
            tmp_path: Каталог для временного файла.
        """
        script = tmp_path / "behavior_editor.js"
        script.write_text(_form_script(), encoding="utf-8")

        result = subprocess.run(
            ["node", "--check", str(script)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        assert result.returncode == 0, f"скрипт формы не разбирается: {result.stderr.strip()}"


def _run_logic(body: str, tmp_path: Path) -> dict[str, object]:
    """Исполняет тело функции формы в node и возвращает результат.

    Args:
        body: Код, который нужно исполнить; должен вернуть значение через
            выражение ``result``.
        tmp_path: Каталог для временного файла.

    Returns:
        Значение, полученное от node.

    Raises:
        AssertionError: если исполнение не удалось.
    """
    script = tmp_path / "logic.js"
    # node не знает про window: форма живёт в браузере. Заглушка объявляет объект,
    # чтобы проверялась сама логика, а не обращение к окружению.
    shim = "const window = {};\n"
    script.write_text(
        shim + _form_script() + "\n" + body + "\nconsole.log(JSON.stringify(result));\n",
        encoding="utf-8",
    )
    result = subprocess.run(
        ["node", str(script)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, f"исполнение не удалось: {result.stderr.strip()}"
    return json.loads(result.stdout.strip())


@requires_node
class TestFormLogic:
    """Логика формы даёт ожидаемые значения."""

    def test_should_parse_range(self, tmp_path: Path) -> None:
        """Диапазон «мин-макс» разбирается в числа.

        Args:
            tmp_path: Каталог для временного файла.
        """
        result = _run_logic(
            """
            result = {
                parsed: window.BehaviorEditor.parseRange('30-3600'),
                float: window.BehaviorEditor.parseRange('0-5.5'),
                broken: window.BehaviorEditor.parseRange('не диапазон')
            };
            """,
            tmp_path,
        )

        assert result["parsed"] == {"min": "30", "max": "3600"}
        assert result["float"] == {"min": "0", "max": "5.5"}
        # Неудачный разбор даёт пустые границы, а не выдуманные числа:
        # форма без подсказки честнее формы с неверной подсказкой.
        assert result["broken"] == {"min": None, "max": None}

    def test_should_collect_only_filled_params_as_numbers(self, tmp_path: Path) -> None:
        """Пустое поле означает умолчание, заполненное — число.

        Args:
            tmp_path: Каталог для временного файла.
        """
        result = _run_logic(
            """
            const inputs = [
                { value: '200', param: 'brightness' },
                { value: '  ', param: 'motion_timeout_sec' },
                { value: '21.5', param: 'target_temp' },
                { value: '', param: 'hysteresis' }
            ];
            const root = {
                querySelectorAll: () => inputs.map(item => ({
                    value: item.value,
                    dataset: { param: item.param }
                }))
            };
            result = window.BehaviorEditor.collectParams(root, 'fields');
            """,
            tmp_path,
        )

        assert result == {"brightness": 200, "target_temp": 21.5}, (
            "пустое поле должно означать «взять умолчание», то есть не отправляться; "
            "иначе сервер отвергнет его как не прошедшее проверку формата"
        )

    def test_should_reject_invalid_json(self, tmp_path: Path) -> None:
        """Битый JSON не уходит на сервер, а показывается ошибкой.

        Args:
            tmp_path: Каталог для временного файла.
        """
        result = _run_logic(
            """
            const root = { querySelector: () => ({ value: '{ битое' }) };
            let message = null;
            try {
                window.BehaviorEditor.collectParams(root, 'json');
            } catch (error) {
                message = error.message;
            }
            result = { message: message };
            """,
            tmp_path,
        )

        assert result["message"], "битый JSON должен приводить к сообщению, а не к тишине"

    def test_should_reject_non_object_json(self, tmp_path: Path) -> None:
        """Массив вместо объекта отвергается.

        Args:
            tmp_path: Каталог для временного файла.
        """
        result = _run_logic(
            """
            const root = { querySelector: () => ({ value: '[1, 2]' }) };
            let message = null;
            try {
                window.BehaviorEditor.collectParams(root, 'json');
            } catch (error) {
                message = error.message;
            }
            result = { message: message };
            """,
            tmp_path,
        )

        assert "объект" in str(result["message"]).lower(), (
            f"ожидалось сообщение про объект, получено: {result['message']}"
        )


class TestFormSendsToEditRoute:
    """Форма ходит в маршрут правки поведений."""

    def test_should_use_behaviors_route_with_put(self) -> None:
        """Проверка по исходному тексту: маршрут и метод.

        Утверждение о тексте, а не о поведении: маршрут проверяется контрактным
        тестом маршрута, здесь фиксируется лишь факт, что форма обращается
        именно к нему и методом PUT.

        Args:
            None.
        """
        source = _form_script()

        assert "/behaviors" in source, "форма не обращается к маршруту правки поведений"
        assert "method: 'PUT'" in source, "форма отправляет не PUT"
