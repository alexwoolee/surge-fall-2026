"""Opt-in Phase 8 CLI: review saved evidence or explicitly dispatch a configured case.

Examples and the separate live API checkpoint are in docs/phase8-validation.md.
Existing backend.control.main remains available without any OpenAI dependency.
"""

import argparse
import asyncio
from pathlib import Path
from uuid import uuid4

from backend.control.agent import build_case, run_agent
from backend.control.alerts import load_policy
from backend.control.openai_client import AgentAPIError, OpenAISettings, ResponsesClient, strict_json
from backend.control.reporting import protect_inputs, read_evidence, write_review_report
from backend.shared.contracts import AnalysisTask
from backend.shared.settings import ControlSettings, ROOT


def read_case_config(path):
    with Path(path).open('rb') as stream:
        raw = stream.read(65537)
    if len(raw) > 65536:
        raise ValueError('Case configuration exceeds its limit.')
    return strict_json(raw.decode('utf-8-sig'))


def load_openai_settings(env_file=None):
    """Read an explicitly selected private two-key file, without executing it.

    No implicit dotenv loading, variable interpolation, shell or global env edits.
    A supplied file takes precedence and must supply both keys. Settings for
    workers never come from this file or enter the model context.
    """
    if env_file is None:
        return OpenAISettings.from_env()
    try:
        with Path(env_file).open('rb') as stream:
            raw = stream.read(8193)
        if len(raw) > 8192:
            raise ValueError
        settings = {}
        for line in raw.decode('utf-8-sig').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            key, separator, value = line.partition('=')
            key, value = key.strip(), value.strip()
            if separator != '=' or key not in {'OPENAI_API_KEY', 'OPENAI_MODEL'} or key in settings:
                raise ValueError
            if value[:1] in {'"', "'"}:
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError
                value = value[1:-1]
            settings[key] = value
        return OpenAISettings(api_key=settings.get('OPENAI_API_KEY', ''), model=settings.get('OPENAI_MODEL', ''))
    except (OSError, ValueError, UnicodeError):
        raise AgentAPIError('configuration_error') from None


def case_for_evidence(config, evidence):
    requests = evidence.get('requests')
    if not isinstance(requests, list) or len(requests) != 2:
        raise ValueError('The original two requests are required.')
    hydro = AnalysisTask.model_validate(requests[0])
    if hydro.analysis_type != 'hydrometeorology':
        raise ValueError('The first request must identify Hydro.')
    return build_case(config, hydro.gpm_resources, hydro.smap_resource, hydro.task_id)


