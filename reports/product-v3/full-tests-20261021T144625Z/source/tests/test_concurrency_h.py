import asyncio
import json
from pathlib import Path

import httpx
import pytest

from agentkernel.core.enums import InferenceTier
from agentkernel.core.models import TaskRequest
from agentkernel.concurrency.analyzer.routing import ConcurrencyRouter
from agentkernel.providers.local_rtx import LocalRTXProvider
from agentkernel.providers.nebius_token_factory import DEFAULT_MODELS, NebiusTokenFactoryProvider
from agentkernel.runtime.kernel import AgentKernel
from agentkernel.telemetry.recorder import TelemetryRecorder
from agentkernel.verification.mock_verifier import MockVerifier

MODEL = DEFAULT_MODELS[InferenceTier.NANO]


@pytest.mark.parametrize("pricing", [False, True])
def test_real_provider_catalog_usage_nullable_cost(monkeypatch: pytest.MonkeyPatch, pricing: bool) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "test-secret-not-a-real-key")
    if pricing:
        monkeypatch.setenv("AGENTKERNEL_NEBIUS_PRICING_JSON", json.dumps({MODEL: {"input_per_million": 1, "output_per_million": 2}}))
    paths = []
    def handler(request: httpx.Request) -> httpx.Response:
        paths.append(request.url.path)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        payload = json.loads(request.content)
        assert payload["model"] == MODEL
        assert "untrusted data" in payload["messages"][0]["content"]
        return httpx.Response(200, json={"model": MODEL, "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}],
                                        "usage": {"prompt_tokens": 100, "completion_tokens": 25}})
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            recorder = TelemetryRecorder()
            result = await AgentKernel(ConcurrencyRouter(InferenceTier.NANO), LocalRTXProvider(),
                                        NebiusTokenFactoryProvider(client=client), recorder,
                                        MockVerifier(default_pass=True)).execute(TaskRequest(task_id="n", task_type="test", prompt="test"))
        assert result.success
        assert result.inference.input_tokens == 100
        assert result.total_cost_usd == (0.00015 if pricing else None)
        assert recorder.execution_events[0].total_cost == result.total_cost_usd
        assert result.inference.latency_ms > 0
    asyncio.run(run())
    assert paths == ["/v1/models", "/v1/chat/completions"]


@pytest.mark.parametrize(("case", "error"), [
    ("unavailable", "configured_model_unavailable"), ("429", "rate_limited"),
    ("401", "authentication_or_access_denied"), ("timeout", "timeout"),
    ("malformed", "malformed_response"), ("bad_catalog", "malformed_catalog"),
])
def test_structured_provider_errors(monkeypatch: pytest.MonkeyPatch, case: str, error: str) -> None:
    monkeypatch.setenv("NEBIUS_API_KEY", "test-secret-not-a-real-key")
    def handler(request: httpx.Request) -> httpx.Response:
        if case == "timeout":
            raise httpx.ReadTimeout("never leak request secrets", request=request)
        if case.isdigit():
            return httpx.Response(int(case), text="test-secret-not-a-real-key")
        if case == "unavailable":
            return httpx.Response(200, json={"data": []})
        if case == "bad_catalog":
            return httpx.Response(200, json={"data": [{}]})
        if request.url.path.endswith("models"):
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        return httpx.Response(200, json={"choices": []})
    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = TaskRequest(task_id="n", task_type="test", prompt="test")
            route = await ConcurrencyRouter(InferenceTier.NANO).route(task)
            result = await NebiusTokenFactoryProvider(client=client).generate(task, route)
        assert result.metadata["error_code"] == error
        assert result.estimated_cost_usd is None
        assert "test-secret" not in result.model_dump_json()
    asyncio.run(run())


def test_no_key_no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    assert asyncio.run(NebiusTokenFactoryProvider().check_models()).error == "missing_api_key"


def test_redacted_telemetry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from agentkernel.concurrency.app import ConcurrencyJobEvent
    monkeypatch.setenv("NEBIUS_API_KEY", "secret-test-value")
    recorder = TelemetryRecorder()
    recorder.record(ConcurrencyJobEvent(task_id="x", summary={"api_key": "abc", "log": "secret-test-value", "text": "Bearer abcdefgh"}))
    text = recorder.export_jsonl(tmp_path / "events.jsonl").read_text()
    assert "secret-test-value" not in text and "abcdefgh" not in text
    assert "[REDACTED]" in text
