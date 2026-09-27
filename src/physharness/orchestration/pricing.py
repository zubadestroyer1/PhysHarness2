"""Experiment prices are explicit inputs.

Cached input is billed at ``cached_input_usd_per_million`` when an operator records one; without it
every input token bills at the input rate, as before. The cached rate may not exceed the input rate,
so a reservation at the full rate bounds every settlement. Provider cache writes are not modelled.
"""

from decimal import ROUND_CEILING, Decimal

from pydantic import Field, model_validator

from ..domain import StrictModel


class ModelPrice(StrictModel):
    input_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    output_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    cached_input_usd_per_million: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    source: str = "operator-supplied"

    @model_validator(mode="after")
    def cached_rate_within_input_rate(self):
        cached = self.cached_input_usd_per_million
        if cached is not None and cached > self.input_usd_per_million:
            raise ValueError("cached_input_usd_per_million cannot exceed input_usd_per_million")
        return self

    def cost(self, input_tokens, output_tokens, cached_input_tokens=0):
        if input_tokens < 0 or output_tokens < 0 or cached_input_tokens < 0:
            raise ValueError("Token counts cannot be negative")
        if cached_input_tokens > input_tokens:
            raise ValueError("Cached input tokens cannot exceed input tokens")
        rate = self.cached_input_usd_per_million
        cached_rate = self.input_usd_per_million if rate is None else rate
        value = (
            self.input_usd_per_million * (input_tokens - cached_input_tokens)
            + cached_rate * cached_input_tokens
            + self.output_usd_per_million * output_tokens
        ) / 1_000_000
        return value.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
