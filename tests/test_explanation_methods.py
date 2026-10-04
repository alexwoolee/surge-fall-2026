"""Product/method context is complete without exposing untrusted worker text."""

from copy import deepcopy
import json

import pytest

from backend.control.explanation_methods import build_method_facts
from backend.control.fusion import fuse_analysis
from backend.control.agent_grounding import render_explanation
from test_agent_grounding import make_report
from test_contracts import hydro_result
from test_fusion import fusion_inputs, remove_flood_components


def _catalog(inputs):
    return {fact["id"]: fact for fact in build_method_facts(fuse_analysis(*inputs))}


def test_fixed_product_methods_and_limitations_have_resolvable_references(fusion_inputs):
    fused = fuse_analysis(*fusion_inputs)
    original = fused.model_dump(mode="json")
    facts = build_method_facts(fused)
    catalog = {fact["id"]: fact for fact in facts}
    assert len(catalog) == len(facts)
    assert {f"source.{name}" for name in fused.components} <= catalog.keys()
    assert {f"method.{name}" for name in fused.components} <= catalog.keys()
    assert {f"source_limitation.{name}" for name in fused.components} <= catalog.keys()
    text = " ".join(fact["text"] for fact in facts)
    for expected in ("GPM_3IMERGHH", "version 07", "SPL4SMGP", "version 008",
                     "sentinel-1-rtc", "cop-dem-glo-30", "glo-30-hand",
                     "<= -17.0 dB", "surface model", "EGM2008", "Permanent water",
                     "radar shadow", "not a confidence interval", "model-assimilated",
                     "undeclared positive sentinel", "not geographic-area-weighted"):
        assert expected in text
    report = {"fusion": original}
    for fact in facts:
        assert set(fact) == {"id", "text", "kind", "source_refs"}
        assert fact["source_refs"]
        for ref in fact["source_refs"]:
            value = report
            for part in ref.lstrip("/").split("/"):
                value = value[int(part)] if isinstance(value, list) else value[part]
    assert fused.model_dump(mode="json") == original
    assert build_method_facts(fused) == facts


def test_sensitivity_retains_exact_threshold_and_area_numbers(fusion_inputs):
    catalog = _catalog(fusion_inputs)
    text = catalog["method.sentinel1_sensitivity"]["text"]
    for row in fusion_inputs[2]["flood"]["evidence"]["sentinel1"]["sensitivity"]:
        assert f"{row['threshold_db']!r} dB: {row['area_km2']!r} km2" in text
    assert "not a confidence interval, probability or validated flood extent" in text


@pytest.mark.parametrize("fallback", [False, True])
def test_contract_valid_extreme_sensitivity_count_preserves_full_explanation(fusion_inputs, fallback):
    flood = fusion_inputs[2]["flood"]
    evidence = flood["evidence"]["sentinel1"]
    count = 10 ** 400
    coverage = flood["coverage"]["sentinel1"]
    coverage.update(aoi_pixels=count, covered_pixels=count, valid_pixels=count,
                    coverage_fraction=1.0, valid_fraction=1.0, status="complete")
    evidence["coverage"] = deepcopy(coverage)
    evidence["candidate_water"]["fraction_valid"] = evidence["candidate_water"]["count"] / count
    flood["summary"]["surface_water"].update(
        valid_fraction=1.0, candidate_fraction_valid=evidence["candidate_water"]["fraction_valid"],
    )
    for row in evidence["sensitivity"]:
        row["fraction_valid"] = row["count"] / count
    evidence["sensitivity"][-1].update(count=count, fraction_valid=1.0)
    # This input still satisfies the existing full evidence contract; only the
    # optional high-threshold sensitivity count overflows area arithmetic.
    fused = fuse_analysis(*fusion_inputs)
    assert fused.components["sentinel1"].coverage["valid_pixels"] == count
    report = make_report(fusion_inputs)
    original = deepcopy(report)
    rendered = render_explanation(report, None if fallback else ["disclaimer"],
                                  status="fallback" if fallback else "complete")
    assert rendered["measurements"] == report["fusion"]["metrics"]
    assert rendered["measurements"]["sentinel1.candidate_area_km2"]["value"] is not None
    assert "unavailable or internally inconsistent" in rendered["narrative"]
    assert report == original


@pytest.mark.parametrize("change", [
    "missing", "null", "short", "extra", "threshold", "bool_threshold", "bool_count",
    "negative_count", "excess_count", "fraction", "area", "non_mapping",
    "non_monotonic", "center_mismatch", "missing_area", "huge_threshold",
    "negative_area", "negative_fraction",
])
def test_unvalidated_sensitivity_does_not_become_a_reported_measurement(fusion_inputs, change):
    evidence = fusion_inputs[2]["flood"]["evidence"]["sentinel1"]
    rows = evidence["sensitivity"]
    if change == "missing":
        evidence.pop("sensitivity")
    elif change == "null":
        evidence["sensitivity"] = None
    elif change == "short":
        rows.pop()
    elif change == "extra":
        rows.append(deepcopy(rows[-1]))
    elif change == "threshold":
        rows[0]["threshold_db"] += 0.1
    elif change == "bool_threshold":
        rows[0]["threshold_db"] = True
    elif change == "huge_threshold":
        rows[0]["threshold_db"] = 10 ** 1000
    elif change == "bool_count":
        rows[0]["count"] = True
    elif change == "negative_count":
        rows[0]["count"] = -1
    elif change == "excess_count":
        rows[0]["count"] = evidence["coverage"]["valid_pixels"] + 1
    elif change == "fraction":
        rows[0]["fraction_valid"] += 0.1
    elif change == "area":
        rows[0]["area_km2"] += 0.1
    elif change in {"negative_area", "negative_fraction"}:
        rows[0].update(count=0, fraction_valid=0, area_km2=0)
        rows[0]["area_km2" if change == "negative_area" else "fraction_valid"] = -1e-13
    elif change == "non_mapping":
        rows[0] = "private arbitrary worker text"
    elif change == "missing_area":
        rows[0].pop("area_km2")
    else:
        index = 0 if change == "non_monotonic" else 1
        count = evidence["coverage"]["valid_pixels"] if index == 0 else 0
        rows[index].update(count=count,
                           fraction_valid=count / evidence["coverage"]["valid_pixels"],
                           area_km2=count * evidence["raster"]["pixel_area_m2"] / 1_000_000)
    catalog = _catalog(fusion_inputs)
    assert "unavailable or internally inconsistent" in catalog["method.sentinel1_sensitivity"]["text"]
    assert "-17.0 dB" in catalog["method.sentinel1"]["text"]
    assert "Mean" not in catalog["method.sentinel1_sensitivity"]["text"]


