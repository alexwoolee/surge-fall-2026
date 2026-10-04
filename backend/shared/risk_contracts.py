"""Strict presentation contract for a screening concern and evidence score."""

from typing import Annotated, Literal, Self
from pydantic import Field, StrictBool, model_validator
from backend.shared.contracts import Contract, Count, Fraction

Text = Annotated[str, Field(strict=True, min_length=1, max_length=2000)]


class RiskView(Contract):
    level: Literal['unknown', 'low', 'moderate', 'high', 'critical']
    score: Annotated[Count, Field(le=100)] | None
    confidenceLevel: Literal['low', 'moderate', 'high']
    confidenceScore: Fraction
    alert: StrictBool
    title: Text
    summary: Text
    basis: Text
    limitations: Annotated[list[Text], Field(min_length=1, max_length=32)]

    @model_validator(mode='after')
    def consistent(self) -> Self:
        if (self.level == 'unknown') != (self.score is None) or self.alert != (self.level in ('high', 'critical')):
            raise ValueError('Screening level, score and alert disagree.')
        expected = 'high' if self.confidenceScore >= .8 else 'moderate' if self.confidenceScore >= .5 else 'low'
        if self.confidenceLevel != expected:
            raise ValueError('Confidence label must match its evidence score.')
        return self
