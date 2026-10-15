"""Тревоги дома: молчащие датчики и недоступные приборы (спека 017, FR-011).

Тревога — это то, что требует внимания, в отличие от обычного состояния.
Считаются на сервере, чтобы все клиенты видели одну правду: молчание датчика
(``stale``), недоступность датчика (``unavailable``) и недоступность прибора.
Мёртвый датчик не попадает в производные локации — это уже делает снимок
(спека 016), здесь же он становится видимым отдельной строкой.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from services.watchdog import MISMATCH_FAULT_REASONS, MISMATCH_MANUAL_OVERRIDE


#: Вид тревоги.
KIND_STALE_SENSOR = "stale_sensor"
KIND_UNAVAILABLE_SENSOR = "unavailable_sensor"
KIND_UNAVAILABLE_DEVICE = "unavailable_device"
# Расхождение «автомат ↔ прибор» (концепция §7, п. 4): решение есть, а прибор
# его не отражает — команда не применилась либо прибор недоступен.
KIND_DEVICE_MISMATCH = "device_mismatch"
# Проблема из обхода дома (BACKLOG F6): прибор не отвечает, показание устарело,
# батарейка на исходе. Обход смотрит весь дом, а не только приборы манифеста.
KIND_HEALTH = "health_problem"

#: Значимость проблем обхода: «вмешаться» против «знать».
HEALTH_SEVERITY = {
    "unavailable": "warning",
    "low_battery": "warning",
    "stale": "info",
}

#: Значимость тревоги: ``warning`` — вмешаться, ``info`` — знать.
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"


class Alert(BaseModel):
    """Тревога, требующая внимания инженера.

    Attributes:
        kind: Вид (молчание, недоступность датчика или прибора).
        subject: Кого касается — сущность или устройство.
        severity: Значимость.
        detail: Объяснение человеческим языком.
        at: Время, к которому относится (может отсутствовать).
    """

    kind: str
    subject: str
    severity: str
    detail: str
    at: str | None = None


def build_alerts(locations: list[dict[str, Any]], devices: list[dict[str, Any]]) -> list[Alert]:
    """Собрать тревоги из снимков локаций и списка устройств.

    Args:
        locations: Снимки локаций (``LocationSnapshot.model_dump(mode="json")``).
        devices: Представления устройств (см. ``overview``).

    Returns:
        Список тревог; порядок — сначала значимые, затем информационные.
    """
    alerts: list[Alert] = []

    for snapshot in locations:
        place = snapshot.get("location") or {}
        place_name = place.get("name") or place.get("id") or "локация"
        readings: dict[str, list[dict[str, Any]]] = snapshot.get("readings") or {}
        for role_readings in readings.values():
            for reading in role_readings:
                entity_id = reading.get("entity_id") or ""
                role = _role_label(reading.get("role"))
                if not reading.get("available", True):
                    alerts.append(
                        Alert(
                            kind=KIND_UNAVAILABLE_SENSOR,
                            subject=entity_id,
                            severity=SEVERITY_WARNING,
                            detail=f"{place_name}: {role} недоступен",
                            at=reading.get("at"),
                        )
                    )
                elif reading.get("stale"):
                    alerts.append(
                        Alert(
                            kind=KIND_STALE_SENSOR,
                            subject=entity_id,
                            severity=SEVERITY_INFO,
                            detail=f"{place_name}: {role} молчит",
                            at=reading.get("at"),
                        )
                    )

    for device in devices:
        status = device.get("status")
        if status and status != "available":
            alerts.append(
                Alert(
                    kind=KIND_UNAVAILABLE_DEVICE,
                    subject=device.get("ha_entity_id") or device.get("id") or "",
                    severity=SEVERITY_WARNING,
                    detail=f"{device.get('name') or device.get('id')}: прибор {status}",
                )
            )

    return alerts


#: Виды расхождения «автомат ↔ прибор» → человеческое объяснение.
MISMATCH_LABELS = {
    "device_on_decision_off": "горит, хотя решение — выключено",
    "device_off_decision_on": "не горит, хотя решение — включить",
    "device_unavailable": "не отвечает",
}

#: Те же виды для штор: про штору «горит» не говорят, у неё положение.
MISMATCH_LABELS_COVER = {
    "device_on_decision_off": "открыта, хотя решение — закрыть",
    "device_off_decision_on": "закрыта, хотя решение — открыть",
    "device_unavailable": "не отвечает",
}


def _mismatch_label(subject: str, reason: str) -> str:
    """Назвать расхождение словами, подходящими прибору.

    Args:
        subject: Сущность прибора.
        reason: Вид расхождения.

    Returns:
        Объяснение человеческим языком.
    """
    if reason == MISMATCH_MANUAL_OVERRIDE:
        return "человек вмешался: автоматика уступает по правилу оверрайда"
    labels = MISMATCH_LABELS_COVER if subject.startswith("cover.") else MISMATCH_LABELS
    return labels.get(reason, reason)


def alerts_from_watchdog(snapshot: Any) -> list[Alert]:
    """Собрать тревоги о расхождении «автомат ↔ прибор» из снимка сторожа.

    Сторож читает фактическое состояние прибора у Home Assistant и называет
    расхождение (``device_state``/``mismatch``). Здесь оно превращается в
    тревогу, чтобы его видел не только журнал: «прибор горит, а решение —
    выключено» — это то, что требует внимания, а не молчаливое согласие.

    Args:
        snapshot: Последний снимок сторожа (``FsmSnapshot``) либо ``None``.

    Returns:
        Список тревог; пустой, если сторожа нет или расхождений нет.
    """
    if snapshot is None:
        return []
    alerts: list[Alert] = []
    for entry in getattr(snapshot, "entries", ()) or ():
        reason = getattr(entry, "mismatch_reason", None)
        if not reason:
            continue
        subject = getattr(entry, "device", "") or getattr(entry, "entity_id", "")
        explained = _mismatch_label(str(subject), str(reason))
        alerts.append(
            Alert(
                kind=KIND_DEVICE_MISMATCH,
                subject=subject,
                # Уступка человеку — «знать», а не «вмешаться»: прибор не сломан,
                # автоматика сама обязана уступать на срок оверрайда (§7, п. 2).
                severity=(
                    SEVERITY_WARNING if str(reason) in MISMATCH_FAULT_REASONS else SEVERITY_INFO
                ),
                detail=(
                    f"{subject}: {explained} "
                    f"(Home Assistant сообщает: {getattr(entry, 'device_state', None)})"
                ),
                at=None,
            )
        )
    return alerts


#: Роли датчиков, которые показываются словами, а не идентификатором Home Assistant.
ROLE_LABELS = {
    "temperature": "температура",
    "humidity": "влажность",
    "motion": "движение",
    "contact": "контакт",
    "illuminance": "освещённость",
    "lux": "освещённость",
    "pressure": "давление",
    "wind": "ветер",
    "rain": "дождь",
    "uv": "УФ-излучение",
    "co2": "CO₂",
    "soil_moisture": "влага почвы",
    "soil_conductivity": "проводимость почвы",
    "battery": "батарея",
    "power": "мощность",
}


def _role_label(role: Any) -> str:
    """Назвать роль датчика по-русски.

    Args:
        role: Роль из снимка локации.

    Returns:
        Русское название роли либо исходная строка, если роль неизвестна.
    """
    if not role:
        return "датчик"
    return ROLE_LABELS.get(str(role), str(role))


def alerts_from_health(report: Any) -> list[Alert]:
    """Собрать тревоги из обхода дома (BACKLOG F6).

    Обход отвечает на вопрос, который панель приборов манифеста не видит: что
    происходит со **всем** домом — не отвечает ли датчик за пределами комнат,
    не села ли батарейка, не замолчал ли прибор, который обязан шлать показания.

    Args:
        report: Снимок обхода (``last_report``) либо ``None``.

    Returns:
        Список тревог.
    """
    if not report:
        return []
    alerts: list[Alert] = []
    for problem in report.get("problems") or []:
        if not isinstance(problem, dict):
            continue
        kind = str(problem.get("kind") or "")
        alerts.append(
            Alert(
                kind=KIND_HEALTH,
                subject=str(problem.get("subject") or ""),
                severity=HEALTH_SEVERITY.get(kind, SEVERITY_INFO),
                detail=str(problem.get("detail") or kind),
                at=problem.get("at"),
            )
        )
    return alerts
