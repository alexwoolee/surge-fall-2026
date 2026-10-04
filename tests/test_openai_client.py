"""The optional model boundary is bounded, single-attempt, and credential safe."""

import asyncio
import json

import httpx
import pytest

import backend.control.openai_client as module
from backend.control.openai_client import AgentAPIError, OpenAISettings, ResponsesClient, strict_json


SECRET = 'test-private-api-credential'


def settings(**changes):
    return OpenAISettings(**{'api_key': SECRET, 'model': 'explicit-test-model', **changes})


def complete(**changes):
    return {'id': 'response-id', 'status': 'completed', 'output': [], **changes}


def run(handler, *, configuration=None, **payload):
    client = ResponsesClient(configuration or settings(), transport=httpx.MockTransport(handler))
    return asyncio.run(client.create(input='Bounded public evidence.', **payload))


def assert_safe(exc, code):
    assert exc.value.code == code
    assert SECRET not in str(exc.value)
    assert SECRET not in repr(exc.value)
    assert exc.value.__cause__ is None


def test_fixed_https_destination_and_store_false_single_post(monkeypatch):
    monkeypatch.setenv('OPENAI_BASE_URL', 'http://attacker.invalid')
    calls = []

    def handle(request):
        calls.append(request)
        assert str(request.url) == 'https://api.openai.com/v1/responses'
        assert request.method == 'POST'
        assert request.headers['authorization'] == 'Bearer ' + SECRET
        assert request.headers['content-type'] == 'application/json'
        value = strict_json(request.content)
        assert value == {'model': 'explicit-test-model', 'store': False, 'stream': False,
                         'max_output_tokens': 1500, 'input': 'Bounded public evidence.',
                         'instructions': 'Use only supplied evidence.'}
        return httpx.Response(200, json=complete())

    assert run(handle, instructions='Use only supplied evidence.') == complete()
    assert len(calls) == 1
    assert SECRET not in repr(settings())


def test_default_tls_verification_and_no_environment_proxy_or_redirects(monkeypatch):
    original = module.httpx.AsyncClient
    captured = []

    def client(**kwargs):
        captured.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(module.httpx, 'AsyncClient', client)
    run(lambda request: httpx.Response(200, json=complete()))
    assert captured[0]['trust_env'] is False
    assert captured[0]['follow_redirects'] is False
    assert captured[0].get('verify', True) is True


@pytest.mark.parametrize('name,value', [
    ('api_key', ''), ('api_key', SECRET + '\n'), ('api_key', 'non-ascii-é'),
    ('api_key', None), ('model', ''), ('model', '../ model'), ('model', None),
    ('timeout_seconds', float('inf')), ('timeout_seconds', float('nan')),
    ('timeout_seconds', True), ('timeout_seconds', 0), ('timeout_seconds', 121),
    ('timeout_seconds', 10 ** 1000),
    ('max_output_tokens', True), ('max_output_tokens', 0), ('max_output_tokens', 8193),
])
def test_invalid_settings_fail_without_echoing_configuration(name, value):
    with pytest.raises(AgentAPIError) as exc:
        settings(**{name: value})
    assert_safe(exc, 'configuration_error')


