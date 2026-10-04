"""Deterministic analyst-review conditions for explicitly labeled demo policies.

Conditions evaluate validated observations without changing worker evidence.
No policy is selected implicitly, and these thresholds are not scientific
hazard classifications or operational emergency-response criteria.
"""

from __future__ import annotations

import json
import math
import operator
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import ConfigDict, Field, model_validator

from backend.control.fusion import FusionResult, METRIC_UNITS
from backend.shared.contracts import Contract, Finite, Fraction, Nonempty


Comparator = Literal["gt", "gte", "lt", "lte"]
ReviewStatus = Literal["triggered", "not_triggered", "not_assessable"]
PositiveDuration = Annotated[Finite, Field(gt=0)]
RuleID = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")]
DEMO_NOTICE = (
    "Demonstration policy: thresholds are illustrative configured criteria for "
    "analyst review. They are not scientifically validated disaster thresholds "
    "or an emergency-response determination. Unassessed conditions remain explicit."
)
_COMPARATORS = {"gt": operator.gt, "gte": operator.ge, "lt": operator.lt, "lte": operator.le}
_RAINFALL_METRICS = {"gpm.mean_accumulation_mm", "gpm.max_cell_accumulation_mm"}
_FRACTION_METRICS = {
    "smap.surface_mean_m3_m3", "smap.rootzone_mean_m3_m3", "sentinel1.valid_fraction",
}
_NONNEGATIVE_METRICS = _RAINFALL_METRICS | {"sentinel1.candidate_area_km2", "hand.mean_m"}
_MAX_POLICY_BYTES = 65_536


