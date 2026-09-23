"""Contratos internos de Weekly Forms."""

from typing import Literal

from pydantic import Field

from ....schemas.bot import UtelQaConfig


class WeeklyFormsCaseConfig(UtelQaConfig):
    weekly_form_type: Literal["form_lp", "lateral", "tarjeta", "footer"] = "form_lp"
    client: str = Field(default="", max_length=160)
