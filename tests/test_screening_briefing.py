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
    assert 'Source provenance' in html and 'not-assessable' in html
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
