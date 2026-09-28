"""Experiment prices are explicit inputs.

Cached input is billed at ``cached_input_usd_per_million`` when an operator records one; without it
every input token bills at the input rate, as before. The cached rate may not exceed the input rate.
A price with a cached rate must also record ``cache_write_usd_per_million``: the provider bills
cache writes above the input rate, which the full-rate over-count of cache hits used to mask.
Reservations charge every input token at the higher of the input and cache-write rates, so a
reservation bounds every settlement.
"""

from decimal import ROUND_CEILING, Decimal

from pydantic import Field, model_validator

from ..domain import StrictModel


class ModelPrice(StrictModel):
    input_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    output_usd_per_million: Decimal = Field(ge=0, allow_inf_nan=False)
    cached_input_usd_per_million: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    cache_write_usd_per_million: Decimal | None = Field(default=None, ge=0, allow_inf_nan=False)
    source: str = "operator-supplied"

    @model_validator(mode="after")
    def cached_rates_are_complete(self):
        cached = self.cached_input_usd_per_million
        if cached is not None and cached > self.input_usd_per_million:
            raise ValueError("cached_input_usd_per_million cannot exceed input_usd_per_million")
        if cached is not None and self.cache_write_usd_per_million is None:
            raise ValueError(
                "cached_input_usd_per_million requires cache_write_usd_per_million, the "
                "provider's cache-write rate"
            )
        return self

    def _rates(self):
        cached, write = self.cached_input_usd_per_million, self.cache_write_usd_per_million
        full = self.input_usd_per_million
        return (full if cached is None else cached), (full if write is None else write)

    def cost(self, input_tokens, output_tokens, cached_input_tokens=0, cache_write_tokens=0):
        if min(input_tokens, output_tokens, cached_input_tokens, cache_write_tokens) < 0:
            raise ValueError("Token counts cannot be negative")
        if cached_input_tokens + cache_write_tokens > input_tokens:
            raise ValueError("Cached and cache-write input tokens cannot exceed input tokens")
        cached_rate, write_rate = self._rates()
        plain = input_tokens - cached_input_tokens - cache_write_tokens
        value = (
            self.input_usd_per_million * plain
            + cached_rate * cached_input_tokens
            + write_rate * cache_write_tokens
            + self.output_usd_per_million * output_tokens
        ) / 1_000_000
        return value.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)

    def reservation_cost(self, input_tokens, output_tokens):
        """The most ``input_tokens`` and ``output_tokens`` can settle at: every input token at
        the higher of the input and cache-write rates, since neither a hit nor a write is known
        in advance."""
        rate = max(self.input_usd_per_million, self._rates()[1])
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("Token counts cannot be negative")
        value = (rate * input_tokens + self.output_usd_per_million * output_tokens) / 1_000_000
        return value.quantize(Decimal("0.000001"), rounding=ROUND_CEILING)
