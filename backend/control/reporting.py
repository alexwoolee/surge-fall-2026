"""Phase 7 structured review artifacts, without HTML, HTTP or model calls.

The original worker evidence remains in the fusion object. HTML presentation
and frontend integration belong to the later, separately accepted phase.
"""

import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

from backend.control.alerts import evaluate_review_conditions
from backend.control.fusion import fuse_analysis
from backend.control.state import DispatchRun
from backend.shared.contracts import CombinedAnalysis


MAX_REPORT_BYTES = 16 * 1024 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON object keys are not allowed.')
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError('Nonfinite JSON numbers are not allowed.')


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Nonfinite JSON numbers are not allowed.')
    return number


def read_evidence(path):
    """Read bounded, unambiguous JSON and identify the exact input bytes."""
    with Path(path).open('rb') as source:
        raw = source.read(MAX_REPORT_BYTES + 1)
    if len(raw) > MAX_REPORT_BYTES:
        raise ValueError('Evidence report exceeds the input size limit.')
    value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object,
                       parse_constant=_invalid_constant, parse_float=_finite_float)
    if not isinstance(value, dict):
        raise ValueError('Evidence must be a JSON object.')
    return value, hashlib.sha256(raw).hexdigest()


def build_review_report(evidence, policy, *, requested_window=None):
    """Re-evaluate saved results, preserving their original request bindings.

    Accept the saved Control/Phase 5/Phase 6 envelope, or a local acquisition
    envelope containing the same two requests and CombinedAnalysis. Unknown
    input metadata is not copied into a new artifact (it may contain secrets).
    PASS describes deterministic evaluation, not environmental completeness or
    a fresh distributed run. Missing evidence is explicitly retained by fusion.
    """
    if not isinstance(evidence, dict):
        raise ValueError('An evidence envelope is required.')
    requests = evidence.get('requests')
    if not isinstance(requests, list) or len(requests) != 2:
        raise ValueError('The two original bounded worker requests are required.')
    dispatch = None
    if 'dispatch' in evidence:
        raw = evidence['dispatch']
        dispatch = DispatchRun.model_validate(raw.model_dump(mode='json')
                                             if isinstance(raw, DispatchRun) else raw)
        combined = dispatch.combined
        if 'combined' in evidence:
            other = evidence['combined']
            other = CombinedAnalysis.model_validate(other.model_dump(mode='json')
                                                    if isinstance(other, CombinedAnalysis) else other)
            if other != combined:
                raise ValueError('Collection and dispatch evidence disagree.')
    elif 'combined' in evidence:
        combined = evidence['combined']
    else:
        raise ValueError('Validated collected worker evidence is required.')
    recorded_window = evidence.get('requested_window')
    if requested_window is not None and recorded_window is not None:
        from backend.control.fusion import TimeWindow
        if TimeWindow.model_validate(requested_window) != TimeWindow.model_validate(recorded_window):
            raise ValueError('Requested window conflicts with the saved investigation context.')
    fused = fuse_analysis(*requests, combined,
                          requested_window=requested_window if requested_window is not None else recorded_window,
                          dispatch=dispatch)
    review = evaluate_review_conditions(fused, policy)
    return {
        'phase': '7', 'validation': 'PASS', 'phase_gate': 'PENDING_USER',
        'scope': 'deterministic_review_of_retained_evidence',
        'execution_repeated': False,
        'validation_meaning': 'Evidence binding and deterministic review completed; this is not a severity classification or a new remote execution proof.',
        'fusion': fused.model_dump(mode='json'),
        'review': review.model_dump(mode='json'),
    }


def protect_inputs(output, *inputs):
    """Never replace an input, including a symlink or hard-link alias."""
    output = Path(output)
    for source in map(Path, inputs):
        if output.resolve() == source.resolve():
            raise ValueError('Output must be separate from the evidence and policy inputs.')
        if output.exists() and source.exists() and output.samefile(source):
            raise ValueError('Output aliases an input file.')


def write_review_report(path, value):
    """Write strict JSON atomically using a unique, closed temporary file."""
    serialized = json.dumps(value, indent=2, allow_nan=False) + '\n'
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n',
                                         dir=path.parent, prefix='.phase7-', suffix='.tmp',
                                         delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(serialized)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
