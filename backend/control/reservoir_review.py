"""Grounded combined review of independent worker aggregates; no local datasets."""

from copy import deepcopy
from datetime import datetime, timezone

from backend.control.alerts import DEMO_NOTICE
from backend.control.fusion import DISCLAIMER
from backend.control.context_dispatch import validate_record
from backend.control.risk_synthesis import build_synthesis_input, validate_synthesis
from backend.shared.risk_contracts import RiskView
from backend.shared.context_contracts import ContextResult, ContextTask
from backend.shared.dam_contracts import DamResult, DamTask

NAMES = {'hydro': 'Hydrometeorology Agent', 'flood': 'Surface Water and Terrain Agent',
         'dam': 'Dam Records Agent'}
DATASETS = {'gpm': 'NASA GPM IMERG rainfall', 'smap': 'NASA SMAP L4 soil moisture',
            'sentinel1': 'Sentinel-1 candidate surface water', 'dem': 'Copernicus DEM elevation',
            'hand': 'HAND height above drainage'}
REASONS = {
    'measured': 'Observed within the requested interval.',
    'partial_temporal_coverage': 'Only part of the requested rainfall interval is available.',
    'static_noncontemporaneous': 'Static terrain context; not a measurement at the historical assessment date.',
    'observation_date_unverified': 'Terrain excluded because its observation date cannot be verified against the historical cutoff.',
    'no_matching_observations': 'The catalog returned no eligible observations for the requested area and interval.',
    'missing_local_data': 'Matching input files are unavailable on the assigned worker.',
    'before_product_coverage': 'The requested period predates this product.',
    'source_unavailable': 'The source could not provide suitable data.',
    'processing_failed': 'The component could not be processed.',
    'invalid_result': 'The component did not pass its result checks.',
    'resource_limit': 'The requested source selection exceeds its processing limit.',
    'authentication_unavailable': 'The assigned worker could not authenticate with the external data provider.',
    'provider_timeout': 'The external data provider did not respond within the acquisition deadline.',
    'download_limit': 'The requested download exceeds the configured acquisition limit.',
}
# These are normal source-selection outcomes, not acquisition/processing errors.
# They still contribute zero coverage to the unchanged confidence calculation.
EXPECTED_ABSENCE_REASONS = frozenset({
    'before_product_coverage', 'no_matching_observations', 'observation_date_unverified',
})
# Match the acquisition workers' fixed lower bounds; intervals end exclusively.
_PRODUCT_STARTS = {
    'gpm': datetime(1998, 1, 1, tzinfo=timezone.utc),
    'smap': datetime(2015, 3, 31, tzinfo=timezone.utc),
    'sentinel1': datetime(2014, 4, 3, tzinfo=timezone.utc),
}


def expected_source_absence(item, end):
    """An expected reason must fit both its product and requested period."""
    if item is None or item.availability != 'unavailable':
        return False
    if item.reason == 'observation_date_unverified':
        return item.component in {'dem', 'hand'}
    start = _PRODUCT_STARTS.get(item.component)
    if start is None:
        return False
    return ((item.reason == 'before_product_coverage' and end <= start)
            or (item.reason == 'no_matching_observations' and end > start))


LIMITS = [
    'Risk is an ordinal screening concern, not a calibrated flood or dam-failure probability, forecast, or emergency instruction.',
    'Confidence is an evidence-coverage score, not the probability that flooding will occur.',
    'Candidate surface water can include permanent reservoir water; it does not establish new flooding.',
    'Static terrain is not contemporaneous hydraulic evidence. No breach model, flood depth, inundation footprint or downstream impact is calculated.',
    'Missing evidence stays unavailable. It is not treated as zero or evidence of safety.',
    'Current reprocessed NASA product versions reconstruct historical observations; these versions are not asserted to have been available to operators at the assessment date.',
]
ORDER = {'unknown': -1, 'low': 0, 'moderate': 1, 'high': 2, 'critical': 3}

