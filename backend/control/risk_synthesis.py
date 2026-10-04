"""One bounded AI synthesis over a location-redacted, current-cutoff fact catalog.

Citations, numerical copying, input binding and existing serious Dam alerts are
checked mechanically. These checks do not prove that free-form interpretation
is scientifically entailed; the report presents it as AI screening judgement.
No new rainfall/soil/dam interaction thresholds are defined here.
"""

from collections.abc import Mapping
from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
import hashlib
import json
import re

from backend.control.openai_client import AgentAPIError, strict_json
from backend.shared.context_contracts import ContextComponent
from backend.shared.dam_contracts import DamResult


LEVELS = ('unknown', 'low', 'moderate', 'high', 'critical')
_MAX_CATALOG_BYTES = 48 * 1024
_NUMBER = re.compile(r'(?<![\w.])[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?')
_PRODUCT_LABEL = re.compile(r'(?<!\w)Sentinel-1(?!\w|\.\d)', re.IGNORECASE)
_UNSUPPORTED = re.compile(
    r'\b(?:above[- ]normal|higher than normal|above[- ]average|wetter than normal|'
    r'flooding is confirmed|flooding has been confirmed|dam has failed|dam failed|'
    r'breach occurred|will flood|will fail|guaranteed|toddbrook|whaley bridge)\b|https?://|file://',
    re.IGNORECASE,
)
# Recognize bounded disclaimers about what evidence establishes. An unrelated
# "not" elsewhere in a sentence must not exempt an affirmative claim.
_EVIDENCE_NEGATION = re.compile(
    r'(?:^|[.!?;\n])\s*(?:'
    r'(?:this(?: (?:assessment|analysis|screening|evidence))?|'
    r'the (?:data|evidence|observations|assessment|analysis|findings|result)|'
    r'these (?:data|observations|findings)) '
    r'(?:does not|do not|cannot) (?:establish|show|demonstrate|prove|confirm|imply|mean) (?:that )?|'
    r'(?:there is|we have) no (?:evidence|basis) (?:that |to (?:conclude|establish|show) (?:that )?)|'
    r'it cannot be (?:concluded|established|shown|confirmed) (?:that )?'
    r')(?:the )?(?:(?:site|reservoir|dam) |rainfall (?:was|is) )?$',
    re.IGNORECASE,
)
_INSTRUCTIONS = '''Act as an environmental screening analyst for an unnamed registered reservoir or bounded study area.
Use ONLY the provided facts from the requested interval and historical cutoff. Do not identify the location,
recall any known incident, import external observations, use future information, or use tools. General physical
reasoning is allowed as an explicitly conditional interpretation, never as a new observed fact.
Synthesize the factors together: rainfall amount and coverage, soil moisture, candidate surface water, dam
integrity, hydraulic loading, maintenance and monitoring evidence, freshness, and missing inputs. These are
not independent checkboxes or fixed interaction thresholds. Existing dam screening is one provided judgement.
Missing evidence is unknown, not zero or proof of safety; it does not erase a supported concern from other evidence.
Do not infer that rainfall is above normal or increasing without a supplied comparison baseline. Candidate water
alone cannot establish new flooding. SMAP soil moisture is volumetric water content, not percent saturation;
porosity is not supplied. Interpret wetter soil only in relation to a supplied measurement or comparison,
never as an observed trend or departure from normal without a supplied baseline.
Do not assert confirmed flooding, a breach, causation, a forecast, or a
probability. Distinguish routine maintenance from structural evidence rather than assuming every maintenance
item is dangerous. Stale, sparse or partial observations constrain your interpretation; state such limits.
Choose unknown when the provided evidence cannot support classification. Never downgrade a protected high or
critical Dam alert; a possible disagreement requires separate human review, not silently lowering the result.
Return the strict JSON schema. Write a concise plain-language summary and basis; explain each material
conclusion in reasons with field_refs citing exact catalog IDs. Each reason must cite actual supplied facts.
Cite all factors that materially drive your classification and coverage/freshness limits where relevant.
Use qualitative prose where possible. If repeating a number or date, copy it exactly from cited facts; do not
invent, round, convert, extrapolate or calculate measurements, thresholds, confidence, odds or percentages.
Keep title equal to "Risk not assessable" for unknown, otherwise "Low", "Moderate", "High" or "Critical"
followed by " flood-risk screening concern". Echo evidence_digest unchanged. Do not output confidence or tools.
Focus the opening summary and basis on the available drivers and how they combine. Do not enumerate absent
products or partial-coverage details there; the report already contains technical source notes. Mention a
freshness or coverage limitation in a cited reason only when it materially limits your conclusion. If no
usable observations support classification, state that plainly and return unknown; never fill gaps with zero.
The classification is an AI screening judgement, not a calibrated flood probability or emergency instruction.'''


