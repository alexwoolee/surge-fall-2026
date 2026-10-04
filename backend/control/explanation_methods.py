"""Safe product and processing context for a revalidated fusion result.

Product names and method descriptions are fixed templates for the supported
processors. Worker prose, resource identifiers, paths and URLs are never copied
into the explanation. Optional SAR sensitivity is checked separately because
the lossless evidence envelope does not otherwise validate those extra rows.
"""

import math

from backend.control.fusion import FusionResult


_SOURCES = {
    "gpm": "NASA GPM IMERG, product GPM_3IMERGHH, version 07",
    "smap": "NASA SMAP L4, product SPL4SMGP, version 008",
    "sentinel1": "Sentinel-1 RTC, collection sentinel-1-rtc",
    "dem": "Copernicus DEM GLO-30, collection cop-dem-glo-30",
    "hand": "ASF GLO-30 HAND, collection glo-30-hand",
}
_SAR_METHOD = {
    "input": "linear gamma0 power", "conversion": "10 * log10(gamma0)",
    "comparison": "<=", "smoothing": "none added by MeshMind",
    "clipping": "pixel_centers", "area_method": "UTM planimetric pixel area",
}


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _same(actual, expected):
    return _number(actual) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


def _sensitivity(component):
    """Return exact evidence numbers only when all three rows agree internally.

This checks arithmetic and parameter binding, not the authenticity of pixels.
The source acquisition and processing evidence remain in the retained report.
    """
    evidence, summary = component.evidence, component.summary
    if not isinstance(evidence, dict) or not isinstance(summary, dict) or not isinstance(component.coverage, dict):
        return None
    rows = evidence.get("sensitivity")
    raster = evidence.get("raster")
    area = raster.get("pixel_area_m2") if isinstance(raster, dict) else None
    valid = component.coverage.get("valid_pixels")
    threshold = summary.get("threshold_db")
    if (not isinstance(rows, list) or len(rows) != 3 or not _number(area) or area <= 0
            or isinstance(valid, bool) or not isinstance(valid, int) or valid <= 0
            or not _number(threshold)):
        return None
    previous = -1
    expected = [threshold + offset for offset in (-2, 0, 2)]
    for row, threshold in zip(rows, expected):
        if not isinstance(row, dict) or not {"threshold_db", "count", "fraction_valid", "area_km2"} <= row.keys():
            return None
        count = row["count"]
        if (isinstance(count, bool) or not isinstance(count, int)
                or not previous <= count <= valid or count < 0
                or not _number(row["fraction_valid"]) or not 0 <= row["fraction_valid"] <= 1
                or not _number(row["area_km2"]) or row["area_km2"] < 0
                or not _same(row["threshold_db"], threshold)):
            return None
        # Pixel-count contracts do not impose an upper bound. Extra sensitivity
        # rows must not prevent the main validated measurements from rendering
        # when an extreme count cannot participate in finite float arithmetic.
        try:
            fraction = count / valid
            candidate_area = count * area / 1_000_000
        except (OverflowError, ZeroDivisionError):
            return None
        if (not _number(candidate_area)
                or not _same(row["fraction_valid"], fraction)
                or not _same(row["area_km2"], candidate_area)):
            return None
        previous = count
    if (not _number(summary.get("candidate_area_km2")) or not _number(summary.get("candidate_fraction_valid"))
            or not _same(rows[1]["area_km2"], summary["candidate_area_km2"])
            or not _same(rows[1]["fraction_valid"], summary["candidate_fraction_valid"])):
        return None
    return rows


