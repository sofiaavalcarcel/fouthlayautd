from __future__ import annotations

import json
from typing import Any


def _unwrap_relation(value: Any) -> Any:
    while isinstance(value, dict) and "data" in value and (
        set(value).issubset({"data", "meta"}) or "attributes" not in value
    ):
        value = value["data"]
    return value


def _normalize_current_for_desired(current: Any, desired: Any) -> Any:
    """Handle the read shapes Strapi uses for relations/components."""
    current = _unwrap_relation(current)
    if isinstance(current, dict) and isinstance(desired, dict):
        desired_keys = set(desired)
        if "attributes" in current and desired_keys and not desired_keys.issubset(current):
            attributes = current.get("attributes")
            if isinstance(attributes, dict) and desired_keys.intersection(attributes):
                return attributes
    return current


def payload_matches(current: Any, desired: Any) -> bool:
    """Compare a Strapi read response with a partial write payload."""
    desired = _unwrap_relation(desired)
    current = _normalize_current_for_desired(current, desired)
    if isinstance(desired, dict):
        if not isinstance(current, dict):
            return False
        return all(key in current and payload_matches(current[key], value) for key, value in desired.items())
    if isinstance(desired, list):
        return isinstance(current, list) and len(current) == len(desired) and all(
            payload_matches(actual, wanted) for actual, wanted in zip(current, desired)
        )
    if isinstance(current, dict) and "id" in current and not isinstance(desired, (dict, list)):
        current = current["id"]
    return current == desired


def plan_change(field: str, current: Any, desired: Any, *, action: str = "update") -> dict[str, Any]:
    return {
        "field": field,
        "action": action,
        "before": _preview(current),
        "after": _preview(desired),
        "verified": None,
    }


def _preview(value: Any, limit: int = 1200) -> Any:
    try:
        serialized = json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        serialized = str(value)
    if len(serialized) > limit:
        return serialized[: limit - 1] + "…"
    return value
