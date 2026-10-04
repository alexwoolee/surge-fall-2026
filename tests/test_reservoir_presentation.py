"""Expected historical absences are source notes; operational failures remain visible."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from backend.control.briefing import render_briefing_html
from backend.control.investigation_plan import resolve_prompt
from backend.control.reservoir_review import DATASETS, REASONS, build_reservoir_review, expected_source_absence
from backend.control.reservoir_web import ReservoirService, create_reservoir_app
from backend.shared.context_contracts import unavailable
from test_reservoir_control import (
    OTHER, factory_with_workers, settings, submit, wait_finished,
)


HISTORICAL = 'Assess flood risk at Toddbrook Reservoir as of 2007-12-09.'
EXPECTED = {
    'gpm': 'no_matching_observations', 'smap': 'before_product_coverage',
    'sentinel1': 'before_product_coverage', 'dem': 'observation_date_unverified',
    'hand': 'observation_date_unverified',
}


def review(tmp_path, *, reasons=None, prompt=HISTORICAL, fail=(), measured=False):
    def mutate(role, result):
        if role != 'dam':
            for item in result['components']:
                if item['availability'] == 'unavailable':
                    item['reason'] = (reasons or EXPECTED)[item['component']]
    factory, _, _ = factory_with_workers(mutation=mutate, fail=fail, measured=measured)
    service = ReservoirService(settings(), history_dir=tmp_path, client_factory=factory)
    with TestClient(create_reservoir_app(service)) as client:
        identifier = submit(client, prompt)
        view = wait_finished(client, identifier)
        html = client.get(f'/sessions/{identifier}/briefing').text
        assert client.get('/sessions').json()['sessions'][0]['status'] == view['status']
    return view, html, service.sessions[identifier]


def test_expected_2007_gaps_produce_a_normal_assessable_briefing_without_changing_risk(tmp_path):
    view, html, session = review(tmp_path / 'expected')
    baseline, _, _ = review(tmp_path / 'failure', reasons=dict.fromkeys(DATASETS, 'source_unavailable'))
    briefing = view['briefing']
    assert view['status'] == 'briefing-ready' and briefing['partial'] is False
    assert all(worker['status'] == 'complete' and worker['validated'] for worker in view['workers'].values())
    assert all('partial' not in worker['summary'].lower() for worker in view['workers'].values())
    assert session['records']['hydro']['result']['status'] == 'partial'
    assert session['records']['flood']['result']['status'] == 'partial'
    assert view['risk'] == baseline['risk']  # No scoring/coverage normalization.
    assert view['risk']['confidenceScore'] == .36
    assert view['risk']['level'] == 'critical' and view['risk']['alert'] is True
    assert not any(row['label'] in DATASETS.values() for row in briefing['metrics'])
    for source in briefing['sourceProvenance'][:5]:
        component = next(key for key, value in DATASETS.items() if value == source['dataset'])
        assert source['resources'] == 'Unavailable.'
        assert source['coverage'] == REASONS[EXPECTED[component]]
        assert source['coverage'] not in briefing['actualCoverage']
        assert source['coverage'] not in html  # Routine gaps stay in retained evidence, not the report display.
    assert all(condition['status'] == 'not-assessable' for condition in briefing['reviewConditions'][:2])
    assert 'Partial or unreported spatial coverage' not in html
    assert 'Screening briefing prepared from the available evidence.' in html
    assert 'role="alert"' in html


@pytest.mark.parametrize('reason', [
    'authentication_unavailable', 'provider_timeout', 'processing_failed',
    'invalid_result', 'source_unavailable', 'missing_local_data',
    'resource_limit', 'download_limit',
])
def test_source_errors_remain_in_technical_notes_without_partial_screen_labels(tmp_path, reason):
    view, html, _ = review(tmp_path, reasons={**EXPECTED, 'gpm': reason})
    briefing = view['briefing']
    assert view['status'] == 'briefing-ready' and briefing['partial'] is True
    assert not any(row['label'] == DATASETS['gpm'] for row in briefing['metrics'])
    assert REASONS[reason] not in briefing['actualCoverage']
    assert any(row['dataset'] == DATASETS['gpm'] and row['coverage'] == REASONS[reason]
               for row in briefing['sourceProvenance'])
    assert REASONS[reason] in html
    assert view['risk']['level'] == 'critical' and view['risk']['confidenceScore'] == .36
    assert 'Screening briefing prepared from the available evidence.' in html


@pytest.mark.parametrize('role', ['hydro', 'flood', 'dam'])
def test_missing_workers_are_not_relabelled_as_expected_source_absence(tmp_path, role):
    view, html, _ = review(tmp_path, fail={role})
    assert view['status'] == 'briefing-ready' and view['briefing']['partial'] is True
    assert view['workers'][role]['status'] == 'down'
    assert view['workers'][role]['returned'] is False
    assert 'Screening briefing prepared from the available evidence.' in html


def test_an_unassessable_risk_is_never_presented_as_a_normal_classified_result(tmp_path):
    view, html, _ = review(tmp_path, prompt=OTHER)
    assert view['status'] == 'briefing-ready'
    assert view['risk']['level'] == 'unknown' and view['risk']['score'] is None
    assert view['risk']['confidenceScore'] == 0 and view['risk']['alert'] is False
    assert all(row['status'] == 'not-assessable' for row in view['reviewConditions'])
    assert len(view['briefing']['sourceProvenance']) == 5
    assert view['risk']['summary'] in html


def test_expected_terrain_absence_does_not_mask_incomplete_measured_coverage(tmp_path):
    view, _, session = review(tmp_path, measured=True)
    assert view['status'] == 'briefing-ready'
    records = deepcopy(session['records'])
    hydro = records['hydro']
    hydro['result']['components'][0]['metrics']['valid_fraction'] = .5
    hydro['outcome'] = hydro['status']['state'] = hydro['result']['status'] = 'partial'
    plan = resolve_prompt(session['prompt'])
    risk, briefing = build_reservoir_review(plan, records, session['id'], session['prompt'])
    assert briefing['partial'] is True
    assert risk['confidenceScore'] < view['risk']['confidenceScore']
    assert briefing['reviewConditions'][0]['status'] == 'not-assessable'
    assert any(row['label'].endswith('Valid grid coverage') and row['value'] == '50.0%'
               for row in briefing['metrics'])
    assert 'Screening briefing prepared from the available evidence.' in render_briefing_html(briefing)


@pytest.mark.parametrize('component,boundary', [
    ('gpm', '1998-01-01'), ('smap', '2015-03-31'), ('sentinel1', '2014-04-03'),
])
def test_expected_product_absence_checks_the_exclusive_coverage_boundary(component, boundary):
    end = datetime.fromisoformat(boundary).replace(tzinfo=timezone.utc)
    before = unavailable(component, 'before_product_coverage')
    empty = unavailable(component, 'no_matching_observations')
    assert expected_source_absence(before, end)
    assert not expected_source_absence(empty, end)
    assert not expected_source_absence(before, end + timedelta(seconds=1))
    assert expected_source_absence(empty, end + timedelta(seconds=1))
    assert not expected_source_absence(unavailable(component, 'observation_date_unverified'), end)


@pytest.mark.parametrize('component,reason,as_of', [
    ('gpm', 'observation_date_unverified', '2007-12-09'),
    ('sentinel1', 'observation_date_unverified', '2007-12-09'),
    ('gpm', 'before_product_coverage', '2007-12-09'),
    ('smap', 'before_product_coverage', '2019-08-01'),
    ('sentinel1', 'before_product_coverage', '2019-08-01'),
    ('smap', 'no_matching_observations', '2007-12-09'),
    ('dem', 'no_matching_observations', '2007-12-09'),
    ('hand', 'before_product_coverage', '2007-12-09'),
])
def test_malformed_expected_reason_is_not_normalized_or_repeated_as_a_false_fact(tmp_path, component, reason, as_of):
    reasons = {key: ('observation_date_unverified' if key in {'dem', 'hand'} else 'no_matching_observations')
               for key in DATASETS} if as_of.startswith('2019') else EXPECTED
    view, html, session = review(tmp_path, reasons={**reasons, component: reason},
                                prompt=f'Assess flood risk at Toddbrook Reservoir as of {as_of}.')
    assert view['status'] == 'briefing-ready' and view['briefing']['partial'] is True
    diagnostic = 'The returned coverage reason does not match this product and requested period.'
    assert not any(row['label'] == DATASETS[component] for row in view['briefing']['metrics'])
    assert any(row['dataset'] == DATASETS[component] and row['coverage'] == diagnostic
               for row in view['briefing']['sourceProvenance'])
    assert diagnostic not in view['actualCoverage'] and diagnostic in html
    assert view['risk']['level'] == 'critical' and view['risk']['confidenceScore'] == .36
    result = session['records']['hydro' if component in {'gpm', 'smap'} else 'flood']['result']
    assert next(item['reason'] for item in result['components'] if item['component'] == component) == reason
