"""
MeshMind hydrometeorology worker service.

This module combines deterministic GPM rainfall processing
and SMAP soil-moisture processing into one structured result.

It does not:
- search external APIs
- download data
- call an LLM
- apply flood/disaster conclusions

Those concerns belong to later layers.
"""

from pathlib import Path
from typing import Any
from uuid import uuid4

from backend.workers.hydro.gpm import (
    GPMProcessingError,
    analyze_gpm_granules,
)

from backend.workers.hydro.smap import (
    SMAPProcessingError,
    analyze_smap_granule,
)


HYDRO_ANALYSIS_TYPE = "hydrometeorology"

HYDRO_WORKER_ID = "hydro-worker"


class HydroWorkerError(Exception):
    """Raised when the hydro worker cannot complete safely."""


def _bbox_to_dict(
    bbox: tuple[float, float, float, float],
) -> dict[str, float]:
    """
    Convert a bbox tuple into the shared readable form.
    """

    west, south, east, north = bbox

    return {
        "west": float(west),
        "south": float(south),
        "east": float(east),
        "north": float(north),
    }


def _validate_input_files(
    gpm_files: list[str | Path],
    smap_file: str | Path,
) -> tuple[list[Path], Path]:
    """
    Validate that the worker received real local resources.

    The individual processors perform deeper format validation.
    """

    if not gpm_files:
        raise HydroWorkerError(
            "At least one GPM granule is required."
        )

    normalized_gpm_files = [
        Path(path)
        for path in gpm_files
    ]

    normalized_smap_file = Path(
        smap_file
    )

    missing_gpm_files = [
        path
        for path in normalized_gpm_files
        if not path.exists()
    ]

    if missing_gpm_files:
        missing_names = ", ".join(
            str(path)
            for path in missing_gpm_files
        )

        raise HydroWorkerError(
            "One or more GPM resources do not exist: "
            f"{missing_names}"
        )

    if not normalized_smap_file.exists():
        raise HydroWorkerError(
            "SMAP resource does not exist: "
            f"{normalized_smap_file}"
        )

    return (
        normalized_gpm_files,
        normalized_smap_file,
    )


def _build_summary(
    gpm_result: dict[str, Any],
    smap_result: dict[str, Any],
) -> dict[str, Any]:
    """
    Extract the small set of numerical values that later
    layers will usually need.

    These values are copied from deterministic processor
    results. Nothing is inferred by an LLM.
    """

    rainfall = gpm_result[
        "rainfall"
    ]

    surface = smap_result[
        "surface_soil_moisture"
    ]

    rootzone = smap_result[
        "rootzone_soil_moisture"
    ]

    return {
        "rainfall": {
            "area_mean_total_accumulation_mm": float(
                rainfall[
                    "area_mean_total_accumulation_mm"
                ]
            ),
            "max_cell_total_accumulation_mm": float(
                rainfall[
                    "max_cell_total_accumulation_mm"
                ]
            ),
            "duration_hours": float(
                gpm_result[
                    "total_duration_hours"
                ]
            ),
            "granule_count": int(
                gpm_result[
                    "granule_count"
                ]
            ),
        },
        "soil_moisture": {
            "surface_mean_m3_m3": float(
                surface[
                    "mean"
                ]
            ),
            "surface_max_m3_m3": float(
                surface[
                    "maximum"
                ]
            ),
            "rootzone_mean_m3_m3": float(
                rootzone[
                    "mean"
                ]
            ),
            "rootzone_max_m3_m3": float(
                rootzone[
                    "maximum"
                ]
            ),
            "smap_timestamp_utc": smap_result[
                "timestamp_utc"
            ],
        },
    }


def run_hydro_analysis(
    gpm_files: list[str | Path],
    smap_file: str | Path,
    bbox: tuple[float, float, float, float],
    *,
    task_id: str | None = None,
) -> dict[str, Any]:
    """
    Execute one deterministic MeshMind hydro analysis.

    Parameters
    ----------
    gpm_files:
        Local GPM IMERG half-hourly HDF5 granules covering
        the requested rainfall-analysis period.

    smap_file:
        Local SMAP L4 HDF5 granule representing the selected
        soil state.

    bbox:
        Geographic bounding box:

        (west, south, east, north)

    task_id:
        Optional externally supplied task identifier.

        If omitted, the deterministic worker wrapper creates
        an identifier for application tracking only.

    Returns
    -------
    dict
        Structured hydrometeorology result containing the
        underlying deterministic GPM and SMAP evidence plus
        a compact numerical summary.
    """

    (
        normalized_gpm_files,
        normalized_smap_file,
    ) = _validate_input_files(
        gpm_files,
        smap_file,
    )

    resolved_task_id = (
        task_id
        if task_id is not None
        else str(uuid4())
    )

    # -----------------------------------------------------
    # GPM rainfall processing
    # -----------------------------------------------------

    try:
        gpm_result = analyze_gpm_granules(
            normalized_gpm_files,
            bbox,
        )

    except GPMProcessingError as exc:
        raise HydroWorkerError(
            "GPM rainfall analysis failed: "
            f"{exc}"
        ) from exc

    # -----------------------------------------------------
    # SMAP soil-state processing
    # -----------------------------------------------------

    try:
        smap_result = analyze_smap_granule(
            normalized_smap_file,
            bbox,
        )

    except SMAPProcessingError as exc:
        raise HydroWorkerError(
            "SMAP soil-moisture analysis failed: "
            f"{exc}"
        ) from exc

    # -----------------------------------------------------
    # Build compact deterministic summary
    # -----------------------------------------------------

    summary = _build_summary(
        gpm_result,
        smap_result,
    )

    # -----------------------------------------------------
    # Structured worker result
    # -----------------------------------------------------

    result = {
        "task_id": resolved_task_id,
        "worker_id": HYDRO_WORKER_ID,
        "analysis_type": HYDRO_ANALYSIS_TYPE,
        "status": "complete",
        "bbox": _bbox_to_dict(
            bbox
        ),
        "sources": [
            {
                "name": "NASA GPM IMERG",
                "product": gpm_result[
                    "product"
                ],
                "version": gpm_result[
                    "version"
                ],
                "resources_used": [
                    path.name
                    for path
                    in normalized_gpm_files
                ],
            },
            {
                "name": "NASA SMAP L4",
                "product": smap_result[
                    "product"
                ],
                "version": smap_result[
                    "version"
                ],
                "resources_used": [
                    normalized_smap_file.name
                ],
            },
        ],
        "summary": summary,
        "evidence": {
            "gpm": gpm_result,
            "smap": smap_result,
        },
        "limitations": [
            (
                "Rainfall values are derived from GPM IMERG "
                "grid cells intersecting the requested AOI."
            ),
            (
                "Soil moisture represents the selected SMAP "
                "L4 model state and is not accumulated over "
                "the rainfall time window."
            ),
            (
                "This result is environmental analysis "
                "evidence, not an emergency-response or "
                "evacuation determination."
            ),
        ],
    }

    return result