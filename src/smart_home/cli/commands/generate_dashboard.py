"""Генерация дашборда Home Assistant из манифеста (BACKLOG B8, enhancement 19).

Команда делает то же, что ``GET /api/v1/system/dashboard``: собирает панель из
дома — представления по комнатам и локациям, карточки датчиков, приборов и
автоматов. Отличие одно: не нужен запущенный контейнер и ничего не пишется в
дом — результат уходит в файл или в стандартный вывод.

#  Copyright 2026 Leonid Artemev
#  SPDX-License-Identifier: Apache-2.0
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml


#: Манифест по умолчанию — эталон боевого дома из репозитория.
#:
#: Боевой том (``deploy/docker/config/manifest.yaml``) в git не хранится по
#: правилам безопасности; эталон лежит в ``instances/``.
DEFAULT_MANIFEST = "instances/leonids_house_prod/manifest.yaml"


def _load_manifest(path: str) -> Any:
    """Прочитать и проверить манифест дома.

    Args:
        path: Путь к YAML-манифесту.

    Returns:
        Проверенная модель ``Manifest``.

    Raises:
        FileNotFoundError: Файла нет.
        yaml.YAMLError: Файл не разбирается как YAML.
        pydantic.ValidationError: Манифест не проходит проверку модели.
    """
    from core.models.manifest import Manifest

    manifest_path = Path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Манифест не найден: {path}")

    with open(manifest_path, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return Manifest.model_validate(data)


def _counts(config: dict[str, Any]) -> tuple[int, int]:
    """Посчитать представления и карточки.

    Args:
        config: Собранная конфигурация дашборда.

    Returns:
        Пара ``(представлений, карточек)``.
    """
    views = [view for view in config.get("views") or [] if isinstance(view, dict)]
    cards = sum(len(view.get("cards") or []) for view in views)
    return len(views), cards


def cmd_generate_dashboard(args: argparse.Namespace) -> int:
    """Собрать дашборд и записать его в файл или стандартный вывод.

    Args:
        args: Разобранные аргументы командной строки.

    Returns:
        Код возврата: 0 — успех, 1 — ошибка с названной причиной.
    """
    from dashboard.lovelace_generator import LovelaceGenerator

    try:
        manifest = _load_manifest(args.manifest)
    except FileNotFoundError as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    except yaml.YAMLError as error:
        print(f"Ошибка разбора YAML: {error}", file=sys.stderr)
        return 1
    except Exception as error:  # noqa: BLE001 — модель называет причину сама
        print(f"Манифест не прошёл проверку: {error}", file=sys.stderr)
        return 1

    if not manifest.all_places:
        print(
            "Ошибка: в манифесте нет ни комнат, ни локаций — дашборд собирать не из чего.",
            file=sys.stderr,
        )
        return 1

    config = LovelaceGenerator().generate(manifest)
    text = yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
    views, cards = _counts(config)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as handle:
            handle.write(text)
        print(f"Дашборд: {views} представлений, {cards} карточек. Записано: {output_path}")
    else:
        # В stdout — только YAML: вывод должен быть пригоден для перенаправления
        # в файл без служебных строк.
        print(text, end="")

    return 0


def setup_generate_dashboard_parser(subparsers: Any) -> None:
    """Зарегистрировать подкоманду ``generate-dashboard``.

    Args:
        subparsers: Объект подкоманд ``argparse``.
    """
    parser = subparsers.add_parser(
        "generate-dashboard",
        help="Собрать дашборд Home Assistant из манифеста",
        description=(
            "Собрать конфигурацию Lovelace из комнат и локаций манифеста. "
            "Результат — YAML для вставки в Home Assistant или файл."
        ),
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        default=DEFAULT_MANIFEST,
        help=f"Путь к манифесту (по умолчанию: {DEFAULT_MANIFEST})",
    )
    parser.add_argument(
        "--output",
        "-o",
        help="Файл для записи (по умолчанию — стандартный вывод)",
    )
    parser.set_defaults(func=cmd_generate_dashboard)