# Presentation only: screening and confidence calculations use the typed values.
_METRIC_DISPLAY = {
    'area_mean_total_accumulation_mm': ('Area-mean rainfall accumulation', 'mm', 3),
    'max_cell_total_accumulation_mm': ('Maximum grid-cell rainfall accumulation', 'mm', 3),
    'covered_hours': ('Observed rainfall duration', 'hours', 1),
    'requested_hours': ('Requested rainfall duration', 'hours', 1),
    'granule_count': ('Half-hour rainfall observations', 'count', 0),
    'temporal_coverage_fraction': ('Temporal coverage', 'percent', 1),
    'valid_fraction': ('Valid grid coverage', 'percent', 1),
    'timestamp_utc': ('Observation midpoint (UTC)', 'timestamp', 0),
    'surface_mean_m3_m3': ('Mean surface soil moisture', 'm³/m³', 3),
    'surface_max_m3_m3': ('Maximum surface soil moisture', 'm³/m³', 3),
    'rootzone_mean_m3_m3': ('Mean root-zone soil moisture', 'm³/m³', 3),
    'rootzone_max_m3_m3': ('Maximum root-zone soil moisture', 'm³/m³', 3),
    'surface_valid_fraction': ('Valid surface-moisture coverage', 'percent', 1),
    'rootzone_valid_fraction': ('Valid root-zone moisture coverage', 'percent', 1),
    'candidate_fraction_valid': ('Candidate water fraction of valid area', 'percent', 1),
    'candidate_area_km2': ('Candidate surface-water area', 'km²', 3),
    'threshold_db': ('Backscatter screening threshold', 'dB', 1),
    'mean_m': ('Mean height', 'm', 2),
    'min_m': ('Minimum height', 'm', 2),
    'max_m': ('Maximum height', 'm', 2),
    'median_m': ('Median height', 'm', 2),
    'valid_pixels': ('Valid grid cells', 'count', 0),
    'tile_count': ('Source tiles', 'count', 0),
    'recent_visit_count': ('Visits in the preceding 90 days', 'count', 0),
    'full_pool_visit_count': ('Full-pool visits in the preceding 90 days', 'count', 0),
    'latest_pool_level_mod': ('Latest observed pool level', 'mOD', 3),
    'latest_pool_departure_m': ('Pool departure from 185.67 mOD', 'signed_m', 3),
    'latest_visit_age_days': ('Age of latest operational visit', 'days', 0),
    'latest_supervision_age_days': ('Age of latest supervision observation', 'days', 0),
    'latest_instrumentation_age_days': ('Age since instrumentation record became available', 'days', 0),
    'sealant_defect_fraction': ('Recent visits recording sealant defects', 'percent', 1),
    'blocked_relief_fraction': ('Recent visits recording blocked relief holes', 'percent', 1),
    'seepage_at_full_pool_fraction': ('Full-pool visits recording crest-joint seepage', 'percent', 1),
    'current_spillway_flowing': ('Recent observation records spillway flow', 'boolean', 0),
    'open_maintenance_count': ('Open engineering maintenance items', 'count', 0),
    'long_open_maintenance_count': ('Engineering items open for more than 365 days', 'count', 0),
    'latest_inspection_grade': ('Latest available inspection grade', 'text', 0),
    'known_integrity_action': ('Recorded hydraulic-integrity action', 'boolean', 0),
    'monitoring_gap': ('Pressure-monitoring evidence gap', 'boolean', 0),
}


def display_measurement(dataset, key, value):
    """Format a checked metric without modifying its underlying precision."""
    label, unit, places = _METRIC_DISPLAY[key]
    if value is None:
        formatted = 'Unavailable.'
    elif unit == 'boolean':
        formatted = 'Yes' if value else 'No'
    elif unit == 'count':
        formatted = f'{value:,d}'
    elif unit == 'percent':
        formatted = f'{value * 100:.{places}f}%'
    elif unit == 'signed_m':
        formatted = f'{value:+.{places}f} m'
    elif unit == 'timestamp':
        formatted = value.isoformat().replace('+00:00', 'Z')
    elif unit == 'text':
        formatted = str(value)
    else:
        formatted = f'{value:,.{places}f} {unit}'
    return {'label': f'{dataset}: {label}', 'value': formatted}


