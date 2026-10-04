"""Bounded, single-attempt Responses requests with redacted failure messages.

This transport only contacts the fixed OpenAI endpoint. Callers own the bounded
tool and output schemas, and must validate returned arguments before using them.
"""

import asyncio
from dataclasses import dataclass, field
import json
import math
import os
import re

import httpx


RESPONSES_URL = 'https://api.openai.com/v1/responses'
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
MAX_JSON_DEPTH = 32

_ERROR_MESSAGES = {
    'configuration_error': 'OpenAI configuration is missing or invalid.',
    'invalid_request': 'The bounded OpenAI request is invalid.',
    'request_too_large': 'The OpenAI request exceeds its size limit.',
    'response_too_large': 'The OpenAI response exceeds its size limit.',
    'invalid_json': 'The OpenAI JSON content is malformed or outside its limits.',
    'invalid_response': 'The OpenAI response does not have the expected structure.',
    'authentication_error': 'OpenAI authentication or access was rejected.',
    'rate_limited': 'OpenAI request capacity is currently unavailable.',
    'api_unavailable': 'The OpenAI service is currently unavailable.',
    'unexpected_status': 'OpenAI returned an unexpected HTTP status.',
    'timeout': 'The OpenAI request exceeded its time limit.',
    'transport_error': 'The OpenAI request could not be completed.',
    'refusal': 'The OpenAI response declined the request.',
    'incomplete_response': 'The OpenAI response did not complete.',
    'api_error': 'The OpenAI request failed.',
}


class AgentAPIError(Exception):
    """Safe to display or persist; no remote body or exception text is retained."""

    def __init__(self, code):
        self.code = code if isinstance(code, str) and code in _ERROR_MESSAGES else 'api_error'
        super().__init__(_ERROR_MESSAGES[self.code])


@dataclass(frozen=True)
class OpenAISettings:
    api_key: str = field(repr=False)
    model: str
    timeout_seconds: float = 30.0
    max_output_tokens: int = 1500

    def __post_init__(self):
        if (not isinstance(self.api_key, str) or not 1 <= len(self.api_key) <= 4096
                or any(not 33 <= ord(character) <= 126 for character in self.api_key)):
            raise AgentAPIError('configuration_error')
        if (not isinstance(self.model, str)
                or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}', self.model) is None):
            raise AgentAPIError('configuration_error')
        if (isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float))
                or not 0.01 <= self.timeout_seconds <= 120 or not math.isfinite(self.timeout_seconds)):
            raise AgentAPIError('configuration_error')
        if (isinstance(self.max_output_tokens, bool) or not isinstance(self.max_output_tokens, int)
                or not 1 <= self.max_output_tokens <= 8192):
            raise AgentAPIError('configuration_error')

    @classmethod
    def from_env(cls):
        """Require explicit credentials and model; never read credential files."""
        return cls(api_key=os.environ.get('OPENAI_API_KEY', ''),
                   model=os.environ.get('OPENAI_MODEL', ''))


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


def _finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError
    return number


def _reject_constant(_value):
    raise ValueError


def strict_json(text_or_bytes) -> dict:
    """Decode a bounded UTF-8 JSON object without ambiguous keys or numbers."""
    try:
        if isinstance(text_or_bytes, bytes):
            if len(text_or_bytes) > MAX_RESPONSE_BYTES:
                raise ValueError
            raw = text_or_bytes.decode('utf-8')
        elif isinstance(text_or_bytes, str):
            if len(text_or_bytes.encode('utf-8')) > MAX_RESPONSE_BYTES:
                raise ValueError
            raw = text_or_bytes
        else:
            raise ValueError
        value = json.loads(raw, object_pairs_hook=_unique_object,
                           parse_float=_finite_float, parse_constant=_reject_constant)
        if not isinstance(value, dict):
            raise ValueError
        pending = [(value, 1)]
        while pending:
            item, depth = pending.pop()
            if depth > MAX_JSON_DEPTH:
                raise ValueError
            if isinstance(item, dict):
                for key in item:
                    key.encode('utf-8')
                pending.extend((child, depth + 1) for child in item.values())
            elif isinstance(item, list):
                pending.extend((child, depth + 1) for child in item)
            elif isinstance(item, str):
                item.encode('utf-8')
        return value
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise AgentAPIError('invalid_json') from None


def _request_body(settings, payload):
    fixed = {'model': settings.model, 'store': False, 'stream': False,
             'max_output_tokens': settings.max_output_tokens}
    for key, value in fixed.items():
        if key in payload and (type(payload[key]) is not type(value) or payload[key] != value):
            raise AgentAPIError('invalid_request')
    try:
        encoded = bytearray()
        encoder = json.JSONEncoder(ensure_ascii=False, allow_nan=False, separators=(',', ':'))
        for part in encoder.iterencode({**payload, **fixed}):
            encoded.extend(part.encode('utf-8'))
            if len(encoded) > MAX_REQUEST_BYTES:
                raise AgentAPIError('request_too_large')
        # Match the strict response parser's finite-number and nesting contract.
        strict_json(bytes(encoded))
        return bytes(encoded)
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise AgentAPIError('invalid_request') from None
    except AgentAPIError as exc:
        if exc.code == 'invalid_json':
            raise AgentAPIError('invalid_request') from None
        raise


def _validate_response(value):
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            if item.get('type') == 'refusal':
                raise AgentAPIError('refusal')
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    status = value.get('status')
    if not isinstance(status, str):
        raise AgentAPIError('invalid_response')
    if value.get('error') is not None or status in {'failed', 'cancelled'}:
        raise AgentAPIError('api_error')
    if status in {'incomplete', 'queued', 'in_progress'}:
        raise AgentAPIError('incomplete_response')
    if status != 'completed' or not isinstance(value.get('output'), list):
        raise AgentAPIError('invalid_response')
    return value


class ResponsesClient:
    """One bounded HTTPS POST per create call, without retry or redirection."""

    def __init__(self, settings: OpenAISettings, *, transport=None):
        if not isinstance(settings, OpenAISettings):
            raise AgentAPIError('configuration_error')
        self.settings = settings
        self._transport = transport

    async def create(self, **payload) -> dict:
        body = _request_body(self.settings, payload)
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                async with httpx.AsyncClient(
                    transport=self._transport, timeout=self.settings.timeout_seconds,
                    trust_env=False, follow_redirects=False,
                ) as client:
                    async with client.stream(
                        'POST', RESPONSES_URL, content=body,
                        headers={'Authorization': 'Bearer ' + self.settings.api_key,
                                 'Content-Type': 'application/json', 'Accept': 'application/json'},
                    ) as response:
                        if response.status_code in {401, 403}:
                            raise AgentAPIError('authentication_error')
                        if response.status_code == 429:
                            raise AgentAPIError('rate_limited')
                        if response.status_code >= 500:
                            raise AgentAPIError('api_unavailable')
                        if response.status_code != 200:
                            raise AgentAPIError('unexpected_status')
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(data) + len(chunk) > MAX_RESPONSE_BYTES:
                                raise AgentAPIError('response_too_large')
                            data.extend(chunk)
                        return _validate_response(strict_json(bytes(data)))
        except (TimeoutError, httpx.TimeoutException):
            raise AgentAPIError('timeout') from None
        except (httpx.HTTPError, OSError):
            raise AgentAPIError('transport_error') from None
