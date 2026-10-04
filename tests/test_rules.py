"""Configured demo review conditions preserve evidence and three-way outcomes."""

from copy import deepcopy
import json
import math
from pathlib import Path

from pydantic import ValidationError
import pytest

from backend.control.alerts import (
    DEMO_NOTICE, ReviewPolicy, ReviewResult, ReviewRule,
    evaluate_review_conditions, load_policy,
)
from backend.control.fusion import METRIC_UNITS, fuse_analysis
from backend.shared.contracts import CombinedAnalysis
from test_contracts import hydro_result
from test_fusion import make_fusion_inputs


def rule_data(**updates):
    return {
        "id": "D-01", "label": "Illustrative observation-duration rainfall comparison",
        "metric": "gpm.mean_accumulation_mm", "unit": "mm", "comparator": "gte",
        "threshold": 0.5, "required_duration_hours": 0.5, "minimum_valid_fraction": 0.9,
        **updates,
    }


def policy_data(*rules, **updates):
    return {
        "version": "1.0", "label": "Explicit demonstration policy",
        "purpose": "demonstration", "rules": list(rules) or [rule_data()], **updates,
    }


def hydro_fusion(hydro):
    return fuse_analysis(*make_fusion_inputs(hydro))


@pytest.mark.parametrize("comparator, relative_threshold, expected", [
    ("gt", -1, "triggered"), ("gt", 0, "not_triggered"), ("gt", 1, "not_triggered"),
    ("gte", -1, "triggered"), ("gte", 0, "triggered"), ("gte", 1, "not_triggered"),
    ("lt", -1, "not_triggered"), ("lt", 0, "not_triggered"), ("lt", 1, "triggered"),
    ("lte", -1, "not_triggered"), ("lte", 0, "triggered"), ("lte", 1, "triggered"),
])
def test_comparators_use_unrounded_values_at_and_next_to_boundary(
    hydro_result, comparator, relative_threshold, expected,
):
    fused = hydro_fusion(hydro_result)
    value = fused.metrics["gpm.mean_accumulation_mm"].value
    threshold = value if relative_threshold == 0 else math.nextafter(
        value, math.inf if relative_threshold > 0 else -math.inf,
    )
    policy = ReviewPolicy.model_validate(policy_data(rule_data(comparator=comparator, threshold=threshold)))
    result = evaluate_review_conditions(fused, policy)
    assessment = result.assessments[0]
    assert assessment.status == expected
    assert assessment.value == value and assessment.threshold == threshold
    assert result.analyst_review_recommended == (expected == "triggered")
    assert result.triggered_count + result.not_triggered_count == 1
    assert result.not_assessable_count == 0


@pytest.mark.parametrize("update", [
    {"metric": "candidate_water.low_hand_overlap"}, {"metric": "gpm.peak_24h_mm"},
    {"comparator": "eq"}, {"comparator": "__import__"}, {"unit": "inches"},
    {"threshold": True}, {"threshold": "5"}, {"threshold": None},
    {"threshold": float("nan")}, {"threshold": float("inf")},
    {"threshold": -float("inf")}, {"threshold": -0.1},
    {"required_duration_hours": None}, {"required_duration_hours": 0},
    {"required_duration_hours": True}, {"required_duration_hours": "1"},
    {"required_duration_hours": float("nan")}, {"required_duration_hours": float("inf")},
    {"minimum_valid_fraction": -0.1}, {"minimum_valid_fraction": 1.1},
    {"minimum_valid_fraction": True}, {"minimum_valid_fraction": "0.9"},
    {"minimum_valid_fraction": float("nan")}, {"minimum_valid_fraction": float("inf")},
    {"id": ""}, {"id": "with spaces"}, {"label": "   "}, {"extra": "ignored"},
])
def test_invalid_rule_configuration_is_rejected(update):
    with pytest.raises(ValidationError):
        ReviewRule.model_validate(rule_data(**update))


@pytest.mark.parametrize("metric", [
    "smap.surface_mean_m3_m3", "smap.rootzone_mean_m3_m3", "sentinel1.valid_fraction",
])
@pytest.mark.parametrize("threshold", [-0.0001, 1.0001])
def test_fraction_and_soil_thresholds_are_bounded(metric, threshold):
    with pytest.raises(ValidationError):
        ReviewRule.model_validate(rule_data(
            metric=metric, unit=METRIC_UNITS[metric], threshold=threshold, required_duration_hours=None,
        ))