def checked_results(plan, records, task_id):
    tasks, results = plan.tasks(task_id), {}
    if not set(records).issubset(tasks):
        raise ValueError('An unrelated worker cannot contribute to this investigation.')
    for role, record in records.items():
        validate_record(record, tasks[role], role)
        outcome, status = record['outcome'], record['status']
        if (outcome is None) != (record['completed_at'] is None):
            raise ValueError('Worker outcome must agree with lifecycle completion.')
        if outcome is None and record['error'] is not None:
            raise ValueError('An active lifecycle cannot contain a terminal error.')
        if status is not None and (not status.get('execution_host') or not status.get('process_instance_id')):
            raise ValueError('Retained worker status requires its process identity.')
        returned = record['result'] is not None
        if returned != (outcome in {'complete', 'partial'}):
            raise ValueError('Returned evidence must agree with the retained outcome.')
        if not returned:
            if outcome is not None and record['error'] is None:
                raise ValueError('An unsuccessful outcome requires its safe operational error.')
            if outcome == 'worker_failed' and (status is None or status['state'] != 'failed'):
                raise ValueError('Worker failure requires a matching terminal status.')
            continue
        if not record['accepted'] or record['error'] is not None or status is None or status['state'] != outcome:
            raise ValueError('Returned evidence requires matching accepted terminal status.')
        task = tasks[role]
        raw = record['result']
        if role == 'dam':
            result = DamResult.model_validate(raw)
            bound = DamTask(task_id=result.task_id, site_id=result.site.id,
                            window=result.window, as_of=result.as_of)
        else:
            result = ContextResult.model_validate(raw)
            bound = ContextTask.model_validate({key: raw[key] for key in ContextTask.model_fields})
        if bound != task or result.worker_id != role + '-worker' or result.status != outcome:
            raise ValueError('Evidence does not match the resolved site, dates and worker.')
        results[role] = result
    return results


def synthesis_input(plan, records, task_id):
    """Send only checked, dated aggregates to the reasoning model."""
    results = checked_results(plan, records, task_id)
    components = {item.component: item for role in ('hydro', 'flood') if role in results
                  for item in results[role].components}
    return build_synthesis_input(components, results.get('dam'), start_time=plan.start,
                                 end_time=plan.end, as_of=plan.as_of)


