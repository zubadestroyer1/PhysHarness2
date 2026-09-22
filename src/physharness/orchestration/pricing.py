"""Experiment prices are explicit inputs; cached-token discounts are conservatively omitted."""

from decimal import ROUND_CEILING, Decimal

from pydantic import Field

from ..domain import StrictModel


class ModelPrice(StrictModel):
    input_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    output_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    source: str = "operator-supplied"

    def cost(self, input_tokens, output_tokens):
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token counts cannot be negative")
        value = (
            self.input_usd_per_million * input_tokens + self.output_usd_per_million * output_tokens
        ) / 1_000_000
        return value.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