@pytest.mark.parametrize("metric", list(METRIC_UNITS))
def test_only_available_metrics_and_their_exact_units_are_configurable(metric):
    rainfall = metric.startswith("gpm.")
    rule = ReviewRule.model_validate(rule_data(
        metric=metric, unit=METRIC_UNITS[metric], required_duration_hours=0.5 if rainfall else None,
    ))
    assert rule.metric == metric
    with pytest.raises(ValidationError):
        ReviewRule.model_validate({**rule.model_dump(), "unit": f"wrong-{rule.unit}"})
    if not rainfall:
        with pytest.raises(ValidationError):
            ReviewRule.model_validate({**rule.model_dump(), "required_duration_hours": 1.0})


@pytest.mark.parametrize("update", [
    {"version": "2.0"}, {"version": 1}, {"version": True},
    {"purpose": "production"}, {"purpose": "scientific"}, {"purpose": None},
    {"label": "   "}, {"rules": []}, {"rules": "default"},
    {"rules": [rule_data(), rule_data()]}, {"extra": "ignored"},
])
def test_policy_must_be_explicit_versioned_unique_and_demo_only(update):
    with pytest.raises(ValidationError):
        ReviewPolicy.model_validate(policy_data(**update))


@pytest.mark.parametrize("field", ["version", "label", "purpose", "rules"])
def test_policy_does_not_fill_implicit_defaults(field):
    value = policy_data()
    value.pop(field)
    with pytest.raises(ValidationError):
        ReviewPolicy.model_validate(value)


def test_duration_mismatch_is_not_assessable_and_keeps_observed_measurement(hydro_result):
    fused = hydro_fusion(hydro_result)
    policy = ReviewPolicy.model_validate(policy_data(rule_data(required_duration_hours=24.0)))
    result = evaluate_review_conditions(fused, policy)
    assessment = result.assessments[0]
    assert assessment.status == "not_assessable"
    assert assessment.value == fused.metrics[assessment.metric].value
    assert assessment.duration_hours == 0.5
    assert assessment.required_duration_hours == 24.0
    assert "duration" in assessment.reason
    assert assessment.dependencies == [
        "gpm.mean_accumulation_mm", "gpm.mean_accumulation_mm.duration_hours",
        "gpm.mean_accumulation_mm.valid_fraction",
    ]
    assert result.not_assessable_count == 1
    assert not result.analyst_review_recommended


def test_unknown_coverage_prevents_assessment_without_erasing_value(hydro_result):
    raw = deepcopy(hydro_result)
    raw["evidence"]["gpm"].pop("selected_grid")
    fused = hydro_fusion(raw)
    result = evaluate_review_conditions(fused, ReviewPolicy.model_validate(policy_data()))
    assessment = result.assessments[0]
    assert assessment.status == "not_assessable"
    assert assessment.value is not None and assessment.valid_fraction is None
    assert "coverage" in assessment.reason
    # A policy that explicitly does not gate on coverage can still compare the
    # preserved measurement; its result discloses that coverage is unknown.
    ungated = ReviewPolicy.model_validate(policy_data(rule_data(minimum_valid_fraction=None)))
    observed = evaluate_review_conditions(fused, ungated).assessments[0]
    assert observed.status in {"triggered", "not_triggered"}
    assert observed.valid_fraction is None


def test_coverage_gate_uses_inclusive_minimum_and_rejects_lower_support(hydro_result):
    raw = deepcopy(hydro_result)
    grid = raw["evidence"]["gpm"]["selected_grid"]
    grid["complete_coverage_pixels"] = 1
    grid["complete_coverage_fraction"] = 1 / grid["total_pixels"]
    fused = hydro_fusion(raw)
    observed_coverage = fused.metrics["gpm.mean_accumulation_mm"].valid_fraction
    policy = ReviewPolicy.model_validate(policy_data(rule_data(minimum_valid_fraction=observed_coverage)))
    assert evaluate_review_conditions(fused, policy).assessments[0].status != "not_assessable"
    above = ReviewPolicy.model_validate(policy_data(rule_data(
        minimum_valid_fraction=math.nextafter(observed_coverage, math.inf),
    )))
    result = evaluate_review_conditions(fused, above).assessments[0]
    assert result.status == "not_assessable" and result.value is not None
    assert result.valid_fraction == observed_coverage


def test_partial_collection_retains_hydro_and_never_passes_missing_water(hydro_result):
    fused = hydro_fusion(hydro_result)
    value = fused.metrics["gpm.mean_accumulation_mm"].value
    policy = ReviewPolicy.model_validate(policy_data(
        rule_data(threshold=value),
        rule_data(id="D-02", label="Higher example rainfall threshold", threshold=value + 1),
        rule_data(id="D-03", label="Missing water", metric="sentinel1.candidate_area_km2",
                  unit="km2", threshold=0.0, required_duration_hours=None),
    ))
    result = evaluate_review_conditions(fused, policy)
    assert [item.status for item in result.assessments] == ["triggered", "not_triggered", "not_assessable"]
    assert (result.triggered_count, result.not_triggered_count, result.not_assessable_count) == (1, 1, 1)
    assert result.assessments[-1].value is None
    assert result.analyst_review_recommended
    assert result.policy.purpose == "demonstration" and result.notice == DEMO_NOTICE


