"""Control entry point and honest remote gate checks, without external services."""

import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from backend.control import main as control_cli
from backend.control.main import make_tasks, save_json
from backend.shared.settings import ControlSettings, ROOT, WorkerEndpoint
from scripts.validate import validate_remote_workers as checkpoint


def test_bounded_tasks_share_new_id_and_reconcile_explicit_id():
    config = json.loads((ROOT / 'config/test_case.example.json').read_text())
    first = make_tasks(config, checkpoint.GPM_RESOURCES, checkpoint.SMAP_RESOURCE)
    second = make_tasks(config, checkpoint.GPM_RESOURCES, checkpoint.SMAP_RESOURCE)
    assert first[0].task_id == first[1].task_id != second[0].task_id
    assert first[0].bbox == first[1].bbox
    assert make_tasks(config, checkpoint.GPM_RESOURCES, checkpoint.SMAP_RESOURCE, first[0].task_id) == first
    with pytest.raises(ValueError):
        make_tasks(config, checkpoint.GPM_RESOURCES, checkpoint.SMAP_RESOURCE, '')
    with pytest.raises(ValueError):
        make_tasks({**config, 'bbox': [-122, 40, -121, 44]}, checkpoint.GPM_RESOURCES, checkpoint.SMAP_RESOURCE)


def test_reports_replace_atomically_without_partial_json(tmp_path):
    output = tmp_path / 'nested' / 'result.json'
    save_json(output, {'task_id': 'retained', 'validation': 'RUNNING'})
    with pytest.raises(ValueError):
        save_json(output, {'invalid': float('nan')})
    assert json.loads(output.read_text()) == {'task_id': 'retained', 'validation': 'RUNNING'}
    save_json(output, {'validation': 'PASS'})
    assert json.loads(output.read_text()) == {'validation': 'PASS'}
    assert not output.with_name('result.json.tmp').exists()


def topology_run(hosts=('hydro-laptop', 'flood-laptop'), instances=('one', 'two')):
    records = [SimpleNamespace(task_status=SimpleNamespace(execution_host=host, process_instance_id=instance))
               for host, instance in zip(hosts, instances)]
    return SimpleNamespace(hydro=records[0], flood=records[1])


def settings(hydro='http://100.100.1.2:8002', flood='http://100.100.1.3:8003'):
    return ControlSettings(WorkerEndpoint(hydro, 'hydro-worker', 'test-token'),
                           WorkerEndpoint(flood, 'flood-worker', 'test-token'))


def test_remote_gate_requires_operator_and_actual_distinct_reported_hosts():
    check = checkpoint.topology_checks(topology_run(), settings(), 'control-laptop', True)
    assert all(check.values())
    assert not all(checkpoint.topology_checks(topology_run(), settings(), 'control-laptop', False).values())
    assert not all(checkpoint.topology_checks(topology_run(('control-laptop', 'flood-laptop')), settings(), 'control-laptop', True).values())
    assert not all(checkpoint.topology_checks(topology_run(instances=('same', 'same')), settings(), 'control-laptop', True).values())
    assert not all(checkpoint.topology_checks(topology_run((None, None)), settings(), 'control-laptop', True).values())


@pytest.mark.parametrize('url', ['http://127.0.0.1:8002', 'http://localhost:8002',
                                 'http://[::1]:8002', 'http://[::ffff:127.0.0.1]:8002',
                                 'http://0.0.0.0:8002'])
def test_local_endpoint_never_passes_remote_gate(url):
    assert not all(checkpoint.topology_checks(topology_run(), settings(hydro=url), 'control-laptop', True).values())


def test_auth_failure_writes_safe_failed_report_before_submission(monkeypatch, tmp_path):
    async def reject(*args):
        raise httpx.ConnectError('unsafe credentials must not appear')
    monkeypatch.setattr(checkpoint, '_authentication_check', reject)
    config = json.loads((ROOT / 'config/test_case.example.json').read_text())
    tasks = make_tasks(config, checkpoint.GPM_RESOURCES, checkpoint.SMAP_RESOURCE)
    output = tmp_path / 'result.json'
    code = asyncio.run(checkpoint.validate(settings(), tasks, local_check=False, confirmed=True, output=output))
    payload = output.read_text()
    assert code == 1 and 'unsafe credentials' not in payload and 'test-token' not in payload
    assert json.loads(payload)['validation'] == 'FAIL'
    assert json.loads(payload)['task_id'] == tasks[0].task_id


def test_local_check_cannot_accept_physical_confirmation():
    with pytest.raises(SystemExit):
        checkpoint.main(['--local-check', '--confirm-separate-laptops'])


def test_final_control_report_keeps_exact_requests_for_ambiguous_retry(monkeypatch, tmp_path):
    class Run:
        hydro = SimpleNamespace(worker_id='hydro-worker', outcome='timed_out', error=None)
        flood = SimpleNamespace(worker_id='flood-worker', outcome='rejected', error=None)

        def model_dump(self, **kwargs):
            return {'task_id': 'recoverable-id', 'acceptance_unknown': True}

    async def dispatch(hydro, flood, configured):
        assert hydro.task_id == flood.task_id == 'recoverable-id'
        return Run()

    monkeypatch.setattr(control_cli, 'run_analysis', dispatch)
    monkeypatch.setattr(ControlSettings, 'from_env', lambda: settings())
    output = tmp_path / 'control.json'
    assert control_cli.main(['--output', str(output), '--task-id', 'recoverable-id',
                             '--gpm-resources', *checkpoint.GPM_RESOURCES,
                             '--smap-resource', checkpoint.SMAP_RESOURCE]) == 1
    report = json.loads(output.read_text())
    assert report['dispatch']['acceptance_unknown']
    assert report['requests'][0]['gpm_resources'] == checkpoint.GPM_RESOURCES
    assert report['requests'][1]['start_time'] == '2021-11-13T00:00:00Z'
    assert {task['task_id'] for task in report['requests']} == {'recoverable-id'}