class UnavailableClient:
    """A configuration failure still permits a deterministic replay fallback."""
    def __init__(self, code):
        self.code = code

    async def create(self, **_payload):
        raise AgentAPIError(self.code)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--input', type=Path, help='Retained original requests plus dispatch/combined evidence; no worker calls.')
    mode.add_argument('--execute', action='store_true', help='Explicitly authorize one new combined worker dispatch for the configured case.')
    parser.add_argument('--request', required=True, help='Natural-language request, up to 4096 UTF-8 bytes. Never include credentials.')
    parser.add_argument('--include-request', action='store_true',
                        help='Save the exact request in the local explanation as untrusted user context. '
                             'Omitted by default for privacy; review it for sensitive information before enabling or sharing.')
    parser.add_argument('--config', type=Path, default=ROOT / 'config/test_case.example.json')
    parser.add_argument('--rules', type=Path, required=True, help='Explicit deterministic demonstration policy.')
    parser.add_argument('--output', type=Path, default=ROOT / 'outputs/debug/agent/result.json')
    parser.add_argument('--env-file', type=Path, help='Optional private file containing only OPENAI_API_KEY and OPENAI_MODEL.')
    parser.add_argument('--gpm-resources', nargs='+', help='Required only with --execute; configured resource basenames.')
    parser.add_argument('--smap-resource', help='Required only with --execute; configured resource basename.')
    parser.add_argument('--task-id', help='With --execute, reuse only for an identical prior task; never restart a changed request under the same ID.')
    args = parser.parse_args(argv)
    if args.execute and (not args.gpm_resources or not args.smap_resource):
        parser.error('--execute requires --gpm-resources and --smap-resource.')
    if args.input is not None and any(value is not None for value in (args.gpm_resources, args.smap_resource, args.task_id)):
        parser.error('Retained-evidence mode uses its original resources and task ID.')
    inputs = [args.config, args.rules] + [path for path in (args.input, args.env_file) if path is not None]
    attempt_path = args.output.with_name(args.output.name + '.phase8-attempt.json')
    attempt = {'attempt_id': str(uuid4()), 'validation': 'RUNNING', 'dispatch_attempted': False}
    try:
        protect_inputs(args.output, *inputs)
        protect_inputs(attempt_path, *inputs, args.output)
        write_review_report(attempt_path, attempt)
    except (ValueError, OSError):
        print('Cannot safely record this attempt; output must be separate from all inputs and credentials.')
        return 2
    stage = 'configuration'
    last_report = None
    digest = None
    model = None
    try:
        config, policy = read_case_config(args.config), load_policy(args.rules)
        evidence = None
        if args.input is not None:
            evidence, digest = read_evidence(args.input)
            case = case_for_evidence(config, evidence)
            control = None
        else:
            case = build_case(config, args.gpm_resources, args.smap_resource, args.task_id)
            control = ControlSettings.from_env()
        try:
            settings = load_openai_settings(args.env_file)
            client, model = ResponsesClient(settings), settings.model
        except AgentAPIError as error:
            client = UnavailableClient(error.code)
        stage = 'agent_run'
        def persist(report):
            nonlocal last_report
            # The original request is included only with --include-request.
            # Raw model responses and private settings are never persisted.
            report = {**report, 'attempt_id': attempt['attempt_id'], 'source_sha256': digest,
                      'model': model, 'api': 'OpenAI Responses'}
            last_report = report
            write_review_report(args.output, report)
            attempt.update(validation=report['validation'], dispatch_attempted=report['dispatch_attempted'])
            write_review_report(attempt_path, attempt)
        report = asyncio.run(run_agent(args.request, case, policy, client, evidence=evidence,
                                       execute=args.execute, control_settings=control, persist=persist,
                                       include_request=args.include_request))
        print(f"Phase 8 agent: {report['status']}; validation: {report['validation']}.")
        if report['error']:
            print(f"Stage: {report['error']['stage']}; code: {report['error']['code']}.")
        if report['deterministic']:
            review = report['deterministic']['review']
            print(f"Deterministic review retained: {review['triggered_count']} triggered, "
                  f"{review['not_triggered_count']} not triggered, {review['not_assessable_count']} not assessable.")
        print(f'Agent evidence: {args.output}')
        return 0 if report['status'] == 'complete' else 1
    except (AgentAPIError, ValueError, KeyError, TypeError, OSError, RuntimeError, OverflowError, RecursionError):
        attempt.update(validation='FAIL', failed_stage=stage,
                       error='Attempt failed; inspect this attempt and any retained task evidence before retrying.')
        # If dispatch/evidence was already recorded, retain it and mark this
        # attempt incomplete. Never replace its results with an empty report.
        if last_report is not None:
            last_report.update(validation='FAIL', phase_gate='NOT_READY', status='degraded',
                               error={'stage': stage, 'code': 'execution_or_output_failure'})
            try:
                write_review_report(args.output, last_report)
            except OSError:
                print('Could not update output; inspect its attempt ID before relying on older evidence.')
        try:
            write_review_report(attempt_path, attempt)
        except OSError:
            print('Could not save failure status; do not rely on previous output for this attempt.')
        print(f'Phase 8 attempt failed at {stage}; no automatic retry was attempted.')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