class ReviewRule(Contract):
    """One allowlisted comparison with explicit units and evidence eligibility."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, validate_default=True)

    id: RuleID
    label: Nonempty
    metric: Nonempty
    unit: Nonempty
    comparator: Comparator
    threshold: Finite
    required_duration_hours: PositiveDuration | None = None
    minimum_valid_fraction: Fraction | None = None

    @model_validator(mode="after")
    def supported_condition(self) -> Self:
        if not self.label.strip():
            raise ValueError("A review condition requires a nonblank label.")
        if self.metric not in METRIC_UNITS:
            raise ValueError("The review metric is not supported by the accepted evidence.")
        if self.unit != METRIC_UNITS[self.metric]:
            raise ValueError("Review units must match the metric's authoritative units.")
        if self.metric in _RAINFALL_METRICS and self.required_duration_hours is None:
            raise ValueError("Rainfall conditions require an explicit observation duration.")
        if self.metric not in _RAINFALL_METRICS and self.required_duration_hours is not None:
            raise ValueError("Only rainfall accumulation conditions may specify a duration.")
        if self.metric in _FRACTION_METRICS and not 0 <= self.threshold <= 1:
            raise ValueError("Fraction and soil-moisture thresholds must lie between zero and one.")
        if self.metric in _NONNEGATIVE_METRICS and self.threshold < 0:
            raise ValueError("This metric requires a nonnegative threshold.")
        return self


class ReviewPolicy(Contract):
    """An explicit, versioned demonstration policy; no production default."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False, validate_default=True)

    version: Literal["1.0"]
    label: Nonempty
    purpose: Literal["demonstration"]
    rules: Annotated[list[ReviewRule], Field(min_length=1, max_length=32)]

    @model_validator(mode="after")
    def explicit_policy(self) -> Self:
        if not self.label.strip():
            raise ValueError("A demonstration policy requires a nonblank label.")
        ids = [rule.id for rule in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError("Review condition IDs must be unique within a policy.")
        return self


class ReviewAssessment(Contract):
    rule_id: RuleID
    label: Nonempty
    metric: Nonempty
    component: Nonempty
    unit: Nonempty
    comparator: Comparator
    threshold: Finite
    required_duration_hours: PositiveDuration | None
    minimum_valid_fraction: Fraction | None
    value: Finite | None
    valid_fraction: Fraction | None
    duration_hours: PositiveDuration | None
    status: ReviewStatus
    reason: Nonempty
    dependencies: Annotated[list[Nonempty], Field(min_length=1)]

    @model_validator(mode="after")
    def assessed_values_exist(self) -> Self:
        if self.status != "not_assessable" and self.value is None:
            raise ValueError("An assessed condition requires an observed numerical value.")
        return self


class ReviewResult(Contract):
    policy: ReviewPolicy
    assessments: Annotated[list[ReviewAssessment], Field(min_length=1)]
    triggered_count: Annotated[int, Field(strict=True, ge=0)]
    not_triggered_count: Annotated[int, Field(strict=True, ge=0)]
    not_assessable_count: Annotated[int, Field(strict=True, ge=0)]
    analyst_review_recommended: Annotated[bool, Field(strict=True)]
    notice: Literal[DEMO_NOTICE] = DEMO_NOTICE

    @model_validator(mode="after")
    def consistent_counts(self) -> Self:
        if [item.rule_id for item in self.assessments] != [rule.id for rule in self.policy.rules]:
            raise ValueError("Every configured condition must have one ordered assessment.")
        for assessment, rule in zip(self.assessments, self.policy.rules):
            if any(getattr(assessment, field) != getattr(rule, field) for field in (
                "label", "metric", "unit", "comparator", "threshold",
                "required_duration_hours", "minimum_valid_fraction",
            )):
                raise ValueError("Every assessment must retain its exact configured condition.")
            eligible = assessment.value is not None
            if rule.required_duration_hours is not None:
                eligible = eligible and assessment.duration_hours == rule.required_duration_hours
            if rule.minimum_valid_fraction is not None:
                eligible = eligible and assessment.valid_fraction is not None and assessment.valid_fraction >= rule.minimum_valid_fraction
            expected = "not_assessable" if not eligible else (
                "triggered" if _COMPARATORS[rule.comparator](assessment.value, rule.threshold) else "not_triggered"
            )
            if assessment.status != expected:
                raise ValueError("Assessment status must match its retained values and configured eligibility.")
        for status in ("triggered", "not_triggered", "not_assessable"):
            if getattr(self, f"{status}_count") != sum(item.status == status for item in self.assessments):
                raise ValueError("Review counts must retain all three assessment states.")
        if self.analyst_review_recommended != (self.triggered_count > 0):
            raise ValueError("The review recommendation must reflect triggered conditions.")
        return self


def _reject_constant(_value):
    raise ValueError("Review policy JSON cannot contain nonfinite numbers.")


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("Review policy JSON cannot contain nonfinite numbers.")
    return number


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Review policy JSON cannot contain duplicate keys.")
        result[key] = value
    return result


def load_policy(path: str | Path) -> ReviewPolicy:
    """Read a bounded strict-JSON policy without silently filling missing rules."""
    with Path(path).open("rb") as stream:
        encoded = stream.read(_MAX_POLICY_BYTES + 1)
    if len(encoded) > _MAX_POLICY_BYTES:
        raise ValueError("Review policy exceeds the 64 KiB limit.")
    try:
        value = json.loads(
            encoded.decode("utf-8-sig"), parse_constant=_reject_constant,
            parse_float=_finite_float, object_pairs_hook=_unique_object,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError):
        raise ValueError("Review policy must be valid UTF-8 JSON.") from None
    return ReviewPolicy.model_validate(value)


def evaluate_review_conditions(fused: FusionResult, policy: ReviewPolicy) -> ReviewResult:
    """Evaluate raw-precision values; missing/unsuitable evidence is unassessed.

    Revalidation through detached Python dictionaries rejects mutated model
    instances rather than trusting their previously validated construction.
    Rainfall duration means the sum of supplied observation durations; no
    continuous time interval or peak-24-hour value is inferred.
    """
    if not isinstance(fused, FusionResult) or not isinstance(policy, ReviewPolicy):
        raise TypeError("Use a validated FusionResult and explicit ReviewPolicy.")
    fused = FusionResult.model_validate(fused.model_dump(mode="python"))
    policy = ReviewPolicy.model_validate(policy.model_dump(mode="python"))
    assessments = []
    for rule in policy.rules:
        metric = fused.metrics[rule.metric]
        dependencies = [rule.metric]
        if rule.required_duration_hours is not None:
            dependencies.append(f"{rule.metric}.duration_hours")
        if rule.minimum_valid_fraction is not None:
            dependencies.append(f"{rule.metric}.valid_fraction")

        reasons = []
        if metric.status != "available" or metric.value is None:
            reasons.append(metric.unavailable_reason or "Required evidence is unavailable.")
        else:
            if rule.required_duration_hours is not None:
                if metric.duration_hours is None:
                    reasons.append("The observation duration required by this condition is unavailable.")
                elif metric.duration_hours != rule.required_duration_hours:
                    reasons.append("The supplied observation duration does not match this condition's configured duration.")
            if rule.minimum_valid_fraction is not None:
                if metric.valid_fraction is None:
                    reasons.append("Valid observation coverage is unavailable for this condition.")
                elif metric.valid_fraction < rule.minimum_valid_fraction:
                    reasons.append("Valid observation coverage is below this condition's configured minimum.")

        if reasons:
            status = "not_assessable"
            reason = " ".join(reasons)
        elif _COMPARATORS[rule.comparator](metric.value, rule.threshold):
            status = "triggered"
            reason = "The observed value meets this demonstration policy's configured analyst-review condition."
        else:
            status = "not_triggered"
            reason = "The observed value does not meet this demonstration policy's configured analyst-review condition."
        assessments.append(ReviewAssessment(
            rule_id=rule.id, label=rule.label, metric=rule.metric, component=metric.component,
            unit=rule.unit, comparator=rule.comparator, threshold=rule.threshold,
            required_duration_hours=rule.required_duration_hours,
            minimum_valid_fraction=rule.minimum_valid_fraction,
            value=metric.value, valid_fraction=metric.valid_fraction, duration_hours=metric.duration_hours,
            status=status, reason=reason, dependencies=dependencies,
        ))
    counts = {status: sum(item.status == status for item in assessments)
              for status in ("triggered", "not_triggered", "not_assessable")}
    return ReviewResult(
        policy=policy, assessments=assessments,
        triggered_count=counts["triggered"], not_triggered_count=counts["not_triggered"],
        not_assessable_count=counts["not_assessable"],
        analyst_review_recommended=counts["triggered"] > 0,
    )