def test_all_missing_evidence_is_explicitly_unassessed(hydro_result):
    hydro, flood, combined = make_fusion_inputs(hydro_result)
    missing = CombinedAnalysis(task_id=combined["task_id"], errors=["Neither investigation returned evidence."])
    fused = fuse_analysis(hydro, flood, missing)
    result = evaluate_review_conditions(fused, ReviewPolicy.model_validate(policy_data()))
    assert result.assessments[0].status == "not_assessable"
    assert result.assessments[0].value is None
    assert result.triggered_count == result.not_triggered_count == 0
    assert result.not_assessable_count == 1
    assert not result.analyst_review_recommended


def test_evaluation_is_deterministic_lossless_and_strict_json(hydro_result):
    fused = hydro_fusion(hydro_result)
    policy = ReviewPolicy.model_validate(policy_data())
    original = fused.model_dump(mode="python")
    configured = policy.model_dump(mode="python")
    first = evaluate_review_conditions(fused, policy)
    assert evaluate_review_conditions(fused, policy) == first
    assert fused.model_dump(mode="python") == original
    assert policy.model_dump(mode="python") == configured
    payload = json.dumps(first.model_dump(mode="json"), allow_nan=False)
    assert ReviewResult.model_validate_json(payload) == first
    assert "demonstration" in payload


def test_evaluator_revalidates_mutated_policy_and_evidence(hydro_result):
    fused = hydro_fusion(hydro_result)
    policy = ReviewPolicy.model_validate(policy_data())
    poisoned = policy.model_copy(update={"rules": [policy.rules[0].model_copy(update={"threshold": float("nan")})]})
    with pytest.raises(ValidationError):
        evaluate_review_conditions(fused, poisoned)
    metric = fused.metrics["gpm.mean_accumulation_mm"]
    poisoned = fused.model_copy(update={"metrics": {
        **fused.metrics, metric.metric_id: metric.model_copy(update={"value": metric.value + 10}),
    }})
    with pytest.raises(ValidationError):
        evaluate_review_conditions(poisoned, policy)


@pytest.mark.parametrize("fault", ["count", "threshold", "false_missing", "recommendation"])
def test_serialized_assessment_cannot_contradict_policy_or_counts(hydro_result, fault):
    result = evaluate_review_conditions(hydro_fusion(hydro_result), ReviewPolicy.model_validate(policy_data()))
    raw = result.model_dump(mode="python")
    if fault == "count":
        raw["not_assessable_count"] += 1
    elif fault == "threshold":
        raw["assessments"][0]["threshold"] += 1
    elif fault == "false_missing":
        raw["assessments"][0]["status"] = "not_assessable"
    else:
        raw["analyst_review_recommended"] = not raw["analyst_review_recommended"]
    with pytest.raises(ValidationError):
        ReviewResult.model_validate(raw)


@pytest.mark.parametrize("payload", [
    '{"version":"1.0","version":"1.0"}',
    '{"rules":[{"threshold":1,"threshold":2}]}',
    '{"threshold":NaN}', '{"threshold":Infinity}', '{"threshold":-Infinity}',
    '{"threshold":1e999}', '{"threshold":-1e999}', '{not json}',
])
def test_policy_loader_rejects_duplicate_and_nonfinite_json(tmp_path, payload):
    path = tmp_path / "rules.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(ValueError):
        load_policy(path)


def test_policy_loader_accepts_utf8_bom_but_is_bounded(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(json.dumps(policy_data()), encoding="utf-8-sig")
    assert load_policy(path) == ReviewPolicy.model_validate(policy_data())
    path.write_bytes(b" " * 65_537)
    with pytest.raises(ValueError, match="64 KiB"):
        load_policy(path)


def test_example_policy_uses_available_quantities_and_explicit_demo_label():
    path = Path(__file__).resolve().parents[1] / "config" / "rules.example.json"
    policy = load_policy(path)
    assert policy.purpose == "demonstration"
    assert "not scientific" in policy.label
    assert len(policy.rules) == 5
    assert policy.rules[0].required_duration_hours == 1.0
    assert policy.rules[-1].metric == "sentinel1.valid_fraction"
    assert policy.rules[-1].minimum_valid_fraction is None
    assert all("overlap" not in rule.metric and "peak_24h" not in rule.metric for rule in policy.rules)
