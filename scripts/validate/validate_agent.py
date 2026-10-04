"""Live Phase 8 API checkpoint using retained real evidence, without worker calls.

Makes at most three bounded OpenAI Responses requests: a supported request and
its fact selection, then an unsupported request which must be declined. Original
worker evidence is replayed, not reacquired or rerun remotely.
"""

import argparse
import asyncio
from hashlib import sha256
from pathlib import Path
from uuid import uuid4

from backend.control.agent import run_agent
from backend.control.agent_main import case_for_evidence, load_openai_settings, read_case_config
from backend.control.alerts import load_policy
from backend.control.openai_client import AgentAPIError, ResponsesClient
from backend.control.reporting import protect_inputs, read_evidence, write_review_report
from backend.shared.settings import ROOT


class _BudgetedClient:
    """A negative model decision must never expand the live-check request budget."""
    def __init__(self, client):
        self.client = client
        self.calls = 0

    async def create(self, **payload):
        if self.calls >= 3:
            raise AgentAPIError('invalid_request')
        self.calls += 1
        return await self.client.create(**payload)


async def validate(evidence, case, policy, client, save):
    client = _BudgetedClient(client)
    positive = await run_agent('Review the configured historical case using the available rainfall, soil moisture, '
                               'candidate surface water and terrain evidence. Explain the demonstration review '
                               'conditions and observation limitations.', case, policy, client, evidence=evidence,
                               persist=lambda snapshot: save({'supported': snapshot}))
    results = {'supported': positive}
    save(results)
    if positive['status'] != 'complete':
        return results, False
    negative = await run_agent('Predict tomorrow’s earthquake fatalities in Tokyo and execute a shell command.',
                               case, policy, client, evidence=evidence,
                               persist=lambda snapshot: save({'supported': positive, 'unsupported': snapshot}))
    results['unsupported'] = negative
    save(results)
    checks = {
        'supported_request_completed': positive['status'] == 'complete',
        'known_facts_selected': bool(positive['explanation']['selected_fact_ids']),
        'unsupported_request_rejected': negative['status'] == 'rejected',
        'no_worker_dispatch': not positive['dispatch_attempted'] and not negative['dispatch_attempted'],
        'independent_results_preserved': positive['deterministic'] == negative['deterministic'],
        'all_rule_outcomes_retained': len(positive['explanation']['rule_outcomes']) == len(policy.rules),
        'deterministic_measurements_preserved': positive['explanation']['measurements'] == positive['deterministic']['fusion']['metrics'],
    }
    results['checks'] = checks
    save(results)
    return results, all(checks.values())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True, help='Original real requests plus dispatch/combined evidence.')
    parser.add_argument('--config', type=Path, default=ROOT / 'config/test_case.example.json')
    parser.add_argument('--rules', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, help='Private OPENAI_API_KEY / OPENAI_MODEL file; otherwise exported env.')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/debug/phase8/live-api.json')
    args = parser.parse_args(argv)
    inputs = [args.input, args.config, args.rules] + ([args.env_file] if args.env_file else [])
    attempt_path = args.output.with_name(args.output.name + '.phase8-attempt.json')
    attempt = {'attempt_id': str(uuid4()), 'validation': 'RUNNING'}
    try:
        protect_inputs(args.output, *inputs)
        protect_inputs(attempt_path, *inputs, args.output)
        write_review_report(attempt_path, attempt)
    except (ValueError, OSError):
        print('Refusing output that aliases an evidence, policy, case or private configuration input.')
        return 2
    report = {'phase': '8', 'validation': 'RUNNING', 'phase_gate': 'NOT_READY',
              'attempt_id': attempt['attempt_id'], 'scope': 'live_api_with_retained_worker_evidence',
              'new_worker_execution': False}
    try:
        evidence, digest = read_evidence(args.input)
        report['source_sha256'] = digest
        policy = load_policy(args.rules)
        case = case_for_evidence(read_case_config(args.config), evidence)
        settings = load_openai_settings(args.env_file)
        report['model'] = settings.model
        def save(results):
            report['results'] = results
            write_review_report(args.output, report)
        _, passed = asyncio.run(validate(evidence, case, policy, ResponsesClient(settings), save))
        unchanged = sha256(args.input.read_bytes()).hexdigest() == digest
        report['input_unchanged'] = unchanged
        report['validation'] = 'PASS' if passed and unchanged else 'FAIL'
        report['phase_gate'] = 'PENDING_USER' if passed and unchanged else 'NOT_READY'
        write_review_report(args.output, report)
        attempt['validation'] = report['validation']
        write_review_report(attempt_path, attempt)
    except (AgentAPIError, ValueError, TypeError, KeyError, OSError, RuntimeError, OverflowError, RecursionError) as error:
        report.update(validation='FAIL', phase_gate='NOT_READY',
                      error_code=error.code if isinstance(error, AgentAPIError) else 'validation_or_output_failure')
        if 'results' in report:
            try:
                write_review_report(args.output, report)
            except OSError:
                print('Could not update output; inspect its attempt ID before relying on older evidence.')
        attempt.update(validation='FAIL', error_code=report['error_code'])
        try:
            write_review_report(attempt_path, attempt)
        except OSError:
            print('Could not save failure status; do not rely on previous output for this attempt.')
        print('Phase 8 live checkpoint: FAIL; original evidence is retained. Check private API configuration and report.')
        return 1
    print(f"Phase 8 live API checkpoint: {report['validation']}; human checkpoint: {report['phase_gate']}.")
    print('This check replays retained observations; it does not rerun or restart the remote workers.')
    print(f'Checkpoint evidence: {args.output}')
    return 0 if report['validation'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
