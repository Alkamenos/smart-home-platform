"""FSM creation from manifest for the FSM factory (spec 018, T059).

Extracted from FSMFactory: walking manifest behaviors, subscribing sensor events
and building the load report.
"""

# mypy: disable-error-code="attr-defined"

from __future__ import annotations

from typing import Any

from loguru import logger

from core.definitions import YAMLFSMDefinition
from core.fsm.engine import FSMDefinition
from core.fsm.factory_models import (
    LoadReport,
    MissingTemplateError,
    SkippedBehavior,
    TemplateLoadError,
)
from core.models.manifest import BehaviorConfig


class FsmFactoryCreationMixin:
    """Create FSM definitions from manifest behaviors."""

    def create_from_behavior(
        self,
        device_id: str,
        behavior: BehaviorConfig,
        room_id: str | None = None,
    ) -> list[FSMDefinition]:
        """
        Создать FSM из одного поведения.

        Args:
            device_id: ID устройства.
            behavior: Конфигурация поведения.
            room_id: Комната устройства из манифеста. Нужна условиям, которые
                решают по-разному для разных комнат (ночью свет разрешён в
                санузле и запрещён в спальне).

        Returns:
            list[FSMDefinition]: Список созданных определений FSM.
        """
        definitions = []

        try:
            # Загружаем шаблон
            template_data = self._load_template(behavior.template)
            if room_id is not None:
                template_data["room"] = room_id

            # Применяем параметры
            modified_data = self._apply_params_to_template(
                template_data,
                behavior.params,
                device_id,
                behavior.priority,
                device_id,
                behavior.template,
            )

            # Валидация через Pydantic
            yaml_def = YAMLFSMDefinition.model_validate(modified_data)

            # Проверка guard/action функций. Раньше здесь был WARNING, и это
            # означало худший исход: опечатка в имени действия проходила
            # молча, `action_fn` оставался `None`, переход выполнялся вхолостую,
            # а дом выглядел исправным. Теперь это ошибка сборки — поведение
            # пропускается, а причина попадает в отчёт о загрузке
            # (`research.md` D8, решение владельца 2026-10-10).
            problems = self._validate_guards_and_actions(yaml_def)
            if problems:
                raise TemplateLoadError("; ".join(problems))

            # Если в params есть schedule, создаем guard функцию для проверки расписания
            schedule_guard_fn = None
            if behavior.params and "schedule" in behavior.params:
                from core.guards.schedule_guard import is_within_schedule

                schedule_guard_fn = is_within_schedule

            # Преобразование в FSMDefinition (с применением schedule guard если есть)
            fsm_def = self._yaml_to_fsm_definition(yaml_def, schedule_guard_fn)
            definitions.append(fsm_def)

            logger.info(f"Loaded FSM for behavior '{behavior.template}' on device '{device_id}'")

            # Подписаться на события сенсоров из params, если есть event_bus
            if self._event_bus is not None and behavior.params:
                self._subscribe_to_sensor_events(
                    device_id, fsm_def.entity_id, behavior.params, behavior.template
                )

        except TemplateLoadError:
            raise
        except FileNotFoundError as e:
            logger.error(str(e))
            raise MissingTemplateError(str(e)) from e
        except Exception as e:
            logger.error(
                f"Failed to create FSM from behavior '{behavior.template}' for device '{device_id}': {e}"
            )
            raise TemplateLoadError(str(e)) from e

        return definitions

    def _subscribe_to_sensor_events(
        self,
        device_id: str,
        fsm_entity_id: str,
        params: dict[str, Any],
        template_name: str,
    ) -> None:
        """
        Подписать FSM на события сенсоров из params.

        Для lighting и night_light шаблонов подписывает на motion_sensor events.

        Args:
            device_id: ID устройства.
            fsm_entity_id: entity_id созданной FSM.
            params: Параметры поведения (могут содержать motion_sensor).
            template_name: Имя шаблона (lighting, night_light, etc.).
        """
        # Извлекаем motion_sensor из params, если есть
        motion_sensor = params.get("motion_sensor")

        if motion_sensor:
            # Создаем handler для этой FSM
            async def motion_event_handler(
                event_type: str,
                payload: dict[str, Any],
                trace_id: str | None = None,
            ) -> None:
                """Обработчик событий motion sensor."""
                log = logger.bind(trace_id=trace_id or "unknown")

                # Определяем тип события по состоянию сенсора
                new_state = payload.get("new_state", "")
                if new_state == "on":
                    trigger_event = "motion_detected"
                elif new_state == "off":
                    trigger_event = "motion_cleared"
                else:
                    log.debug(f"Unknown state {new_state} for motion sensor {motion_sensor}")
                    return

                log.info(
                    f"FSMFactory: Motion event from {motion_sensor} -> "
                    f"triggering '{trigger_event}' for FSM '{fsm_entity_id}'"
                )

                # Триггерим событие в FSM
                try:
                    await self._engine.trigger(
                        entity_id=fsm_entity_id,
                        event=trigger_event,
                        external_ctx=payload,
                        trace_id=trace_id,
                    )
                except Exception as e:
                    log.error(f"Failed to trigger FSM '{fsm_entity_id}': {e}")

            # Подписываемся с фильтром по entity_id сенсора
            self._event_bus.subscribe_with_filter(
                event_type="state_change",
                filter_params={"entity_id": motion_sensor},
                handler=motion_event_handler,
            )

            logger.info(
                f"Subscribed FSM '{fsm_entity_id}' to motion sensor '{motion_sensor}' "
                f"(template: {template_name})"
            )

    def create_from_manifest(self, manifest: Any) -> list[FSMDefinition]:
        """
        Создать FSM для всех устройств из манифеста.

        Для каждого устройства итерируется по device.behaviors,
        загружается соответствующий YAML-шаблон и создается отдельная FSM.

        Args:
            manifest: Валидированный объект Manifest.

        Returns:
            list[FSMDefinition]: Список всех созданных определений FSM.
        """
        definitions, report = self.create_from_manifest_reported(manifest)
        return definitions

    def create_from_manifest_reported(
        self, manifest: Any
    ) -> tuple[list[FSMDefinition], LoadReport]:
        """Создать FSM и вернуть отчёт о том, что не получилось.

        Изоляция по устройству, а не по шаблону: два устройства в одной комнате
        могут пользоваться одним шаблоном, и поломка одного поведения не должна
        выключать соседнее. Решение владельца 2026-10-10: «платформа должна быть
        максимально устойчивой, но при этом сообщать о любых проблемах» —
        обе половины обязательны, поэтому пропуски собираются в отчёт, а не
        только пишутся в журнал.

        Args:
            manifest: Валидированный объект Manifest.

        Returns:
            Кортеж из собранных определений и отчёта о пропусках.
        """
        all_definitions: list[FSMDefinition] = []
        report = LoadReport()

        for room_id, device in manifest.all_devices:
            device_id = device.id

            if not device.behaviors:
                # Прибор без поведений — это не поломка, а «только показ»:
                # владелец видит его на панели дома, а платформа им не
                # управляет (решение владельца 2026-10-18). Прежде это писала
                # предупреждением, и после добавления сорока приборов «показ»
                # журнал стал бы потоком ложных тревог.
                logger.debug(f"Устройство '{device_id}' без поведений: только показ")
                continue

            # Сортируем behaviors по приоритету (меньше = выше приоритет)
            sorted_behaviors = sorted(device.behaviors, key=lambda b: b.priority)

            logger.info(f"Processing device '{device_id}' with {len(sorted_behaviors)} behaviors")

            for behavior in sorted_behaviors:
                try:
                    definitions = self.create_from_behavior(
                        device_id,
                        self._with_house_rules(
                            behavior,
                            manifest.automation_rules,
                            getattr(manifest.instance, "time_zone", None),
                        ),
                        room_id,
                    )
                except Exception as exc:  # noqa: BLE001 — одно устройство не должно ронять дом
                    reason = str(exc) or type(exc).__name__
                    report.skipped.append(
                        SkippedBehavior(
                            device_id=device_id,
                            template=behavior.template,
                            reason=reason,
                        )
                    )
                    logger.error(
                        f"Поведение '{behavior.template}' устройства '{device_id}' "
                        f"пропущено: {reason}"
                    )
                    continue
                all_definitions.extend(definitions)

        report.loaded = len(all_definitions)
        if report.skipped:
            logger.error(
                f"Из манифеста не собрано {len(report.skipped)} поведений, "
                f"работают {report.loaded}: {report.as_dict()['skipped']}"
            )
        logger.info(
            f"Created {len(all_definitions)} FSM definitions from manifest "
            f"({len(report.skipped)} skipped)"
        )
        return all_definitions, report
