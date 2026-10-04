"""Re-evaluate retained real or fixture evidence with an explicit review policy.

No network request, environmental processing, or model call is made. The input
must include both original bounded requests and a collection or dispatch report.
This command does not establish that an arbitrary input is real-world evidence;
the operator must inspect its source and the preserved processing provenance.
"""

import argparse
from pathlib import Path

from backend.control.alerts import load_policy
from backend.control.fusion import TimeWindow
from backend.control.reporting import (
    build_review_report, protect_inputs, read_evidence, write_review_report,
)
from backend.shared.settings import ROOT


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True,
                        help='Saved requests plus dispatch/combined evidence; never overwritten.')
    parser.add_argument('--rules', type=Path, required=True, help='Explicit configured policy JSON.')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/debug/fusion/result.json')
    parser.add_argument('--requested-start', help='Optional actual requested event-window start (aware ISO datetime).')
    parser.add_argument('--requested-end', help='Optional actual requested event-window end; not a claim of observation coverage.')
    args = parser.parse_args(argv)
    if (args.requested_start is None) != (args.requested_end is None):
        parser.error('Supply both requested window boundaries or neither.')
    try:
        protect_inputs(args.output, args.input, args.rules)
    except (ValueError, OSError):
        print('Refusing output that aliases an evidence or policy input.')
        return 2
    report = {'phase': '7', 'validation': 'RUNNING', 'phase_gate': 'NOT_READY',
              'scope': 'deterministic_review_of_retained_evidence', 'execution_repeated': False}
    stage = 'read_input'
    try:
        # Invalidate stale success before parsing or evaluating this attempt.
        write_review_report(args.output, report)
        evidence, digest = read_evidence(args.input)
        report['source_sha256'] = digest
        stage = 'load_policy'
        policy = load_policy(args.rules)
        stage = 'requested_window'
        window = None if args.requested_start is None else TimeWindow(
            start=args.requested_start, end=args.requested_end).model_dump(mode='json')
        stage = 'evaluate'
        report = {**build_review_report(evidence, policy, requested_window=window),
                  'source_sha256': digest}
        stage = 'write_output'
        write_review_report(args.output, report)
    except (ValueError, KeyError, TypeError, OSError, RecursionError, OverflowError):
        # Do not echo source payloads, config values, signed URLs or credentials.
        report = {'phase': '7', 'validation': 'FAIL', 'phase_gate': 'NOT_READY',
                  'scope': 'deterministic_review_of_retained_evidence', 'execution_repeated': False,
                  'failed_stage': stage, 'error': 'Evidence or policy validation failed; original inputs are unchanged.'}
        try:
            write_review_report(args.output, report)
        except OSError:
            print('Could not save failure evidence; inspect the output path before relying on an older report.')
        print(f'Phase 7: FAIL ({stage}); original worker evidence is unchanged.')
        return 1
    review = report['review']
    print(f"Phase 7 evaluation: PASS; human checkpoint: PENDING_USER. Policy: {review['policy']['purpose']}.")
    print(f"Review conditions: {review['triggered_count']} triggered, {review['not_triggered_count']} not triggered, {review['not_assessable_count']} not assessable.")
    print(f'Structured review: {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
