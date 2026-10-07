"""Процедура приёмки должна быть исполняема, а не описана.

Зачем проверять документ
-----------------------

Несколько дефектов числились закрытыми без единой живой проверки: единственным
следом оставалась строка в Known Issues, а отсутствие записи выглядело как «всё
проверено». Проверка «прошло» без даты и без видимого признака через полгода
неотличима от «не проверялось».

Поэтому у процедуры есть требования к форме, а не только к содержанию:

1. у каждого шага есть признак успеха — иначе непонятно, состоял ли шаг;
2. у каждого шага есть условие остановки — иначе при провале продолжают и
   получают хуже, чем было;
3. у каждого шага есть графа результата, и «не проверено» в ней допустимо —
   иначе пропуск неотличим от успеха;
4. есть сводная таблица, без которой результаты разъезжаются по шагам;
5. есть дата и исполнитель — результат без даты через год ничего не значит.

Проверка читает сам документ: расхождение между процедурой и её текстом —
ровно тот класс дефекта, который она должна ловить.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import re
from pathlib import Path


#: Путь к процедуре рядом со спекой.
QUICKSTART = Path(__file__).resolve().parents[2] / "specs" / "010-live-acceptance" / "quickstart.md"

#: Обязательные элементы каждого шага.
SUCCESS_SIGN = "Признак успеха"
STOP_CONDITION = "Условие остановки"
RESULT_LINE = "Результат:"


def _text() -> str:
    """Текст процедуры.

    Returns:
        Содержимое файла quickstart.md.
    """
    return QUICKSTART.read_text(encoding="utf-8")


def _step_sections() -> list[tuple[str, str]]:
    """Разделы шагов процедуры.

    Returns:
        Список пар «заголовок шага — тело шага».
    """
    text = _text()
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    steps: list[tuple[str, str]] = []
    for part in parts:
        title, _, body = part.partition("\n")
        if title.startswith("Шаг"):
            steps.append((title, body))
    return steps


class TestProcedureExists:
    """Процедура написана и читается."""

    def test_file_is_readable(self) -> None:
        """Файл процедуры на месте."""
        assert QUICKSTART.is_file(), f"процедуры приёмки нет: {QUICKSTART}"

    def test_has_several_steps(self) -> None:
        """Шагов больше одного — иначе это не процедура, а одна проверка."""
        steps = _step_sections()

        assert len(steps) >= 5, f"шагов мало для процедуры запуска: {len(steps)}"


class TestEveryStepIsVerifiable:
    """Каждый шаг даёт понять, состоял ли он."""

    def test_each_step_states_success_signal(self) -> None:
        """У каждого шага назван признак успеха.

        Returns:
            Ничего.
        """
        missing = [title for title, body in _step_sections() if SUCCESS_SIGN not in body]

        assert not missing, (
            f"шаги без признака успеха: {missing}. По такому шагу нельзя понять, "
            f"состоял ли он: «вроде работает» и «работает» неразличимы"
        )

    def test_each_step_states_stop_condition(self) -> None:
        """У каждого шага есть условие остановки.

        Returns:
            Ничего.
        """
        missing = [title for title, body in _step_sections() if STOP_CONDITION not in body]

        assert not missing, (
            f"шаги без условия остановки: {missing}. Провал шага должен останавливать "
            f"процедуру, а не приводить к расширению автоматизации на всё остальное"
        )

    def test_success_signal_is_observable_without_tools(self) -> None:
        """Признак успеха не требует специальных инструментов.

        Проверяется грубо: шаг, требующий чтения исходного кода или внутренних
        отладочных средств, противоречит назначению процедуры — её исполняет
        владелец.

        Returns:
            Ничего.
        """
        offenders = [
            title
            for title, body in _step_sections()
            if "исходн" in body.lower() and "журнал" not in body.lower()
        ]

        assert not offenders, f"шаги, требующие чтения кода: {offenders}"


class TestNotCheckedIsRecorded:
    """Пропуск должен быть виден как пропуск."""

    def test_each_step_has_result_line(self) -> None:
        """У каждого шага есть графа результата.

        Returns:
            Ничего.
        """
        missing = [title for title, body in _step_sections() if RESULT_LINE not in body]

        assert not missing, f"шаги без графы результата: {missing}"

    def test_not_checked_is_one_of_the_options(self) -> None:
        """«Не проверено» — допустимый результат и оно названо прямо.

        Именно его отсутствие в списке превращает пропуск в молчаливый успех:
        отметить нечего — значит не отмечено ничего.

        Returns:
            Ничего.
        """
        for title, body in _step_sections():
            line = next(
                (ln for ln in body.split("\n") if RESULT_LINE in ln),
                "",
            )
            assert "not checked" in line, (
                f"в шаге «{title}» нет варианта «не проверено»: {line!r}. Пропуск "
                f"обязан записываться, иначе он читается как успех"
            )

    def test_summary_table_lists_every_step(self) -> None:
        """Сводная таблица содержит каждый шаг.

        Returns:
            Ничего.
        """
        text = _text()
        table_rows = [ln for ln in text.split("\n") if re.match(r"^\|\s*\d+\s*\|", ln)]
        steps = _step_sections()

        assert len(table_rows) == len(steps), (
            f"в сводной таблице {len(table_rows)} строк на {len(steps)} шагов: "
            f"результаты разъедутся по шагам"
        )


class TestProcedureIsDated:
    """Результат без даты через год ничего не значит."""

    def test_fields_for_date_and_executor_exist(self) -> None:
        """В процедуре есть место для даты и исполнителя.

        Returns:
            Ничего.
        """
        text = _text().lower()

        assert "дата" in text, "в процедуре нет графы для даты запуска"
        assert "исполнитель" in text, "в процедуре нет графы для исполнителя"


class TestNoImplementationDetails:
    """Процедуру исполняет владелец, а не разработчик."""

    def test_steps_do_not_name_code(self) -> None:
        """Шаги не ссылаются на файлы и строки исходников.

        Returns:
            Ничего.
        """
        offenders = [
            title for title, body in _step_sections() if re.search(r"\.py\b|src/|:\d+", body)
        ]

        assert not offenders, (
            f"шаги, требующие знания кода: {offenders}. Владелец должен суметь "
            f"пройти процедуру, не зная, где какой модуль"
        )

    def test_steps_are_ordered(self) -> None:
        """Шаги пронумерованы по порядку — порядок не переставляется произвольно.

        Returns:
            Ничего.
        """
        numbers = [
            int(m.group(1)) for m in (re.match(r"Шаг (\d+)", t) for t, _ in _step_sections()) if m
        ]

        assert numbers == sorted(numbers), f"шаги идут не по порядку: {numbers}"
        assert numbers[0] == 1, "нумерация шагов начинается не с первого"
