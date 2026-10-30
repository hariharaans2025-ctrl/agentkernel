import asyncio
import json
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from agentkernel.core.enums import ExecutionStatus
from agentkernel.core.models import TaskRequest
from agentkernel.local.base import LocalBackendError
from agentkernel.local.ollama_backend import OllamaBackend
from agentkernel.providers.local_rtx import LocalRTXProvider, SYSTEM_PROMPT
from agentkernel.providers.mock_nebius import MockNebiusProvider
from agentkernel.router.rule_router import RuleBasedRouter
from agentkernel.runtime.kernel import AgentKernel
from agentkernel.telemetry.events import TelemetryEvent
from agentkernel.telemetry.recorder import TelemetryRecorder
from agentkernel.verification.mock_verifier import MockVerifier


def generation(**overrides: Any) -> dict[str, Any]:
    return {"model": "test-model:latest", "response": "Check the missing dependency.",
            "done": True, "prompt_eval_count": 42, "eval_count": 9, **overrides}


def task() -> TaskRequest:
    return TaskRequest(task_id="t", task_type="ci", prompt="ModuleNotFoundError: requests")


def test_default_mock_never_calls_backend() -> None:
    backend = AsyncMock()
    async def run() -> None:
        route = await RuleBasedRouter().route(task())
        result = await LocalRTXProvider(backend).generate(task(), route)
        assert result.status == ExecutionStatus.MOCK
        assert result.latency_ms == 15
        assert result.metadata["execution_mode"] == "mock"
    asyncio.run(run())
    backend.generate.assert_not_awaited()


def test_success_real_metrics_and_request(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AGENTKERNEL_LOCAL_MODEL", "test-model")
    ticks = iter([10.0, 10.842])
    monkeypatch.setattr("agentkernel.local.ollama_backend.perf_counter", lambda: next(ticks))
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "http://localhost:11434/api/generate"
        assert request.method == "POST"
        assert json.loads(request.content) == {
            "model": "test-model", "prompt": task().prompt, "system": SYSTEM_PROMPT, "stream": False,
        }
        return httpx.Response(200, json=generation())
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            response = await OllamaBackend(client=client).generate(task().prompt, SYSTEM_PROMPT)
        assert response.latency_ms == pytest.approx(842)
        assert (response.input_tokens, response.output_tokens) == (42, 9)
        assert response.model == "test-model:latest"
    asyncio.run(run())


@pytest.mark.parametrize("missing", [False, True])
def test_real_telemetry_and_optional_tokens(monkeypatch: pytest.MonkeyPatch, missing: bool) -> None:
    monkeypatch.setenv("AGENTKERNEL_LOCAL_MODEL", "test-model")
    monkeypatch.setenv("AGENTKERNEL_LOCAL_MOCK", "false")
    data = generation()
    if missing:
        del data["prompt_eval_count"]
        del data["eval_count"]
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))) as client:
            recorder = TelemetryRecorder()
            local = LocalRTXProvider(OllamaBackend(client=client))
            result = await AgentKernel(RuleBasedRouter(), local, MockNebiusProvider(), recorder,
                                       MockVerifier(default_pass=True)).execute(task())
        inference = result.inference
        assert inference.status == ExecutionStatus.SUCCESS
        assert inference.estimated_cost_usd == 0
        assert inference.latency_ms > 0
        assert (inference.input_tokens, inference.output_tokens) == ((0, 0) if missing else (42, 9))
        assert inference.metadata["input_tokens_available"] is not missing
        assert inference.metadata["output_tokens_available"] is not missing
        assert len(recorder.events) == 1
        event = recorder.events[0]
        assert event.metadata == inference.metadata
        assert event.metadata["execution_mode"] == "real"
        assert event.metadata["location"] == event.metadata["execution_location"] == "local"
        assert event.metadata["backend"] == "ollama"
        assert event.metadata["model"] == "test-model:latest"
        assert event.latency_ms == inference.latency_ms
        assert event.input_tokens == inference.input_tokens
        assert event.output_tokens == inference.output_tokens
        assert TelemetryEvent.model_validate_json(event.model_dump_json()) == event
        old_record = event.model_dump()
        del old_record["metadata"]
        assert TelemetryEvent.model_validate(old_record).metadata == {}
    asyncio.run(run())