def _bad():
    raise ValueError('AI synthesis does not satisfy its supplied-evidence contract.')


def _encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_encoded(value)).hexdigest()


def build_synthesis_input(components: Mapping[str, ContextComponent], dam: DamResult | None, *,
                          start_time: datetime, end_time: datetime, as_of: date) -> dict:
    """Detach selected aggregates; omit site names, coordinates, raw records and prompts."""
    try:
        if (type(as_of) is not date or not 1900 <= as_of.year <= 2100
                or not isinstance(start_time, datetime) or not isinstance(end_time, datetime)
                or start_time.utcoffset() is None or end_time.utcoffset() is None
                or not timedelta(0) < end_time-start_time <= timedelta(days=7)):
            _bad()
        cutoff = datetime.combine(as_of+timedelta(days=1), time.min, tzinfo=timezone.utc)
        if not cutoff-timedelta(days=1) < end_time <= cutoff:
            _bad()
        names = ('gpm', 'smap', 'sentinel1', 'dem', 'hand')
        if not isinstance(components, Mapping) or not set(components) <= set(names):
            _bad()
        facts, has_evidence = {}, False
        def add(key, value, kind, source):
            facts[key] = {'value': value, 'kind': kind, 'source': source}
        for name in names:
            item = components.get(name)
            if item is None:
                add(name+'.availability', 'unavailable', 'availability', name)
                add(name+'.reason', 'no_validated_worker_result', 'availability', name)
                continue
            if not isinstance(item, ContextComponent):
                _bad()
            item = ContextComponent.model_validate(item.model_dump(mode='json'))
            if item.component != name:
                _bad()
            add(name+'.availability', item.availability, 'availability', name)
            add(name+'.reason', item.reason, 'availability', name)
            if item.availability == 'unavailable':
                continue
            if name in {'dem', 'hand'} or not start_time <= item.observed_start <= item.observed_end <= end_time:
                _bad()
            if name == 'sentinel1' and (item.observed_start != item.observed_end or item.observed_end == end_time):
                _bad()
            if name == 'smap' and (item.observed_start != item.metrics.timestamp_utc-timedelta(hours=1.5)
                                   or item.observed_end != item.metrics.timestamp_utc+timedelta(hours=1.5)):
                _bad()
            if name == 'gpm' and item.metrics.requested_hours != (end_time-start_time).total_seconds()/3600:
                _bad()
            add(name+'.observed_start', item.observed_start.isoformat(), 'time', name)
            add(name+'.observed_end', item.observed_end.isoformat(), 'time', name)
            for key, value in item.metrics.model_dump(mode='json').items():
                kind = 'coverage' if 'fraction' in key or key in {'covered_hours', 'requested_hours', 'granule_count'} else 'measurement'
                add(name+'.metrics.'+key, value, kind, name)
            if name in {'gpm', 'smap'}:
                has_evidence = True
        protected = 'unknown'
        if dam is None:
            add('dam.availability', 'unavailable', 'availability', 'dam')
        else:
            if not isinstance(dam, DamResult):
                _bad()
            dam = DamResult.model_validate(dam.model_dump(mode='json'))
            if dam.as_of != as_of:
                _bad()
            add('dam.availability', 'available', 'availability', 'dam')
            for key in ('risk_level', 'integrity_concern', 'hydraulic_loading'):
                add('dam.summary.'+key, getattr(dam.summary, key), 'assessment', 'dam')
            for key, value in dam.metrics.model_dump(mode='json').items():
                add('dam.metrics.'+key, value, 'coverage' if 'age_days' in key or 'count' in key else 'measurement', 'dam')
            for key, value in dam.evidence.counts.model_dump().items():
                add('dam.counts.'+key, value, 'coverage', 'dam')
            for key in ('first_observation', 'last_observation'):
                value = getattr(dam.evidence, key)
                add('dam.'+key, value.isoformat() if value else None, 'time', 'dam')
            has_evidence = has_evidence or dam.evidence.record_count > 0
            if dam.summary.risk_level in {'high', 'critical'}:
                protected = dam.summary.risk_level
        catalog = {'version': 'grounded-risk-synthesis-v1',
                   'window': {'start_time': start_time.isoformat(), 'end_time': end_time.isoformat(), 'as_of': as_of.isoformat()},
                   'facts': facts, 'protected_level': protected, 'has_assessable_evidence': has_evidence}
        if len(_encoded(catalog)) > _MAX_CATALOG_BYTES:
            _bad()
        return {**catalog, 'evidence_digest': _digest(catalog)}
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise ValueError('AI synthesis input could not be validated.') from None