def build_method_facts(fused: FusionResult) -> list[dict]:
    """Build fixed, referenced context after the caller revalidates ``fused``.

Every returned source reference resolves in the retained Phase 7 report.
Unknown optional methods/sensitivity stay unknown; unavailable components do
not acquire processing claims or measurements from these templates.
"""
    facts = []

    def add(fact_id, text, kind, *refs):
        facts.append({"id": fact_id, "text": text, "kind": kind,
                      "source_refs": list(refs)})

    for name, label in _SOURCES.items():
        component = fused.components[name]
        base = f"/fusion/components/{name}"
        if component.status != "available":
            add(f"source.{name}", f"{label}: evidence unavailable; no source measurement or completed processing is claimed.",
                "source", base)
            continue
        add(f"source.{name}", f"Source: {label}. Exact resource identifiers are retained in the underlying evidence report.",
            "source", f"{base}/provenance")
        if name == "gpm":
            count = component.summary["granule_count"]
            add("method.gpm", f"Rainfall processing uses {count} supplied granule(s). The supported processor multiplies precipitation rate by each granule's supplied duration, sums accumulation, and calculates mean and maximum over AOI grid cells valid in every supplied granule. Pixel means are not geographic-area-weighted.",
                "method", f"{base}/summary", f"{base}/evidence")
            add("source_limitation.gpm", "Satellite precipitation estimates and the supplied granule selection limit this rainfall result. The reported maximum is a grid-cell accumulation over the supplied duration, not a point rain-gauge reading or a whole-event maximum.",
                "source_limitation", f"{base}/evidence")
        elif name == "smap":
            add("method.smap", "The supported SMAP processor calculates separate surface and root-zone volumetric soil-moisture statistics from valid AOI grid pixels in one selected state. Each layer excludes its invalid pixels independently; values in m3/m3 are volume fractions, not rainfall depths.",
                "method", f"{base}/evidence")
            add("source_limitation.smap", "SMAP L4 is a gridded model-assimilated soil-moisture product. One selected state does not establish antecedent wetness, saturation everywhere, a trend, or a causal relationship with the radar observation.",
                "source_limitation", f"{base}/provenance", f"{base}/time_basis")
        elif name == "sentinel1":
            evidence, summary = component.evidence, component.summary
            method = evidence.get("method")
            scene = evidence.get("scene")
            supported = (isinstance(method, dict)
                         and all(method.get(key) == value for key, value in _SAR_METHOD.items())
                         and isinstance(scene, dict) and scene.get("polarization") == "VV")
            if supported:
                add("method.sentinel1", f"Sentinel-1 processing converts valid positive VV gamma0 power to dB using 10 * log10(gamma0), then screens AOI pixel centers at backscatter <= {summary['threshold_db']!r} dB. Candidate area is valid candidate-pixel count times native UTM pixel area; it is approximate planimetric area. MeshMind adds no smoothing, resampling or terrain-shadow masking.",
                    "method", f"{base}/summary/threshold_db", f"{base}/evidence/method", f"{base}/evidence/scene", f"{base}/evidence/raster")
            else:
                add("method.sentinel1", f"The retained Sentinel-1 screening threshold is {summary['threshold_db']!r} dB. Full VV conversion, comparison and area-method metadata are unavailable or do not match the supported method; those details are not claimed.",
                    "method", f"{base}/summary/threshold_db", f"{base}/evidence")
            rows = _sensitivity(component) if supported else None
            if rows is None:
                text = "Sentinel-1 threshold sensitivity is unavailable or internally inconsistent; no numerical sensitivity range is claimed."
            else:
                values = "; ".join(f"{row['threshold_db']!r} dB: {row['area_km2']!r} km2" for row in rows)
                text = f"Sentinel-1 candidate-area sensitivity at the screening threshold and +/-2 dB: {values}."
            text += " This describes dependence on the screening parameter, not a confidence interval, probability or validated flood extent."
            add("method.sentinel1_sensitivity", text, "method", f"{base}/evidence")
            add("source_limitation.sentinel1", "Low VV backscatter identifies candidate surface water, not confirmed floodwater. Permanent water, radar shadow and smooth non-water surfaces can cause false positives. Wind-roughened water, vegetation and urban double-bounce can hide water; speckle can create isolated candidates. No pre-event comparison establishes newly inundated area.",
                "source_limitation", f"{base}/evidence")
        else:
            count = component.summary["tile_count"]
            add(f"method.{name}", f"The supported terrain processor combines {count} source tile(s), selects AOI pixel centers and summarizes valid native-grid cells without reprojection or resampling. Each valid pixel receives equal weight; geographic-grid pixels do not have equal ground area. Overlaps use the first valid pixel in sorted tile order. These statistics describe the available AOI cells, not candidate-water cells.",
                "method", f"{base}/summary", f"{base}/evidence")
            if name == "dem":
                text = "Copernicus DEM is a surface model: buildings and vegetation can influence elevation. Heights reference EGM2008, not the local water level. Mean AOI elevation cannot establish water depth or whether the candidate-water pixels are low-lying."
            else:
                text = "HAND measures height above drainage and supplies terrain context; it does not detect floodwater or measure water depth. Masks, nonfinite and negative values are excluded; zero remains valid. Where source tiles lack declared nodata, undeclared positive sentinel values cannot be identified reliably."
            add(f"source_limitation.{name}", text, "source_limitation", f"{base}/evidence")
    return facts
