from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ProductRow:
    sheet: str
    row_number: int
    program: str
    document: str | None = None
    ft_document: str | None = None


@dataclass(frozen=True)
class ProductResult:
    sheet: str
    row_number: int
    program: str
    country: str
    status: str
    old_canonical: str | None = None
    new_canonical: str | None = None
    message: str | None = None
    description: str | None = None
    siu_key: str | None = None
    banner_key: str | None = None
    changes: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProductSummary:
    total: int
    updated: int
    dry_run: int
    skipped: int
    not_found: int
    ambiguous: int
    invalid_data: int
    failed: int

    def as_dict(self) -> dict[str, int]:
        return asdict(self)