def test_environment_requires_explicit_model_and_key(monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('OPENAI_MODEL', raising=False)
    with pytest.raises(AgentAPIError) as exc:
        OpenAISettings.from_env()
    assert_safe(exc, 'configuration_error')
    monkeypatch.setenv('OPENAI_API_KEY', SECRET)
    with pytest.raises(AgentAPIError):
        OpenAISettings.from_env()
    monkeypatch.setenv('OPENAI_MODEL', 'operator-selected-model')
    value = OpenAISettings.from_env()
    assert value.model == 'operator-selected-model'
    assert value.api_key == SECRET and SECRET not in repr(value)


@pytest.mark.parametrize('payload', [
    {'model': 'different-model'}, {'store': True}, {'store': 0}, {'stream': True},
    {'max_output_tokens': 1501}, {'max_output_tokens': 1500.0},
])
def test_conflicting_overrides_rejected_before_network(payload):
    calls = []
    with pytest.raises(AgentAPIError) as exc:
        run(lambda request: calls.append(request), **payload)
    assert_safe(exc, 'invalid_request')
    assert calls == []


def test_identical_fixed_values_are_allowed():
    assert run(lambda request: httpx.Response(200, json=complete()),
               model='explicit-test-model', store=False, stream=False,
               max_output_tokens=1500) == complete()


@pytest.mark.parametrize('status,code', [
    (301, 'unexpected_status'), (307, 'unexpected_status'), (400, 'unexpected_status'),
    (401, 'authentication_error'), (403, 'authentication_error'), (429, 'rate_limited'),
    (500, 'api_unavailable'), (503, 'api_unavailable'),
])
def test_http_errors_do_not_retry_follow_redirect_or_echo_body(status, code):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, text=SECRET, headers={'Location': 'https://attacker.invalid'})

    with pytest.raises(AgentAPIError) as exc:
        run(handle)
    assert_safe(exc, code)
    assert len(calls) == 1


@pytest.mark.parametrize('exception,code', [
    (httpx.ConnectError, 'transport_error'), (httpx.ReadError, 'transport_error'),
    (httpx.ReadTimeout, 'timeout'), (httpx.ConnectTimeout, 'timeout'),
    (httpx.RemoteProtocolError, 'transport_error'), (OSError, 'transport_error'),
])
def test_transport_errors_are_safe_and_never_retried(exception, code):
    calls = []

    def handle(request):
        calls.append(request)
        raise exception(SECRET)

    with pytest.raises(AgentAPIError) as exc:
        run(handle)
    assert_safe(exc, code)
    assert len(calls) == 1


