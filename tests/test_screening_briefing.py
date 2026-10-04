"""Generic HTML leads with the explanation, independent of coverage diagnostics."""

from copy import deepcopy
from html import escape

import pytest

from backend.control.briefing import render_briefing_html
from test_reservoir_presentation import review


@pytest.mark.parametrize('partial', [False, True])
def test_generic_html_opens_with_plain_language_before_indices_and_coverage(tmp_path, partial):
    view, _, _ = review(tmp_path)
    briefing = deepcopy(view['briefing'])
    briefing['partial'] = partial
    briefing['risk']['summary'] = 'The observations warrant an engineering review.'
    briefing['risk']['basis'] = 'Reported spillway conditions explain the concern.'
    html = render_briefing_html(briefing)
    assert html.index(briefing['risk']['summary']) < html.index(briefing['risk']['basis'])
    assert html.index(briefing['risk']['basis']) < html.index('<details>')
    assert html.index(briefing['risk']['summary']) < html.index('aria-label="Execution context"')
    assert html.index(briefing['risk']['summary']) < html.index('Study area and time coverage')
    assert 'Partial or unreported spatial coverage' not in html
    assert 'Some evidence needs attention' not in html
    assert 'Screening briefing prepared from the available evidence.' in html
    assert 'role="alert"' in html
    assert 'Source provenance' in html and 'not-assessable' not in html
    assert 'Amalga · Analyst support' in html
    assert 'MeshMind' not in html
    assert 'These indices are not probabilities' in html


def test_plain_language_export_remains_escaped_and_keeps_operational_error_details(tmp_path):
    view, _, _ = review(tmp_path, fail={'hydro'})
    briefing = deepcopy(view['briefing'])
    briefing['risk']['summary'] = '<script>alert("unsafe")</script>'
    briefing['risk']['basis'] = '<img src=x onerror=unsafe()>'
    html = render_briefing_html(briefing)
    assert '<script>' not in html and '<img' not in html
    assert escape(briefing['risk']['summary'], quote=True) in html
    assert escape(briefing['risk']['basis'], quote=True) in html
    assert 'No validated worker result is available.' in html
    assert 'No completed worker duration available.' in html


def test_export_filters_routine_source_notes_without_mutating_values_or_rules(tmp_path):
    view, _, _ = review(tmp_path)
    briefing = deepcopy(view['briefing'])
    briefing['metrics'] = [{'label': 'Measured rain', 'value': '0 mm'},
                           {'label': 'Absent product', 'value': 'Unavailable.'}]
    briefing['sourceProvenance'] = [
        {'dataset': 'Measured rainfall', 'access': 'NASA',
         'resources': 'Exact public identifier unavailable for one or more resources; private paths and URLs are omitted.',
         'coverage': '2007-12-09T00:00:00Z to 2007-12-09T03:00:00Z. Only part of the requested rainfall interval is available.'},
        {'dataset': 'Absent soil', 'access': 'NASA', 'resources': 'Unavailable.',
         'coverage': 'The requested period predates this product.'},
        {'dataset': 'Failed imagery', 'access': 'Worker', 'resources': 'Unavailable.',
         'coverage': 'The assigned worker could not authenticate with the external data provider.'},
    ]
    briefing['reviewConditions'] = [
        {'id': 'R1', 'condition': 'Assessed criterion', 'observed': '0 mm', 'configured': '> 50 mm', 'status': 'not-triggered'},
        {'id': 'R2', 'condition': 'Unassessed criterion', 'observed': 'Unavailable', 'configured': '> 0.4', 'status': 'not-assessable'},
    ]
    original = deepcopy(briefing)
    html = render_briefing_html(briefing)
    assert briefing == original
    assert '0 mm' in html and 'Assessed criterion' in html
    assert 'Absent product' not in html and 'Absent soil' not in html
    assert 'Unassessed criterion' not in html
    assert '2007-12-09T03:00:00Z' in html
    assert 'Only part of the requested rainfall interval is available.' not in html
    assert 'could not authenticate' in html
    assert 'Exact public identifier unavailable' in html
    assert '<script' not in html
    assert "default-src 'none'" in html


def test_export_keeps_unknown_risk_explicit_with_null_score(tmp_path):
    view, _, _ = review(tmp_path)
    briefing = deepcopy(view['briefing'])
    briefing['risk'].update(level='unknown', score=None, alert=False,
                            confidenceLevel='low', confidenceScore=0.2,
                            title='Risk not assessable')
    html = render_briefing_html(briefing)
    assert 'Risk not assessable' in html and 'Not assessable' in html
    assert 'role="alert"' not in html and '0.200 on a 0–1 evidence index' in html


def test_amalga_export_brands_generated_prose_but_preserves_original_user_context(tmp_path):
    view, _, _ = review(tmp_path)
    briefing = deepcopy(view['briefing'])
    briefing['originalRequest'] = 'My original MeshMind request <context>'
    briefing['sections'].append({'id': 'legacy-method', 'title': 'MeshMind processing',
                                'paragraphs': ['MeshMind raster processing.']})
    next(row for row in briefing['sourceProvenance'] if row['resources'] != 'Unavailable.')['access'] = 'MeshMind checked source'
    original = deepcopy(briefing)
    html = render_briefing_html(briefing)
    assert 'My original MeshMind request &lt;context&gt;' in html
    assert 'Amalga processing' in html and 'Amalga raster processing.' in html
    assert 'Amalga checked source' in html
    assert briefing == original


@pytest.mark.parametrize('level', ['high', 'unknown'])
def test_export_risk_prose_filters_exact_routine_sentence_only(tmp_path, level):
    view, _, _ = review(tmp_path)
    briefing = deepcopy(view['briefing'])
    routine = 'DEM and HAND are unavailable, so local topographic screening cannot be applied here.'
    driver = 'Rainfall of 25 mm reinforces concern from recorded dam deterioration.'
    briefing['risk'].update(level=level, score=70 if level == 'high' else None,
                            alert=level == 'high', confidenceLevel='low', confidenceScore=0.2,
                            summary=driver, basis=f'{driver} {routine}')
    original = deepcopy(briefing)
    html = render_briefing_html(briefing)
    assert driver in html
    assert (routine in html) == (level == 'unknown')
    assert briefing == original


def test_export_preserves_mixed_measurement_dam_and_operational_risk_caveats(tmp_path):
    view, _, _ = review(tmp_path)
    for caveat in [
        'DEM and HAND are unavailable, while rainfall of 25 mm reinforces the recorded dam concern.',
        'Dam monitoring records are unavailable, so the structural condition is uncertain.',
        'The external data provider could not authenticate, so the worker returned no observations.',
        'DEM and HAND are unavailable, so local topographic screening cannot be applied here.',
    ]:
        briefing = deepcopy(view['briefing'])
        briefing['risk']['basis'] = caveat
        assert caveat in render_briefing_html(briefing)
