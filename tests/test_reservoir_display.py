"""Human-readable display units must not alter checked measurement precision."""

from datetime import datetime, timezone

from backend.control.reservoir_review import _METRIC_DISPLAY, display_measurement
from backend.shared.context_contracts import HeightMetrics, RainMetrics, SoilMetrics, WaterMetrics
from backend.shared.dam_contracts import DamMetrics


def test_all_current_public_metric_fields_have_explicit_display_labels_and_units():
    fields = set().union(*(set(model.model_fields) for model in (HeightMetrics, RainMetrics, SoilMetrics, WaterMetrics, DamMetrics)))
    assert fields == set(_METRIC_DISPLAY)
    assert all('_' not in label for label, _unit, _places in _METRIC_DISPLAY.values())


def test_units_rounding_counts_timestamps_and_unknown_values_remain_distinct():
    assert display_measurement('Rainfall', 'area_mean_total_accumulation_mm', 5.123456)['value'] == '5.123 mm'
    assert display_measurement('Soil', 'surface_mean_m3_m3', .408494919)['value'] == '0.408 m³/m³'
    assert display_measurement('Water', 'candidate_area_km2', 1.25)['value'] == '1.250 km²'
    assert display_measurement('Dam', 'sealant_defect_fraction', 1 / 3)['value'] == '33.3%'
    assert display_measurement('Dam', 'latest_pool_level_mod', 185.673)['value'] == '185.673 mOD'
    assert display_measurement('Dam', 'latest_pool_departure_m', .003)['value'] == '+0.003 m'
    assert display_measurement('Dam', 'latest_pool_departure_m', -.003)['value'] == '-0.003 m'
    assert display_measurement('Terrain', 'valid_pixels', 12345)['value'] == '12,345'
    assert display_measurement('Dam', 'latest_visit_age_days', 7)['value'] == '7 days'
    assert display_measurement('Dam', 'current_spillway_flowing', False)['value'] == 'No'
    assert display_measurement('Dam', 'current_spillway_flowing', True)['value'] == 'Yes'
    assert display_measurement('Dam', 'current_spillway_flowing', None)['value'] == 'Unavailable.'
    assert display_measurement('Dam', 'latest_inspection_grade', 'D')['value'] == 'D'
    stamp = datetime(2019, 7, 31, 1, 30, tzinfo=timezone.utc)
    assert display_measurement('Soil', 'timestamp_utc', stamp)['value'] == '2019-07-31T01:30:00Z'


def test_formatting_does_not_mutate_precision_of_worker_measurements():
    metrics = RainMetrics(area_mean_total_accumulation_mm=49.999999, max_cell_total_accumulation_mm=70,
                          covered_hours=24, requested_hours=24, granule_count=48,
                          temporal_coverage_fraction=1, valid_fraction=1)
    before = metrics.model_dump()
    rows = [display_measurement('Rainfall', key, value) for key, value in before.items()]
    assert rows[0]['value'] == '50.000 mm'
    assert metrics.model_dump() == before
    assert metrics.area_mean_total_accumulation_mm < 50