def build_reservoir_review(plan, records, task_id, prompt, *, synthesis=None):
    results = checked_results(plan, records, task_id)
    components = {item.component: item for role in ('hydro', 'flood') if role in results
                  for item in results[role].components}
    conditions, measurements, sources, processing, coverage_summary = [], [], [], [], []
    qualities = []
    incomplete = False
    for name in DATASETS:
        item = components.get(name)
        available = item is not None and item.availability == 'available'
        expected_absence = expected_source_absence(item, plan.end)
        reason = REASONS[item.reason] if item else 'No validated worker result is available.'
        if item is not None and item.reason in EXPECTED_ABSENCE_REASONS and not expected_absence:
            reason = 'The returned coverage reason does not match this product and requested period.'
        metrics = item.metrics.model_dump() if available else {}
        coverage = (f'{item.observed_start.isoformat()} to {item.observed_end.isoformat()}. '
                    if available and item.observed_start is not None else '') + reason
        sources.append({'dataset': DATASETS[name], 'access': 'Assigned environmental worker',
                        'resources': 'Validated aggregate from the named product.' if available else 'Unavailable.',
                        'coverage': coverage})
        if available:
            coverage_summary.append(f'{DATASETS[name]}: {coverage}')
        if available:
            for key, value in metrics.items():
                measurements.append(display_measurement(DATASETS[name], key, value))
            fractions = [float(value) for key, value in metrics.items() if key.endswith('fraction') and key not in {'candidate_fraction_valid'}]
            quality = min(fractions) if fractions else 1.0
            qualities.append(quality)
            incomplete = incomplete or quality < 1
        else:
            qualities.append(0.0)
            if not expected_absence:
                incomplete = True
    rain, soil = components.get('gpm'), components.get('smap')
    rain_ok = (rain is not None and rain.availability == 'available'
               and rain.metrics.requested_hours == 24 and rain.metrics.temporal_coverage_fraction == 1
               and rain.metrics.valid_fraction >= .8)
    soil_ok = (soil is not None and soil.availability == 'available'
               and soil.metrics.surface_valid_fraction >= .8)
    heavy = rain_ok and rain.metrics.area_mean_total_accumulation_mm >= 50
    wet = soil_ok and soil.metrics.surface_mean_m3_m3 >= .4
    hydro_level = ('high' if heavy and wet else 'moderate' if heavy else 'low') if rain_ok and soil_ok else 'unknown'
    for identifier, label, applicable, triggered, observed, configured in (
        ('H01', 'Area-mean rainfall screening threshold', rain_ok, heavy,
         None if not rain_ok else rain.metrics.area_mean_total_accumulation_mm, '>= 50 mm over a complete 24-hour interval, >= 80% valid area'),
        ('H02', 'Surface-soil moisture screening threshold', soil_ok, wet,
         None if not soil_ok else soil.metrics.surface_mean_m3_m3, '>= 0.40 m3/m3, >= 80% valid area'),
    ):
        conditions.append({'id': identifier, 'condition': label,
                           'observed': 'Unavailable or prerequisites not met.' if observed is None else str(observed),
                           'configured': configured, 'status': 'not-assessable' if not applicable else 'triggered' if triggered else 'not-triggered'})
    level, basis = hydro_level, 'Public environmental screening; site-specific structural condition is not established.'
    confidence = .8 * sum(qualities) / len(qualities)
    dam = results.get('dam')
    limitations = list(LIMITS)
    if dam is not None:
        if ORDER[dam.summary.risk_level] > ORDER[level]:
            level = dam.summary.risk_level
        confidence = .6 * dam.summary.confidence_score + .4 * sum(qualities) / len(qualities)
        basis = 'Combined independent Hydro, Flood and site-specific dam aggregates; the highest assessable screening concern is retained.'
        limitations.extend(dam.limitations)
        for key, value in dam.metrics.model_dump().items():
            measurements.append(display_measurement('Dam records', key, value))
        conditions.extend({'id': rule.rule_id, 'condition': 'Dam screening ' + rule.rule_id,
                           'observed': f'{rule.record_count} supporting records; criterion ' + ('met.' if rule.triggered else 'not met.'),
                           'configured': rule.criterion, 'status': 'triggered' if rule.triggered else 'not-triggered'} for rule in dam.rules)
        sources.append({'dataset': 'Toddbrook dam records', 'access': 'Worker-local analysis; only derived aggregates returned',
                        'resources': f'{dam.evidence.record_count} records. Example opaque references: ' + ', '.join(dam.evidence.record_refs[:6]),
                        'coverage': f'Available as of {dam.as_of}; operational evidence {dam.evidence.first_observation} to {dam.evidence.last_observation}.'})
        coverage_summary.append(f'{sources[-1]["dataset"]}: {sources[-1]["coverage"]}')
    elif plan.location_id == 'toddbrook':
        confidence = min(confidence, .4)
        limitations.append('The private worker did not return usable site-specific evidence; structural concern remains unassessed.')
    else:
        limitations.append('No private dataset is registered for this area. Only Hydro and Flood were dispatched; Toddbrook records were not accessed.')
    if level == 'unknown':
        confidence = min(confidence, .4)
    confidence = round(confidence, 3)
    risk = {'level': level, 'score': {'unknown': None, 'low': 10, 'moderate': 35, 'high': 70, 'critical': 90}[level],
            'confidenceLevel': 'high' if confidence >= .8 else 'moderate' if confidence >= .5 else 'low',
            'confidenceScore': confidence, 'alert': level in {'high', 'critical'},
            'title': 'Risk not assessable' if level == 'unknown' else level.title() + ' flood-risk screening concern',
            'summary': ('Available evidence does not support an overall screening classification.' if level == 'unknown'
                        else 'This historical evidence meets the configured ' + level + '-concern screening criteria.'),
            'basis': basis, 'limitations': list(dict.fromkeys(limitations))}
    risk = RiskView.model_validate(risk).model_dump(mode='json')
    if synthesis is not None:
        synthesis = validate_synthesis(synthesis, synthesis_input(plan, records, task_id))
        level = synthesis['level']
        risk.update(level=level, score={'unknown': None, 'low': 10, 'moderate': 35, 'high': 70, 'critical': 90}[level],
                    alert=level in {'high', 'critical'}, title=synthesis['title'],
                    summary=synthesis['summary'], basis=synthesis['basis'])
        if level == 'unknown':
            confidence = min(confidence, .4)
            risk.update(confidenceScore=confidence, confidenceLevel='low')
        risk = RiskView.model_validate(risk).model_dump(mode='json')
    else:
        risk['basis'] = 'AI synthesis is unavailable for this report. The independent screening result and checked measurements are retained.'
    for role, task in plan.tasks(task_id).items():
        record = records.get(role) or {}
        status = record.get('status') or {}
        duration = 'No completed worker duration available.'
        if status.get('started_at') and status.get('completed_at'):
            from datetime import datetime
            elapsed = (datetime.fromisoformat(status['completed_at']) - datetime.fromisoformat(status['started_at'])).total_seconds()
            duration = f'{elapsed:.6f} seconds.'
        processing.append({'investigation': NAMES[role], 'location': 'Independent ' + role + ' worker',
                           'method': 'Deterministic historical screening aggregates.' if role == 'dam' else 'Existing deterministic geospatial processors over the resolved area and interval.',
                           'duration': duration})
    processing.append({'investigation': 'Combined evidence synthesis', 'location': 'Control',
                       'method': ('AI interpretation of checked aggregate evidence, with validated evidence references.'
                                  if synthesis is not None else 'AI synthesis unavailable; independent screening fallback.'),
                       'duration': 'Included in Control review.'})
    partial = set(results) != set(plan.tasks(task_id)) or level == 'unknown' or incomplete
    if not coverage_summary:
        coverage_summary.append('No numerical measurements were returned for this investigation.')
    context = (f'WGS84 bounds: {plan.bbox.as_tuple()}. All environmental tasks use these exact bounds. '
               'The area is an analysis window, not a delineated catchment or an inundation footprint.')
    briefing = {
        'title': 'Combined flood-risk screening briefing', 'originalRequest': prompt,
        'studyArea': plan.name + '. ' + context,
        'requestedWindow': f'{plan.start.isoformat()} to {plan.end.isoformat()} (end exclusive); as of {plan.as_of}.',
        'actualCoverage': ' '.join(coverage_summary),
        'executionNotice': 'New independent worker execution over historical observations. Current processing does not make those observations current.',
        'partial': partial, 'risk': deepcopy(risk),
        'sections': [
            {'id': 'risk', 'title': risk['title'], 'paragraphs': [risk['summary'], risk['basis'],
              f'Evidence confidence: {risk["confidenceLevel"]} (coverage index {confidence:.3f} on 0–1). This is not flood probability.']},
            *([{'id': 'synthesis', 'title': 'Why these factors matter together',
                'paragraphs': [reason['text'] + ' Evidence: ' + ', '.join(reason['field_refs']) + '.'
                               for reason in synthesis['reasons']]}] if synthesis is not None else []),
            {'id': 'method', 'title': 'How Control combines the evidence', 'paragraphs': [
                'Hydro and Flood always run. Only the exact Toddbrook site also calls its dam-records worker. Results are checked against the same task, location, area and historical cutoff.',
                'When available, AI evaluates interacting rainfall, soil moisture, recent dam condition and hydraulic loading. An existing high or critical Dam concern cannot be downgraded. Candidate water and static terrain are context, not evidence of new flooding or a breach.',
                'AI considers how the measured factors reinforce or counterbalance one another in context. Rainfall with wetter soil, or rainfall pressure alongside dam deterioration, are examples to consider rather than fixed interaction thresholds. Source measurements remain unchanged.',
                'Confidence combines evidence availability and spatial/temporal coverage. With dam evidence: 60% dam evidence score plus 40% mean public-component coverage; without it: 80% of mean public coverage. Unknown risk is capped at 0.40. The score is not a statistical confidence interval.',
                'Displayed measurements are rounded for readability. Screening rules and confidence calculations use the full-precision checked values.',
            ]},
        ],
        'metrics': measurements, 'reviewConditions': conditions, 'sourceProvenance': sources,
        'processingProvenance': processing, 'limitations': risk['limitations'],
        'disclaimer': DISCLAIMER, 'demoNotice': DEMO_NOTICE,
    }
    return risk, briefing