def _catalog(catalog):
    try:
        if not isinstance(catalog, dict) or set(catalog) != {'version', 'window', 'facts', 'protected_level', 'has_assessable_evidence', 'evidence_digest'}:
            _bad()
        if len(_encoded(catalog)) > _MAX_CATALOG_BYTES or catalog['version'] != 'grounded-risk-synthesis-v1':
            _bad()
        if catalog['evidence_digest'] != _digest({k: v for k, v in catalog.items() if k != 'evidence_digest'}):
            _bad()
        if catalog['protected_level'] not in {'unknown', 'high', 'critical'} or type(catalog['has_assessable_evidence']) is not bool:
            _bad()
        if not isinstance(catalog['facts'], dict) or not 1 <= len(catalog['facts']) <= 128:
            _bad()
        for key, fact in catalog['facts'].items():
            if not isinstance(key, str) or not re.fullmatch(r'(gpm|smap|sentinel1|dem|hand|dam)\.[a-z_][a-z0-9_.]*', key):
                _bad()
            if (not isinstance(fact, dict) or set(fact) != {'value', 'kind', 'source'}
                    or fact['source'] != key.split('.')[0]
                    or fact['kind'] not in {'availability', 'coverage', 'measurement', 'time', 'assessment'}
                    or type(fact['value']) not in (str, int, float, bool, type(None))):
                _bad()
        return deepcopy(catalog)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ValueError('AI synthesis input could not be validated.') from None


def _numbers(value):
    if type(value) in (int, float):
        return {float(value)}
    if isinstance(value, str):
        return {float(item.group()) for item in _NUMBER.finditer(_PRODUCT_LABEL.sub('Sentinel', value))}
    return set()


def _unsupported_claim(value):
    for match in _UNSUPPORTED.finditer(value):
        phrase = match.group().lower()
        if phrase in {'toddbrook', 'whaley bridge'} or phrase.startswith(('https://', 'http://', 'file://')):
            return True
        if not _EVIDENCE_NEGATION.search(value[:match.start()]):
            return True
    return False


def _text(value, maximum, numbers):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(char) < 32 and char not in '\n\t' for char in value)
            or _unsupported_claim(value) or not _numbers(value) <= numbers):
        _bad()