def test_total_timeout_covers_slow_response_chunks():
    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{'
            await asyncio.sleep(1)
            yield b'}'

    with pytest.raises(AgentAPIError) as exc:
        run(lambda request: httpx.Response(200, stream=SlowBody()),
            configuration=settings(timeout_seconds=0.01))
    assert_safe(exc, 'timeout')


def test_total_timeout_covers_header_wait():
    async def handle(request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=complete())

    with pytest.raises(AgentAPIError) as exc:
        run(handle, configuration=settings(timeout_seconds=0.01))
    assert_safe(exc, 'timeout')


@pytest.mark.parametrize('value', [
    b'not-json-private', b'[]', b'null', b'1', b'{"x":1,"x":2}',
    b'{"x":{"nested":1,"nested":2}}', b'{"x":NaN}', b'{"x":Infinity}',
    b'{"x":-Infinity}', b'{"x":1e999}', b'{"x":-1e999}', b'{"x": "\xff"}',
    b'{"x":"\\ud800"}', b'{"\\udfff":1}', None,
    '{"x":' * 33 + '0' + '}' * 33,
    '{"x":' + '[' * 2000 + '0' + ']' * 2000 + '}',
])
def test_strict_json_rejects_ambiguous_or_unbounded_content(value):
    with pytest.raises(AgentAPIError) as exc:
        strict_json(value)
    assert_safe(exc, 'invalid_json')


def test_strict_json_accepts_utf8_object_and_finite_values():
    value = {'name': 'Observé', 'x': [None, True, False, 1, -2.5, {'nested': 'valid'}]}
    for raw in [json.dumps(value), json.dumps(value, ensure_ascii=False).encode('utf-8')]:
        assert strict_json(raw) == value


def test_strict_json_rejects_oversized_input():
    with pytest.raises(AgentAPIError) as exc:
        strict_json('{"x":"' + 'x' * module.MAX_RESPONSE_BYTES + '"}')
    assert_safe(exc, 'invalid_json')


@pytest.mark.parametrize('payload,code', [
    ({'instructions': 'x' * module.MAX_REQUEST_BYTES}, 'request_too_large'),
    ({'instructions': 'é' * (module.MAX_REQUEST_BYTES // 2)}, 'request_too_large'),
    ({'temperature': float('nan')}, 'invalid_request'),
    ({'instructions': object()}, 'invalid_request'),
    ({'instructions': '\ud800'}, 'invalid_request'),
    ({'metadata': {1: 'integer key', '1': 'duplicate after encoding'}}, 'invalid_request'),
])
def test_invalid_or_oversized_request_makes_no_http_call(payload, code):
    calls = []
    with pytest.raises(AgentAPIError) as exc:
        run(lambda request: calls.append(request), **payload)
    assert_safe(exc, code)
    assert calls == []


def test_stream_size_limit_is_cumulative_without_content_length():
    class LargeBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(3):
                yield b' ' * (module.MAX_RESPONSE_BYTES // 2)

    with pytest.raises(AgentAPIError) as exc:
        run(lambda request: httpx.Response(200, stream=LargeBody()))
    assert_safe(exc, 'response_too_large')


def test_size_limit_applies_to_decompressed_response():
    import gzip

    compressed = gzip.compress(b' ' * (module.MAX_RESPONSE_BYTES + 1))
    with pytest.raises(AgentAPIError) as exc:
        run(lambda request: httpx.Response(200, content=compressed, headers={'Content-Encoding': 'gzip'}))
    assert_safe(exc, 'response_too_large')


@pytest.mark.parametrize('value,code', [
    ({}, 'invalid_response'),
    (complete(status=None), 'invalid_response'),
    (complete(status=[]), 'invalid_response'),
    (complete(status={'secret': SECRET}), 'invalid_response'),
    (complete(output={}), 'invalid_response'),
    (complete(status='incomplete', incomplete_details={'reason': SECRET}), 'incomplete_response'),
    (complete(status='in_progress'), 'incomplete_response'),
    (complete(status='queued'), 'incomplete_response'),
    (complete(status='failed', error={'message': SECRET}), 'api_error'),
    (complete(status='cancelled'), 'api_error'),
    (complete(error={'message': SECRET}), 'api_error'),
    (complete(output=[{'type': 'message', 'content': [{'type': 'refusal', 'refusal': SECRET}]}]), 'refusal'),
])
def test_refusal_and_incomplete_or_malformed_response_are_not_success(value, code):
    with pytest.raises(AgentAPIError) as exc:
        run(lambda request: httpx.Response(200, json=value))
    assert_safe(exc, code)


def test_non_json_and_duplicate_response_fields_are_rejected():
    for raw in [SECRET, '{"status":"completed","status":"failed","output":[]}']:
        with pytest.raises(AgentAPIError) as exc:
            run(lambda request: httpx.Response(200, text=raw))
        assert_safe(exc, 'invalid_json')


def test_unknown_error_code_cannot_become_a_secret_message():
    error = AgentAPIError(SECRET)
    assert error.code == 'api_error'
    assert SECRET not in str(error) and SECRET not in repr(error)


def test_caller_cancellation_is_not_swallowed():
    async def handle(request):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        run(handle)


def test_request_rejects_cycles_and_excessive_nesting_without_network():
    recursive = []
    recursive.append(recursive)
    deep = {}
    for _ in range(module.MAX_JSON_DEPTH + 1):
        deep = {'child': deep}
    for value in [recursive, deep]:
        calls = []
        with pytest.raises(AgentAPIError) as exc:
            run(lambda request: calls.append(request), metadata=value)
        assert_safe(exc, 'invalid_request')
        assert calls == []


@pytest.mark.parametrize('failure', ['size', 'timeout', 'invalid_json'])
def test_response_stream_is_closed_after_failure(failure):
    class Body(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self):
            if failure == 'size':
                yield b' ' * (module.MAX_RESPONSE_BYTES + 1)
            elif failure == 'timeout':
                await asyncio.sleep(1)
            else:
                yield b'not-json'

        async def aclose(self):
            self.closed = True

    body = Body()
    with pytest.raises(AgentAPIError):
        run(lambda request: httpx.Response(200, stream=body),
            configuration=settings(timeout_seconds=0.01))
    assert body.closed
