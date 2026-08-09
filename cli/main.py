"""CLI платформы: валидация, генерация JSON Schema, создание инстанса."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import click
import yaml
from pydantic import ValidationError

from shplatform.schema import Manifest
from shplatform.validator import validate_manifest


def _load_manifest(path: Path) -> Manifest:
    if not path.exists():
        raise click.ClickException(f"Файл не найден: {path}")

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))

    try:
        manifest = Manifest.model_validate(raw)
    except ValidationError as exc:
        msgs = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            msgs.append(f"  {loc}: {err['msg']}")
        raise click.ClickException(
            "Структурные ошибки манифеста:\n" + "\n".join(msgs)
        )
    return manifest


@click.group()
def cli() -> None:
    """Инструменты платформы умного дома."""


@cli.command()
@click.argument("manifest_path", type=click.Path(exists=False))
def validate(manifest_path: str) -> None:
    """Проверить манифест: структура + cross-references."""
    path = Path(manifest_path)
    manifest = _load_manifest(path)

    report = validate_manifest(manifest)
    if report.ok:
        click.secho(f"OK: Манифест '{path}' корректен", fg="green")
        return

    click.secho(f"FAIL: Найдено проблем: {len(report.issues)}", fg="red")
    for issue in report.issues:
        click.echo(f"  {issue}")
    sys.exit(1)


@cli.command()
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Сохранить JSON Schema в файл")
def schema(output: str | None) -> None:
    """Вывести JSON Schema манифеста."""
    js = Manifest.model_json_schema()
    text = json.dumps(js, indent=2, ensure_ascii=False)
    if output:
        Path(output).write_text(text, encoding="utf-8")
        click.secho(f"OK: JSON Schema сохранена в {output}", fg="green")
    else:
        click.echo(text)


if __name__ == "__main__":
    cli()
