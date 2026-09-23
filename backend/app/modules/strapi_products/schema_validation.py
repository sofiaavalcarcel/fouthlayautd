from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


SCHEMA_PATH = Path(__file__).with_name("strapi-product-schema.json")


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    with SCHEMA_PATH.open(encoding="utf-8") as source:
        return json.load(source)


def validate_product_payload(payload: dict[str, Any], schema_override: dict[str, Any] | None = None) -> list[str]:
    """Check a PDP update payload against the captured Strapi product/component schema."""
    schema = schema_override or _schema()
    errors: list[str] = []
    attributes = schema["product"]["attributes"]
    _validate_attributes(payload, attributes, schema.get("components", {}), "product", errors)
    return errors


def product_schema_version(schema: dict[str, Any] | None = None) -> str:
    return str((schema or _schema()).get("schemaVersion") or "integrado")


def _validate_attributes(
    value: dict[str, Any], definitions: dict[str, Any], components: dict[str, Any],
    path: str, errors: list[str],
) -> None:
    for name, item in value.items():
        if name in {"id", "documentId", "locale", "__component"}:
            continue
        # Strapi returns optional component fields as null. The captured
        # schema describes their underlying type, but null is still a valid
        # value when the field is not populated.
        if item is None:
            continue
        definition = definitions.get(name)
        current_path = f"{path}.{name}"
        if definition is None:
            errors.append(f"{current_path}: campo ausente en el esquema capturado")
            continue
        kind = definition.get("type")
        if kind == "enumeration":
            if item not in definition.get("enum", []):
                errors.append(f"{current_path}: valor {item!r} fuera del enum permitido")
        elif kind == "component":
            component_uid = definition.get("component")
            component = components.get(component_uid, {})
            component_attrs = component.get("attributes", {})
            values = item if definition.get("repeatable") else [item]
            if not isinstance(values, list):
                errors.append(f"{current_path}: se esperaba un componente{ ' repetible' if definition.get('repeatable') else ''}")
                continue
            for index, component_value in enumerate(values):
                nested_path = f"{current_path}[{index}]" if definition.get("repeatable") else current_path
                if not isinstance(component_value, dict):
                    errors.append(f"{nested_path}: se esperaba un objeto")
                    continue
                if component_value.get("__component") not in (None, component_uid):
                    errors.append(f"{nested_path}: UID de componente inesperado {component_value.get('__component')!r}")
                _validate_attributes(component_value, component_attrs, components, nested_path, errors)
        elif kind == "relation":
            values = item if isinstance(item, list) else [item]
            if any(not isinstance(entry, (int, str, dict)) or (isinstance(entry, dict) and not any(k in entry for k in ("id", "documentId"))) for entry in values):
                errors.append(f"{current_path}: relación sin id/documentId válido")
        elif kind == "string" and not isinstance(item, str):
            errors.append(f"{current_path}: se esperaba texto")
        elif kind in {"text", "richtext"} and not isinstance(item, str):
            errors.append(f"{current_path}: se esperaba texto enriquecido")
        elif kind == "boolean" and not isinstance(item, bool):
            errors.append(f"{current_path}: se esperaba boolean")
        elif kind == "media":
            entries = item if isinstance(item, list) else [item]
            if any(not isinstance(entry, dict) or not any(k in entry for k in ("id", "data", "connect")) for entry in entries):
                errors.append(f"{current_path}: referencia de media inválida")
        elif kind == "json" and not isinstance(item, (dict, list, str, int, float, bool, type(None))):
            errors.append(f"{current_path}: JSON inválido")