@pytest.mark.parametrize("missing", ["hydro", "flood", "both", "sentinel1", "hand"])
def test_unavailable_evidence_does_not_acquire_a_method_or_sensitivity(fusion_inputs, missing):
    combined = fusion_inputs[2]
    if missing in {"sentinel1", "hand"}:
        remove_flood_components(combined["flood"], {missing})
        absent = {missing}
    else:
        for worker in ("hydro", "flood") if missing == "both" else (missing,):
            combined[worker] = None
        combined["errors"] = ["PRIVATE_WORKER_ERROR"]
        absent = ({"gpm", "smap", "sentinel1", "dem", "hand"} if missing == "both"
                  else {"gpm", "smap"} if missing == "hydro" else {"sentinel1", "dem", "hand"})
    catalog = _catalog(fusion_inputs)
    for component in absent:
        assert "evidence unavailable" in catalog[f"source.{component}"]["text"]
        assert f"method.{component}" not in catalog
        assert f"source_limitation.{component}" not in catalog
    if "sentinel1" in absent:
        assert "method.sentinel1_sensitivity" not in catalog
    assert "PRIVATE_WORKER_ERROR" not in json.dumps(catalog)


def test_partial_coverage_still_reports_observed_sensitivity_without_extrapolation(fusion_inputs):
    flood = fusion_inputs[2]["flood"]
    coverage = flood["coverage"]["sentinel1"]
    coverage["aoi_pixels"] *= 2
    coverage["coverage_fraction"] = coverage["covered_pixels"] / coverage["aoi_pixels"]
    coverage["valid_fraction"] = coverage["valid_pixels"] / coverage["aoi_pixels"]
    coverage["status"] = "partial"
    flood["evidence"]["sentinel1"]["coverage"] = deepcopy(coverage)
    flood["summary"]["surface_water"]["valid_fraction"] = coverage["valid_fraction"]
    text = _catalog(fusion_inputs)["method.sentinel1_sensitivity"]["text"]
    for row in flood["evidence"]["sentinel1"]["sensitivity"]:
        assert repr(row["area_km2"]) in text


@pytest.mark.parametrize("field,value", [
    ("raster", None), ("raster", []), ("raster", "private scalar"),
    ("scene", None), ("scene", []), ("method", None), ("method", []),
    ("valid_pixels", 0), ("valid_pixels", True), ("valid_pixels", None),
])
def test_optional_context_is_defensive_even_after_a_typed_result_is_mutated(fusion_inputs, field, value):
    # Normal explanation entry points revalidate the result first. This also
    # exercises the helper's own boundary against containers malformed later.
    fused = fuse_analysis(*fusion_inputs)
    component = fused.components["sentinel1"]
    if field == "valid_pixels":
        component.coverage[field] = value
    else:
        component.evidence[field] = value
    catalog = {fact["id"]: fact for fact in build_method_facts(fused)}
    assert "unavailable or internally inconsistent" in catalog["method.sentinel1_sensitivity"]["text"]
    assert "private scalar" not in json.dumps(catalog)
    assert fused.metrics["sentinel1.candidate_area_km2"].value is not None


@pytest.mark.parametrize("metadata", ["provenance", "conversion", "polarization", "sensitivity_extra"])
def test_arbitrary_source_and_method_text_is_never_copied(fusion_inputs, metadata):
    secret = "PRIVATE_TOKEN_8z9_worker_100.64.1.2"
    hydro, flood = fusion_inputs[2]["hydro"], fusion_inputs[2]["flood"]
    evidence = flood["evidence"]["sentinel1"]
    hydro["sources"][0]["extra"] = secret
    hydro["limitations"].append(secret)
    flood["limitations"].append(secret)
    evidence["limitations"].append(secret)
    if metadata == "provenance":
        flood["sources"][0]["extra"] = secret
    elif metadata == "conversion":
        evidence["method"]["conversion"] = secret
    elif metadata == "polarization":
        evidence["scene"]["polarization"] = secret
    else:
        evidence["sensitivity"][0]["comment"] = secret
    catalog = _catalog(fusion_inputs)
    encoded = json.dumps(catalog)
    assert secret not in encoded
    assert "fusion-scene" not in encoded
    assert "fusion-sar.tif" not in encoded
    assert "fusion-dem.tif" not in encoded
    if metadata in {"conversion", "polarization"}:
        assert "details are not claimed" in catalog["method.sentinel1"]["text"]
        assert "unavailable or internally inconsistent" in catalog["method.sentinel1_sensitivity"]["text"]
