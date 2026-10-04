"""No-network checks for AI input privacy, bound citations and saved synthesis."""

import asyncio
from copy import deepcopy
from datetime import timedelta
import json

import pytest

from backend.control.investigation_plan import resolve_prompt
from backend.control.openai_client import AgentAPIError
from backend.control.risk_synthesis import build_synthesis_input, synthesize_risk, validate_synthesis
from test_reservoir_control import TOD, context_result, dam_result


def catalog(*, measured=True, private=True):
    plan = resolve_prompt(TOD)
    tasks = plan.tasks('ai-synthesis-test')
    components = {row.component: row for role in ('hydro', 'flood')
                  for row in context_result(tasks[role], measured=measured).components}
    private_result = dam_result(tasks['dam']) if private else None
    return build_synthesis_input(components, private_result, start_time=plan.start, end_time=plan.end, as_of=plan.as_of)


def valid(value, level=None):
    level = level or value['protected_level']
    refs = (['dam.summary.risk_level', 'dam.summary.integrity_concern']
            if 'dam.summary.risk_level' in value['facts'] else
            ['gpm.metrics.area_mean_total_accumulation_mm'] if 'gpm.metrics.area_mean_total_accumulation_mm' in value['facts'] else
            ['gpm.availability'])
    return {'level': level, 'title': 'Risk not assessable' if level == 'unknown' else level.title()+' flood-risk screening concern',
            'summary': 'The available factors warrant a combined screening review.',
            'basis': 'The supplied evidence is interpreted together within the requested cutoff.',
            'reasons': [{'text': 'The supplied findings support the stated screening concern.', 'field_refs': refs}],
            'evidence_digest': value['evidence_digest']}


def response(value):
    return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed',
                                              'content': [{'type': 'output_text', 'text': json.dumps(value)}]}]}


class FakeClient:
    def __init__(self, output):
        self.output, self.calls = output, []
    async def create(self, **payload):
        self.calls.append(payload)
        return self.output


def test_catalog_contains_only_selected_aggregates_without_reservoir_identity():
    value = catalog()
    encoded = json.dumps(value)
    assert 'dam.metrics.sealant_defect_fraction' in value['facts']
    assert 'gpm.metrics.area_mean_total_accumulation_mm' in value['facts']
    assert value['protected_level'] == 'critical'
    for private in ('Toddbrook', 'toddbrook', 'Whaley', 'latitude', 'longitude', 'bbox', 'record_refs',
                    'task_id', 'confidence_score', 'r_000', 'private_data', 'prompt', 'site_id'):
        assert private not in encoded
    assert value == catalog()


def test_single_responses_request_uses_strict_schema_and_no_tools():
    value = catalog()
    output = valid(value)
    client = FakeClient(response(output))
    assert asyncio.run(synthesize_risk(client, value)) == output
    assert len(client.calls) == 1
    request = client.calls[0]
    assert set(request) == {'instructions', 'input', 'text'}
    assert 'tools' not in request and 'previous_response_id' not in request
    assert json.loads(request['input'][0]['content']) == value
    format = request['text']['format']
    assert format['type'] == 'json_schema' and format['strict'] is True
    assert format['schema']['additionalProperties'] is False
    assert format['schema']['properties']['reasons']['items']['properties']['field_refs']['items']['enum'] == list(value['facts'])
    assert 'not independent checkboxes or fixed interaction thresholds' in request['instructions']
    assert 'Do not enumerate absent' in request['instructions']
    assert 'volumetric water content, not percent saturation' in request['instructions']


def test_interpretation_is_model_supplied_not_a_new_threshold_table():
    value = catalog(private=False)
    for level in ('low', 'moderate', 'high'):
        output = valid(value, level)
        assert asyncio.run(synthesize_risk(FakeClient(response(output)), value))['level'] == level


@pytest.mark.parametrize('level', ['unknown', 'low', 'moderate', 'high'])
def test_a_critical_dam_alert_cannot_be_silently_downgraded(level):
    value = catalog()
    with pytest.raises(ValueError): validate_synthesis(valid(value, level), value)


def test_output_and_input_do_not_gain_ai_confidence_fields():
    value = catalog()
    output = valid(value)
    before = deepcopy(value)
    assert validate_synthesis(output, value) == output
    assert value == before
    output['confidence'] = .99
    with pytest.raises(ValueError): validate_synthesis(output, value)


@pytest.mark.parametrize('change', ['unknown_ref', 'duplicate_ref', 'no_ref', 'uncited_number', 'wrong_digest', 'wrong_title', 'extra_reason_field'])
def test_unbound_or_malformed_synthesis_is_rejected(change):
    value = catalog()
    output = valid(value)
    if change == 'unknown_ref': output['reasons'][0]['field_refs'] = ['future.incident']
    elif change == 'duplicate_ref': output['reasons'][0]['field_refs'] *= 2
    elif change == 'no_ref': output['reasons'][0]['field_refs'] = []
    elif change == 'uncited_number': output['summary'] = 'Rainfall was 999 mm.'
    elif change == 'wrong_digest': output['evidence_digest'] = '0'*64
    elif change == 'wrong_title': output['title'] = 'Low flood-risk screening concern'
    else: output['reasons'][0]['threshold'] = 25
    with pytest.raises(ValueError): validate_synthesis(output, value)


@pytest.mark.parametrize('text', ['Rainfall reached 999mm.', 'Water covered 999km.', 'Monitoring is 999days old.',
                                 'Moisture reached .999m3/m3.', 'Rainfall was above normal.',
                                 'Flooding is confirmed.', 'The dam has failed.', 'Toddbrook is at risk.'])
