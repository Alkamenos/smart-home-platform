"""Models and errors for the FSM factory (spec 018, T059)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class TemplateLoadError(Exception):
    """Шаблон поведения нельзя собрать.

    Отдельный тип нужен, чтобы отличить «опечатка в имени действия» от
    «сломан сам Python-код». Первое — ошибка владельца манифеста, и её надо
    показать с именем устройства; второе — дефект платформы, и его надо
    чинить, а не показывать как «устройство пропущено».
    """


class MissingTemplateError(TemplateLoadError, FileNotFoundError):
    """Шаблон поведения не найден в каталоге ``features/``.

    Наследует и ``TemplateLoadError`` (поведение не собрано — устройство
    пропускается, платформа работает), и ``FileNotFoundError``: отсутствие
    файла шаблона было и остаётся ошибкой о файле, о которой уже знают
    вызывающие (`tests/test_fsm_factory.py:162`).
    """


@dataclass(frozen=True)
class SkippedBehavior:
    """Поведение, которое не удалось собрать.

    Attributes:
        device_id: Устройство, ради которого поведение собиралось.
        template: Имя шаблона поведения.
        reason: Что именно не так, с именем опечатки.
    """

    device_id: str
    template: str
    reason: str


@dataclass
class LoadReport:
    """Что получилось и что не получилось при сборке манифеста.

    Нужен для устойчивой загрузки: решение владельца 2026-10-10 — «платформа
    должна быть максимально устойчивой, но при этом сообщать о любых
    проблемах». Устойчивость без отчёта — это молчаливая поломка, поэтому
    пропуски обязаны быть видны и в журнале, и в готовности.
    """

    loaded: int = 0
    """Сколько определений собрано."""

    skipped: list[SkippedBehavior] = field(default_factory=list)
    """Какие поведения не собраны и почему."""

    @property
    def ok(self) -> bool:
        """Нет ли пропусков.

        Returns:
            True, когда всё собралось.
        """
        return not self.skipped

    def as_dict(self) -> dict[str, Any]:
        """Сведения о загрузке для сводки готовности.

        Returns:
            Словарь со счётчиками и списком пропусков.
        """
        return {
            "loaded": self.loaded,
            "ok": self.ok,
            "skipped": [
                {"device_id": item.device_id, "template": item.template, "reason": item.reason}
                for item in self.skipped
            ],
        }


# Каталог с YAML-шаблонами автоматизаций: src/features/
