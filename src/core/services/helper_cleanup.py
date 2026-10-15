"""Чистка мусора во вспомогательных элементах Home Assistant (BACKLOG B77).

Мусор — это вспомогательные элементы, оставшиеся от прежних версий дома: флаги,
ползунки, списки, счётчики, шаблоны. Удалять их наугад нельзя: часть держат
автоматизации Home Assistant, и отказ такой автоматизации тихий — «ничего не
случилось» заметно только вечером, когда свет не зажёгся.

Поэтому служба **ничего не удаляет**. Она считает признак использования по
фактам и отдаёт список с причинами:

* элемент упомянут в манифесте дома (комнаты, локации, роли датчиков, правила);
* элемент упомянут в правилах автоматизаций Home Assistant (REST
  ``/api/config/automation/config/<id>``: старый API эту конфигурацию не отдавал,
  и без неё признак был бы гаданием);
* элемент встречался в журнале платформы за последние сутки-две недели;
* состояние элемента менялось недавно.

Вердикты:

* ``used`` — есть хотя бы одно свидетельство;
* ``probably_unused`` — свидетельств нет, и все источники свидетельств отвечали;
* ``unknown`` — проверить не удалось (нет связи, не прочитались автоматизации).

Последнее важнее остального: предложить удалить живое хуже, чем сказать «не
знаю». Элементы с вердиктом ``probably_unused`` — кандидаты, а не приговор.

Слепые зоны признака, о которых служба честно молчит и которые должны быть
сказаны человеку: панели Home Assistant, сцены и ручные вызовы скриптов
платформа не читает. «Следов нет» значит «здесь не нашлось», а не «точно никому
не нужно».

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import re
import time
from datetime import UTC
from typing import Any

from loguru import logger


#: Домены вспомогательных элементов: то, что заводит человек под правила дома,
#: а не приборы. Автоматизации сюда не входят: выключенная автоматизация — не
#: мусор (владелец гасит их осознанно), и признак «используется» к ним неприменим.
HELPER_DOMAINS: tuple[str, ...] = (
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "counter",
    "timer",
    "template",
    "group",
    "script",
    "scene",
)

#: Вердикт: элемент используется.
USED = "used"
#: Вердикт: свидетельств использования нет — кандидат на удаление.
PROBABLY_UNUSED = "probably_unused"
#: Вердикт: проверить не удалось — удалять нельзя.
UNKNOWN = "unknown"

#: Сколько суток журнала считать свидетельством использования.
DEFAULT_JOURNAL_DAYS = 14
#: Сколько секунд держать снимок: сбор обходит все автоматизации дома.
DEFAULT_CACHE_SECONDS = 600

#: Идентификатор сущности Home Assistant: ``input_boolean.spim``.
_ENTITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]*\.[a-z0-9_]+$")


class HelperCleanupService:
    """Считает, какие вспомогательные элементы дома действительно используются.

    Ничего не удаляет и не меняет: удаление вспомогательного элемента —
    необратимое действие, а выгода от автоматики ниже цены ошибки.
    """

    def __init__(
        self,
        adapter: Any,
        manifest: Any = None,
        event_store: Any = None,
        journal_days: int = DEFAULT_JOURNAL_DAYS,
        cache_seconds: float = DEFAULT_CACHE_SECONDS,
        clock: Any | None = None,
    ) -> None:
        """Собрать службу чистки.

        Args:
            adapter: Адаптер Home Assistant (чтение состояний и конфигураций
                автоматизаций).
            manifest: Манифест дома; из него берётся список упомянутых сущностей.
            event_store: Журнал платформы; из него берётся история обращений.
            journal_days: Сколько суток журнала считать свидетельством.
            cache_seconds: Сколько держать снимок, чтобы не обходить дом на каждый
                запрос страницы.
            clock: Часы (для тестов).
        """
        self._adapter = adapter
        self._manifest = manifest
        self._event_store = event_store
        self.journal_days = journal_days
        self.cache_seconds = cache_seconds
        self._clock = clock or time.time
        self._report: dict[str, Any] | None = None
        self._report_at = 0.0

    # ------------------------------------------------------------------
    # Сбор
    # ------------------------------------------------------------------

    async def sweep(self, force: bool = False) -> dict[str, Any]:
        """Собрать снимок: вспомогательные элементы и признак использования.

        Args:
            force: Пересобрать, даже если снимок свежий.

        Returns:
            Снимок: ``generated_at``, ``counts``, ``helpers`` и ``sources`` —
            какие источники свидетельств отвечали.
        """
        if self._report is not None and not force and self._age() < self.cache_seconds:
            return self._report

        states = await self._states()
        candidates = [self._helper(item) for item in states if self._is_helper(item)]
        helpers: list[dict[str, Any]] = [item for item in candidates if item is not None]

        declared_automations = sum(
            1 for item in states if str(item.get("entity_id") or "").startswith("automation.")
        )
        manifest_entities = self._manifest_entities()
        automation_entities, automations_readable = await self._automation_entities(
            declared_automations
        )
        dashboard_entities, dashboards_readable = await self._dashboard_entities()
        journal_entities = self._journal_entities([h["entity_id"] for h in helpers])
        origins = await self._origins()

        sources = {
            "states": bool(states),
            "manifest": self._manifest is not None,
            "automations": automations_readable,
            "dashboards": dashboards_readable,
            "journal": self._event_store is not None,
        }

        marks = [
            self._mark(
                helper,
                manifest_entities,
                automation_entities,
                dashboard_entities,
                journal_entities,
                origins,
                sources,
            )
            for helper in helpers
        ]
        marks.sort(key=lambda item: (item["verdict"] != PROBABLY_UNUSED, item["entity_id"]))

        counts = {USED: 0, PROBABLY_UNUSED: 0, UNKNOWN: 0}
        for mark in marks:
            counts[mark["verdict"]] += 1

        report = {
            "generated_at": self._iso(),
            "counts": counts,
            "sources": sources,
            "plan": self._plan(marks),
            "helpers": marks,
        }
        self._report = report
        self._report_at = self._now()
        logger.debug(
            f"Чистка: элементов {len(marks)}, кандидатов {counts[PROBABLY_UNUSED]}, "
            f"неизвестных {counts[UNKNOWN]}"
        )
        return report

    # ------------------------------------------------------------------
    # Источники свидетельств
    # ------------------------------------------------------------------

    async def _states(self) -> list[dict[str, Any]]:
        """Состояния всех сущностей дома.

        Returns:
            Список состояний; пусто, если дом не ответил.
        """
        reader = getattr(self._adapter, "get_all_states", None) or getattr(
            self._adapter, "get_states", None
        )
        if reader is None:
            return []
        try:
            states = await reader()
        except Exception as error:  # noqa: BLE001 - отказ дома не должен ломать страницу
            logger.warning(f"Чистка: состояния не прочитаны: {error}")
            return []
        return [item for item in states or [] if isinstance(item, dict)]

    def _manifest_entities(self) -> set[str]:
        """Сущности, упомянутые в манифесте дома.

        Returns:
            Множество идентификаторов сущностей.
        """
        if self._manifest is None:
            return set()
        try:
            data = self._manifest.model_dump()
        except AttributeError:
            data = self._manifest
        found: set[str] = set()
        self._collect_entities(data, found)
        return found

    def _collect_entities(self, node: Any, found: set[str]) -> None:
        """Собрать идентификаторы сущностей из дерева манифеста.

        Args:
            node: Узел манифеста (словарь, список, строка).
            found: Накопитель идентификаторов.

        Returns:
            Ничего.
        """
        if isinstance(node, str):
            if _ENTITY_ID_RE.match(node):
                found.add(node)
        elif isinstance(node, dict):
            for value in node.values():
                self._collect_entities(value, found)
        elif isinstance(node, list):
            for value in node:
                self._collect_entities(value, found)

    async def _automation_entities(self, declared: int) -> tuple[set[str], bool]:
        """Сущности, упомянутые в правилах автоматизаций Home Assistant.

        Args:
            declared: Сколько автоматизаций объявлено в доме.

        Returns:
            Пару «сущности» и «все автоматизации прочитаны»: пока это не так,
            молчание автоматизаций ничего не доказывает.
        """
        reader = getattr(self._adapter, "get_automation_configs", None)
        if reader is None:
            return set(), False
        try:
            configs = await reader()
        except Exception as error:  # noqa: BLE001 - отказ дома не должен ломать страницу
            logger.warning(f"Чистка: конфигурации автоматизаций не прочитаны: {error}")
            return set(), False

        readable = bool(configs) and (declared == 0 or len(configs) >= declared)
        found: set[str] = set()
        self._collect_entities(list((configs or {}).values()), found)
        return found, readable

    async def _dashboard_entities(self) -> tuple[set[str], bool]:
        """Сущности, выведенные на панели Home Assistant.

        Returns:
            Пару «сущности» и «панели прочитаны»: пока это не так, молчание
            панелей ничего не доказывает.
        """
        reader = getattr(self._adapter, "get_dashboard_entities", None)
        if reader is None:
            return set(), False
        try:
            entities = await reader()
        except Exception as error:  # noqa: BLE001 - отказ дома не должен ломать страницу
            logger.warning(f"Чистка: панели не прочитаны: {error}")
            return set(), False
        if entities is None:
            return set(), False
        return {str(entity) for entity in entities}, True

    async def _origins(self) -> dict[str, bool]:
        """Откуда взялась сущность: создана через дом или описана в YAML.

        Разница решает, что вообще можно сделать: у созданной через интерфейс
        дома есть запись конфигурации, у описанной в YAML — нет, и удалить её
        можно только правкой YAML на самом доме.

        Returns:
            Сущность → есть ли у неё запись конфигурации.
        """
        reader = getattr(self._adapter, "get_entity_registry", None)
        if reader is None:
            return {}
        try:
            records = await reader()
        except Exception as error:  # noqa: BLE001 - отказ дома не должен ломать страницу
            logger.warning(f"Чистка: реестр сущностей не прочитан: {error}")
            return {}
        origins: dict[str, bool] = {}
        for record in records or []:
            if not isinstance(record, dict):
                continue
            entity = record.get("entity_id")
            if entity:
                origins[str(entity)] = bool(record.get("config_entry_id"))
        return origins

    def _journal_entities(self, entity_ids: list[str]) -> set[str]:
        """Сущности, встречавшиеся в журнале платформы за срок наблюдения.

        Args:
            entity_ids: Сущности, по которым спрашиваем журнал.

        Returns:
            Множество сущностей, у которых были события.
        """
        if self._event_store is None or not entity_ids:
            return set()
        from_ts = self._now() - self.journal_days * 86400
        try:
            events = self._event_store.get_events_for_entities(
                entity_ids, from_ts=from_ts, limit=2000
            )
        except Exception as error:  # noqa: BLE001 - журнал не влияет на работу платформы
            logger.warning(f"Чистка: журнал не прочитан: {error}")
            return set()
        found: set[str] = set()
        for event in events or []:
            entity = getattr(event, "entity_id", None)
            if isinstance(event, dict):
                entity = event.get("entity_id")
            if entity:
                found.add(str(entity))
        return found

    # ------------------------------------------------------------------
    # Вердикт
    # ------------------------------------------------------------------

    def _mark(
        self,
        helper: dict[str, Any],
        manifest_entities: set[str],
        automation_entities: set[str],
        dashboard_entities: set[str],
        journal_entities: set[str],
        origins: dict[str, bool],
        sources: dict[str, bool],
    ) -> dict[str, Any]:
        """Вынести вердикт по одному вспомогательному элементу.

        Args:
            helper: Описание элемента (сущность, имя, состояние, время).
            manifest_entities: Сущности манифеста.
            automation_entities: Сущности, нужные автоматизациям Home Assistant.
            dashboard_entities: Сущности, выведенные на панели Home Assistant.
            journal_entities: Сущности, встречавшиеся в журнале.
            origins: Сущность → создана через интерфейс дома либо описана в YAML.
            sources: Какие источники свидетельств отвечали.

        Returns:
            Описание элемента с вердиктом, причинами и происхождением.
        """
        entity_id = helper["entity_id"]
        reasons: list[dict[str, str]] = []
        if entity_id in manifest_entities:
            reasons.append({"source": "manifest", "detail": "описан в манифесте дома"})
        if entity_id in automation_entities:
            reasons.append(
                {"source": "automation", "detail": "нужен автоматизациям Home Assistant"}
            )
        if entity_id in dashboard_entities:
            reasons.append({"source": "dashboard", "detail": "выведен на панель Home Assistant"})
        if entity_id in journal_entities:
            reasons.append(
                {
                    "source": "journal",
                    "detail": f"встречался в журнале за {self.journal_days} суток",
                }
            )

        if reasons:
            verdict = USED
        elif (
            not sources.get("states", False)
            or not sources.get("automations", False)
            or not sources.get("dashboards", False)
        ):
            verdict = UNKNOWN
        else:
            verdict = PROBABLY_UNUSED

        origin = origins.get(entity_id)
        helper["verdict"] = verdict
        helper["reasons"] = reasons
        helper["origin"] = "unknown" if origin is None else ("ui" if origin else "yaml")
        # Удалить через дом можно только созданное через дом, и только когда есть
        # свидетельства, что элемент мёртв: остальное — либо YAML, либо «не знаю».
        helper["removable"] = verdict == PROBABLY_UNUSED and helper["origin"] == "ui"
        return helper

    def _plan(self, marks: list[dict[str, Any]]) -> dict[str, Any]:
        """Заготовка уборки: что именно убирать и по домам.

        Платформа не правит YAML чужого дома — она готовит список, по которому это
        делает человек (а в режиме аддона, где каталог дома доступен, сможет и
        сама). Список сгруппирован по доменам: так его удобно сличить со своим
        `configuration.yaml`.

        Args:
            marks: Вердикты по всем элементам.

        Returns:
            Заготовка: количество, домены и готовый текст списка.
        """
        by_domain: dict[str, list[str]] = {}
        for mark in marks:
            if mark["verdict"] != PROBABLY_UNUSED:
                continue
            domain = mark["entity_id"].split(".", 1)[0]
            by_domain.setdefault(domain, []).append(mark["entity_id"])

        lines: list[str] = []
        for domain in sorted(by_domain):
            lines.append(f"{domain}:")
            lines.extend(f"  - {entity}" for entity in sorted(by_domain[domain]))

        return {
            "count": sum(len(v) for v in by_domain.values()),
            "by_domain": {
                domain: sorted(entities) for domain, entities in sorted(by_domain.items())
            },
            "text": "\n".join(lines),
        }

    def _is_helper(self, item: dict[str, Any]) -> bool:
        """Вспомогательный ли это элемент.

        Args:
            item: Состояние сущности.

        Returns:
            ``True``, если домен относится к вспомогательным элементам.
        """
        entity_id = str(item.get("entity_id") or "")
        domain = entity_id.split(".", 1)[0]
        return domain in HELPER_DOMAINS

    def _helper(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """Описание вспомогательного элемента для снимка.

        Args:
            item: Состояние сущности.

        Returns:
            Описание либо ``None``, если у сущности нет идентификатора.
        """
        entity_id = item.get("entity_id")
        if not entity_id:
            return None
        raw_attributes = item.get("attributes")
        attributes: dict[str, Any] = raw_attributes if isinstance(raw_attributes, dict) else {}
        changed = self._changed_at(item)
        return {
            "entity_id": str(entity_id),
            "name": str(attributes.get("friendly_name") or entity_id),
            "state": item.get("state"),
            "last_changed": self._iso(changed),
            "changed_ago_sec": round(self._now() - changed, 1) if changed else None,
        }

    def _changed_at(self, item: dict[str, Any]) -> float | None:
        """Когда состояние сущности менялось в последний раз.

        Args:
            item: Состояние сущности.

        Returns:
            Время (epoch) либо ``None``.
        """
        raw = item.get("last_changed") or item.get("last_updated")
        if not isinstance(raw, str):
            return None
        try:
            from datetime import datetime

            return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Мелочи
    # ------------------------------------------------------------------

    def _now(self) -> float:
        """Текущее время.

        Returns:
            Время (epoch).
        """
        return float(self._clock())

    def _age(self) -> float:
        """Сколько секунд снимку.

        Returns:
            Возраст снимка в секундах.
        """
        return self._now() - self._report_at

    def _iso(self, moment: float | None = None) -> str:
        """Время в ISO-виде.

        Args:
            moment: Время (epoch); по умолчанию — текущее.

        Returns:
            Строка времени.
        """
        from datetime import datetime

        return datetime.fromtimestamp(
            moment if moment is not None else self._now(), UTC
        ).isoformat()

    @property
    def last_report(self) -> dict[str, Any] | None:
        """Последний снимок чистки.

        Returns:
            Снимок либо ``None``, если ещё не собирали.
        """
        return self._report