def test_invented_measurements_and_unsupported_incident_claims_fail(text):
    value = catalog()
    output = valid(value)
    output['reasons'][0]['text'] = text
    with pytest.raises(ValueError): validate_synthesis(output, value)


@pytest.mark.parametrize('text', [
    'This does not establish that the dam has failed.',
    'The data do not show rainfall was above normal.',
    'This assessment does not mean the site will flood.',
    'There is no evidence that flooding is confirmed.',
    'It cannot be concluded that the dam will fail.',
])
def test_explicit_evidence_disclaimers_are_not_affirmative_claims(text):
    value = catalog()
    output = valid(value)
    output['reasons'][0]['text'] = text
    assert validate_synthesis(output, value) == output


@pytest.mark.parametrize('text', [
    'The evidence establishes that the dam has failed.',
    'This does not establish that the dam has failed, but the dam has failed.',
    'The data do not show rainfall was above normal. However, rainfall was above normal.',
    'It is false that the data do not show rainfall was above normal.',
    'This assessment does not mean the site will flood; flooding is confirmed.',
    'This does not establish that Toddbrook is at risk.',
    'There is no evidence that https://example.test explains this.',
    'This does not establish that the dam has failed after 999mm of rain.',
])
def test_negation_does_not_exempt_other_claims_names_or_invented_measurements(text):
    value = catalog()
    output = valid(value)
    output['reasons'][0]['text'] = text
    with pytest.raises(ValueError): validate_synthesis(output, value)


def test_known_product_label_is_not_a_measurement_but_neighboring_numbers_still_are():
    value = catalog()
    output = valid(value)
    reason = {'text': 'Sentinel-1 observations are unavailable.', 'field_refs': ['sentinel1.availability']}
    output['reasons'].append(reason)
    assert validate_synthesis(output, value) == output
    for text in ('Sentinel-1 measured 999mm.', 'Sentinel-999 observations are unavailable.',
                 'Sentinel-1.999 observations are unavailable.'):
        reason['text'] = text
        with pytest.raises(ValueError): validate_synthesis(output, value)


def test_exact_cited_measurements_are_allowed_without_conversions():
    value = catalog()
    output = valid(value)
    output['reasons'][0]['field_refs'].append('gpm.metrics.area_mean_total_accumulation_mm')
    output['reasons'][0]['text'] = 'The supplied rainfall total is 60mm, alongside the recorded integrity concern.'
    assert validate_synthesis(output, value) == output
    output['reasons'][0]['text'] = 'The supplied rainfall total is 6cm.'
    with pytest.raises(ValueError): validate_synthesis(output, value)


def test_current_evidence_digest_prevents_replaying_a_previous_interpretation():
    before = catalog()
    changed = deepcopy(before)
    changed['facts']['gpm.metrics.area_mean_total_accumulation_mm']['value'] = 10
    with pytest.raises(ValueError): validate_synthesis(valid(before), changed)
    plan = resolve_prompt(TOD)
    request = plan.tasks('changed')['hydro']
    components = {row.component: row for row in context_result(request, measured=True).components}
    rain = components['gpm'].metrics
    rain.area_mean_total_accumulation_mm = 10
    actual_new = build_synthesis_input(components, None, start_time=plan.start, end_time=plan.end, as_of=plan.as_of)
    with pytest.raises(ValueError): validate_synthesis(valid(before), actual_new)


def test_no_observations_require_unknown_without_fabricating_zeros():
    value = catalog(measured=False, private=False)
    assert value['has_assessable_evidence'] is False
    assert not any(fact['kind'] == 'measurement' for fact in value['facts'].values())
    assert validate_synthesis(valid(value, 'unknown'), value)['level'] == 'unknown'
    with pytest.raises(ValueError): validate_synthesis(valid(value, 'low'), value)


def test_future_observations_and_unbound_dam_dates_are_rejected_before_model_call():
    plan = resolve_prompt(TOD)
    tasks = plan.tasks('date-check')
    components = {row.component: row for row in context_result(tasks['hydro'], measured=True).components}
    components['gpm'].observed_end += timedelta(days=1)
    with pytest.raises(ValueError):
        build_synthesis_input(components, None, start_time=plan.start, end_time=plan.end, as_of=plan.as_of)
    private = dam_result(tasks['dam'])
    with pytest.raises(ValueError):
        build_synthesis_input({}, private, start_time=plan.start-timedelta(days=1), end_time=plan.start,
                              as_of=plan.as_of-timedelta(days=1))


@pytest.mark.parametrize('bad', [
    {'status': 'incomplete', 'output': []},
    {'status': 'completed', 'output': [{'type': 'function_call', 'name': 'web_search'}]},
    {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant', 'content': [{'type': 'refusal'}]}]},
])
def test_nonfinal_tool_and_refusal_outputs_never_become_classifications(bad):
    with pytest.raises(AgentAPIError): asyncio.run(synthesize_risk(FakeClient(bad), catalog()))


def test_transport_failure_is_not_retried_or_converted_to_an_ai_result():
    class Broken:
        calls = 0
        async def create(self, **kwargs):
            self.calls += 1
            raise AgentAPIError('timeout')
    client = Broken()
    with pytest.raises(AgentAPIError, match='time limit'):
        asyncio.run(synthesize_risk(client, catalog()))
    assert client.calls == 1
