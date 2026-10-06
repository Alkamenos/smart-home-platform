"""Пять слоёв проверки параметров поведения (пункт 4 веб-плана).

Проверка идёт по контракту шаблонов, а не по захардкоженным правилам: иначе
форма и сервер разойдутся, а это тот же класс расхождения, что закрыт в #65,
#66 и #68.

Каждый слой проверяется отдельным тестом с тем же кодом правки, что и в бою:
исключение поднимается в конкретном слое, и проверка убеждается, что сообщение
называет именно этот слой. Иначе тест прошёл бы и при переставленных слоях.
"""

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from core.behavior_params import ParamError, load_contract, validate_behavior


@pytest.fixture(scope="module")
def contract() -> dict:
    """Контракт шаблонов.

    Returns:
        Разобранный CONTRACT.yaml.
    """
    return load_contract()


class TestLayer1UnknownParam:
    """Слой 1 — параметр должен быть описан в контракте."""

    def test_should_reject_undeclared_param(self, contract: dict) -> None:
        """Неизвестный параметр отвергается, а не игнорируется.

        Args:
            contract: Контракт шаблонов.
        """
        with pytest.raises(ParamError, match="слой 1"):
            validate_behavior("lighting", {"не_существует": 1}, contract)

    def test_should_name_declared_params_in_error(self, contract: dict) -> None:
        """В ошибке перечислены допустимые параметры — иначе пользователь гадает.

        Args:
            contract: Контракт шаблонов.
        """
        with pytest.raises(ParamError) as caught:
            validate_behavior("lighting", {"не_существует": 1}, contract)
        assert "brightness" in str(caught.value)


class TestLayer2Type:
    """Слой 2 — тип значения."""

    def test_should_reject_float_for_int_param(self, contract: dict) -> None:
        """Дробное значение не принимается для целочисленного параметра.

        Args:
            contract: Контракт шаблонов.
        """
        with pytest.raises(ParamError, match="слой 2"):
            validate_behavior("lighting", {"brightness": 2.5}, contract)

    def test_should_reject_bool_for_int_param(self, contract: dict) -> None:
        """`true` — это не 1: в Python bool является подклассом int.

        Args:
            contract: Контракт шаблонов.
        """
        with pytest.raises(ParamError, match="слой 2"):
            validate_behavior("lighting", {"brightness": True}, contract)

    def test_should_accept_int_for_float_param(self, contract: dict) -> None:
        """Целое для дробного параметра допустимо.

        Args:
            contract: Контракт шаблонов.
        """
        assert validate_behavior("humidity_ventilation", {"humidity_threshold": 65}, contract) == []

    def test_should_reject_number_for_str_param(self, contract: dict) -> None:
        """Число не принимается для строкового параметра.

        Args:
            contract: Контракт шаблонов.
        """
        with pytest.raises(ParamError, match="слой 2"):
            validate_behavior("night_light", {"schedule": 2300}, contract)


class TestLayer3Range:
    """Слой 3 — числовой диапазон."""

    def test_should_reject_brightness_above_max(self, contract: dict) -> None:
        """Яркость выше 255 отвергается.

        Args:
            contract: Контракт шаблонов.
        """
        with pytest.raises(ParamError, match="слой 3"):
            validate_behavior("lighting", {"brightness": 300}, contract)

    def test_should_accept_boundary_values(self, contract: dict) -> None:
        """Границы диапазона допустимы.

        Args:
            contract: Контракт шаблонов.
        """
        assert validate_behavior("lighting", {"brightness": 0}, contract) == []
        assert validate_behavior("lighting", {"brightness": 255}, contract) == []


class TestLayer4Format:
    """Слой 4 — формат строки."""

    @pytest.mark.parametrize("value", ["23-07", "23:00-7:00", "24:00-07:00", "", "вечер"])
    def test_should_reject_malformed_schedule(self, contract: dict, value: str) -> None:
        """Окно расписания должно быть ровно «ЧЧ:ММ-ЧЧ:ММ».

        Args:
            contract: Контракт шаблонов.
            value: Негодное значение.
        """
        with pytest.raises(ParamError, match="слой 4"):
            validate_behavior("night_light", {"schedule": value}, contract)

    def test_should_accept_valid_schedule(self, contract: dict) -> None:
        """Корректное окно принимается.

        Args:
            contract: Контракт шаблонов.
        """
        assert validate_behavior("night_light", {"schedule": "23:00-07:00"}, contract) == []


class TestLayer5ConsistencyAndReference:
    """Слой 5 — связность значений и существование ссылки."""

    def test_should_reject_zero_schedule_window(self, contract: dict) -> None:
        """Окно, равное самому себе, бессмысленно и отвергается.

        Args:
            contract: Контракт шаблонов.
        """
        with pytest.raises(ParamError, match="слой 5"):
            validate_behavior("night_light", {"schedule": "23:00-23:00"}, contract)

    def test_should_reject_unknown_template(self, contract: dict) -> None:
        """Поведение ссылается на несуществующий шаблон.

        Args:
            contract: Контракт шаблонов.
        """
        with pytest.raises(ParamError, match="слой 5"):
            validate_behavior("нет_такого_шаблона", {}, contract)

    def test_should_reject_unknown_template_even_with_empty_params(self, contract: dict) -> None:
        """Шаблон проверяется первым — пустые параметры не отменяют проверку.

        Args:
            contract: Контракт шаблонов.
        """
        with pytest.raises(ParamError, match="слой 5"):
            validate_behavior("нет_такого_шаблона", {}, contract)


class TestInertParamsAreAcceptedButReported:
    """Инертный параметр принимается, но помечается."""

    def test_should_report_inert_params_without_failing(self, contract: dict) -> None:
        """Инертный параметр не роняет запрос — иначе правка манифеста сломается.

        Args:
            contract: Контракт шаблонов.
        """
        notes = validate_behavior("lighting", {"motion_timeout_sec": 180}, contract)
        assert notes == ["motion_timeout_sec"], (
            "инертный параметр должен возвращаться замечанием, а не ошибкой"
        )

    def test_should_not_report_effective_params(self, contract: dict) -> None:
        """Рабочие параметры замечанием не сопровождаются.

        Args:
            contract: Контракт шаблонов.
        """
        assert validate_behavior("lighting", {"brightness": 200}, contract) == []


class TestEmptyMeansDefault:
    """Пустое поле означает «взять значение по умолчанию»."""

    def test_should_accept_behavior_without_params(self, contract: dict) -> None:
        """Поведение без параметров — обычный случай, а не ошибка.

        Args:
            contract: Контракт шаблонов.
        """
        assert validate_behavior("lighting", {}, contract) == []

    def test_should_accept_only_declared_params_present(self, contract: dict) -> None:
        """Частично заполненные параметры допустимы.

        Args:
            contract: Контракт шаблонов.
        """
        assert validate_behavior("climate_control", {"target_temp": 22.0}, contract) == [
            "target_temp"
        ]