def validate_synthesis(value, catalog) -> dict:
    """Recheck saved or generated output against a freshly rebuilt catalog."""
    catalog = _catalog(catalog)
    try:
        if not isinstance(value, dict) or set(value) != {'level', 'title', 'summary', 'basis', 'reasons', 'evidence_digest'}:
            _bad()
        level = value['level']
        if level not in LEVELS or value['evidence_digest'] != catalog['evidence_digest']:
            _bad()
        if LEVELS.index(level) < LEVELS.index(catalog['protected_level']):
            _bad()
        if not catalog['has_assessable_evidence'] and level != 'unknown':
            _bad()
        title = 'Risk not assessable' if level == 'unknown' else level.title()+' flood-risk screening concern'
        if value['title'] != title or not isinstance(value['reasons'], list) or not 1 <= len(value['reasons']) <= 6:
            _bad()
        all_refs = set()
        for reason in value['reasons']:
            if not isinstance(reason, dict) or set(reason) != {'text', 'field_refs'}:
                _bad()
            refs = reason['field_refs']
            if (not isinstance(refs, list) or not 1 <= len(refs) <= 16 or any(not isinstance(ref, str) for ref in refs)
                    or len(refs) != len(set(refs)) or not set(refs) <= set(catalog['facts'])):
                _bad()
            numbers = set().union(*(_numbers(catalog['facts'][ref]['value']) for ref in refs))
            _text(reason['text'], 800, numbers)
            all_refs.update(refs)
        if level != 'unknown' and not any(catalog['facts'][ref]['kind'] in {'measurement', 'assessment'}
                                          and catalog['facts'][ref]['value'] is not None for ref in all_refs):
            _bad()
        if catalog['protected_level'] != 'unknown' and 'dam.summary.risk_level' not in all_refs:
            _bad()
        numbers = set().union(*(_numbers(catalog['facts'][ref]['value']) for ref in all_refs))
        _text(value['summary'], 1200, numbers)
        _text(value['basis'], 1800, numbers)
        return deepcopy(value)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise ValueError('AI synthesis does not satisfy its supplied-evidence contract.') from None


def _schema(catalog):
    properties = {'level': {'type': 'string', 'enum': list(LEVELS)}, 'title': {'type': 'string'},
                  'summary': {'type': 'string'}, 'basis': {'type': 'string'},
                  'reasons': {'type': 'array', 'minItems': 1, 'maxItems': 6, 'items': {
                      'type': 'object', 'properties': {'text': {'type': 'string'},
                          'field_refs': {'type': 'array', 'minItems': 1, 'maxItems': 16,
                                         'items': {'type': 'string', 'enum': list(catalog['facts'])}}},
                      'required': ['text', 'field_refs'], 'additionalProperties': False}},
                  'evidence_digest': {'type': 'string', 'enum': [catalog['evidence_digest']]}}
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


async def synthesize_risk(client, catalog) -> dict:
    """Make one Responses call using the existing explicitly configured transport."""
    catalog = _catalog(catalog)
    response = await client.create(instructions=_INSTRUCTIONS,
                                   input=[{'role': 'user', 'content': _encoded(catalog).decode('utf-8')}],
                                   text={'format': {'type': 'json_schema', 'name': 'grounded_risk_synthesis',
                                                    'strict': True, 'schema': _schema(catalog)}})
    try:
        if (not isinstance(response, dict) or response.get('status') != 'completed'
                or response.get('error') is not None or response.get('incomplete_details') is not None
                or not isinstance(response.get('output'), list) or not 1 <= len(response['output']) <= 8):
            _bad()
        items = response['output']
        if any(not isinstance(item, dict) or item.get('type') not in {'message', 'reasoning'} for item in items):
            _bad()
        messages = [item for item in items if item.get('type') == 'message']
        if len(messages) != 1:
            _bad()
        message = messages[0]
        content = message.get('content')
        if (message.get('role') != 'assistant' or message.get('status', 'completed') != 'completed'
                or not isinstance(content, list) or len(content) != 1 or not isinstance(content[0], dict)
                or content[0].get('type') != 'output_text' or not isinstance(content[0].get('text'), str)):
            _bad()
        return validate_synthesis(strict_json(content[0]['text']), catalog)
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        raise AgentAPIError('invalid_response') from None