@pytest.mark.parametrize(("error_class", "message"), [
    (httpx.ConnectError, "Could not connect to http://localhost:11434"),
    (httpx.ReadTimeout, "Ollama timed out"),
])
def test_network_errors(monkeypatch: pytest.MonkeyPatch, error_class: type[httpx.RequestError], message: str) -> None:
    monkeypatch.setenv("AGENTKERNEL_LOCAL_MODEL", "test-model")
    def handler(request: httpx.Request) -> httpx.Response:
        raise error_class("test failure", request=request)
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            backend = OllamaBackend(client=client)
            with pytest.raises(LocalBackendError, match=message):
                await backend.generate("hello")
            health = await backend.health_check()
            assert not health.available
            assert message in (health.error or "")
            local = LocalRTXProvider(backend, mock=False)
            recorder = TelemetryRecorder()
            result = await AgentKernel(RuleBasedRouter(), local, MockNebiusProvider(), recorder, max_attempts=1).execute(task())
            assert result.inference.status == ExecutionStatus.FAILED
            assert message in result.inference.output_text
            assert recorder.events[0].metadata["execution_mode"] == "real"
    asyncio.run(run())


@pytest.mark.parametrize("data", [
    [], {}, {"error": "problem"}, generation(done=False), generation(response=""),
    generation(response="  "), generation(eval_count=-1), generation(eval_count="9"),
    generation(prompt_eval_count=True), generation(model=None),
])
def test_malformed_generation(monkeypatch: pytest.MonkeyPatch, data: Any) -> None:
    monkeypatch.setenv("AGENTKERNEL_LOCAL_MODEL", "test-model")
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))) as client:
            with pytest.raises(LocalBackendError):
                await OllamaBackend(client=client).generate("hello")
    asyncio.run(run())


@pytest.mark.parametrize(("status", "body", "message"), [
    (200, "not json", "malformed JSON"), (404, "missing", "ollama list"), (500, "failed", "HTTP 500"),
])
def test_http_and_json_errors(monkeypatch: pytest.MonkeyPatch, status: int, body: str, message: str) -> None:
    monkeypatch.setenv("AGENTKERNEL_LOCAL_MODEL", "test-model")
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status, text=body))) as client:
            with pytest.raises(LocalBackendError, match=message):
                await OllamaBackend(client=client).generate("hello")
    asyncio.run(run())


@pytest.mark.parametrize(("data", "available", "message"), [
    ({"models": [{"name": "test-model:latest"}]}, True, None),
    ({"models": []}, False, "not installed"),
    ({"models": "wrong"}, False, "malformed"),
    ({"models": [{}]}, False, "malformed"),
])
def test_health_model_availability(monkeypatch: pytest.MonkeyPatch, data: dict[str, Any], available: bool, message: str | None) -> None:
    monkeypatch.setenv("AGENTKERNEL_LOCAL_MODEL", "test-model")
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json=data)
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            health = await OllamaBackend(client=client).health_check()
        assert health.available is available
        if message:
            assert message in (health.error or "")
    asyncio.run(run())


def test_missing_model_configuration() -> None:
    async def run() -> None:
        with pytest.raises(LocalBackendError, match="AGENTKERNEL_LOCAL_MODEL"):
            await OllamaBackend().generate("hello")
        route = await RuleBasedRouter().route(task())
        result = await LocalRTXProvider(mock=False).generate(task(), route)
        assert result.status == ExecutionStatus.FAILED
        assert "AGENTKERNEL_LOCAL_MODEL" in result.output_text
    asyncio.run(run())


@pytest.mark.parametrize(("variable", "value"), [
    ("AGENTKERNEL_LOCAL_BACKEND", "unsupported"),
    ("AGENTKERNEL_OLLAMA_URL", "https://example.com"),
    ("AGENTKERNEL_LOCAL_TIMEOUT_SECONDS", "nan"),
    ("AGENTKERNEL_LOCAL_TIMEOUT_SECONDS", "0"),
    ("AGENTKERNEL_LOCAL_MODEL", "test-cloud"),
    ("AGENTKERNEL_LOCAL_MOCK", "typo"),
])
def test_invalid_configuration_fails_without_network(monkeypatch: pytest.MonkeyPatch, variable: str, value: str) -> None:
    monkeypatch.setenv("AGENTKERNEL_LOCAL_MOCK", "false")
    monkeypatch.setenv(variable, value)
    async def run() -> None:
        result = await LocalRTXProvider().generate(task(), await RuleBasedRouter().route(task()))
        assert result.status == ExecutionStatus.FAILED
    asyncio.run(run())
