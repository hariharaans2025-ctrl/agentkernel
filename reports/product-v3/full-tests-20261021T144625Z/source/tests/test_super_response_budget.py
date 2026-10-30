"""Offline HTTP regressions for the real Super reasoning-only truncation."""
import asyncio
import json

import httpx
import pytest

from agentkernel.concurrency.analyzer.routing import ConcurrencyRouter
from agentkernel.core.enums import InferenceTier
from agentkernel.core.models import TaskRequest
from agentkernel.providers.nebius_token_factory import DEFAULT_MODELS, NebiusTokenFactoryProvider


def request_once(monkeypatch, *, tier=InferenceTier.SUPER, phase="repair", truncated=False):
    monkeypatch.setenv("NEBIUS_API_KEY", "offline-placeholder")
    model = DEFAULT_MODELS[tier]
    calls = []
    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"data": [{"id": model}]})
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "offline-response", "model": model,
            "choices": [{"message": {"content": None if truncated else '{"edits": []}'},
                         "finish_reason": "length" if truncated else "stop"}],
            "usage": {"prompt_tokens": 1890, "completion_tokens": 4096 if truncated else 8,
                      "completion_tokens_details": {"reasoning_tokens": 4096 if truncated else 0}}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = TaskRequest(task_id="budget", task_type="concurrency_" + phase, prompt="Return edits",
                metadata={"phase": phase, "structured_output": True, "max_output_tokens": 4096})
            return await NebiusTokenFactoryProvider(client=client).generate(task, await ConcurrencyRouter(tier).route(task))
    return asyncio.run(run()), calls


def test_super_repair_requests_direct_json_without_increasing_budget(monkeypatch):
    result, calls = request_once(monkeypatch)
    assert len(calls) == 1
    assert calls[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert calls[0]["max_tokens"] == 4096
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert result.status.value == "SUCCESS"
    assert result.metadata["actual_reasoning_tokens"] == 0
    assert result.metadata["requested_enable_thinking"] is False


def test_reasoning_only_truncation_remains_rejected_and_never_retried(monkeypatch):
    result, calls = request_once(monkeypatch, truncated=True)
    assert len(calls) == 1  # Even with the provider's default retry budget.
    assert result.status.value == "FAILED"
    assert result.metadata["error_code"] == "incomplete_response"
    assert result.metadata["retryable"] is False
    assert result.metadata["actual_reasoning_tokens"] == 4096
    assert result.metadata["requested_max_output_tokens"] == 4096
    assert result.input_tokens == 1890 and result.output_tokens == 4096
    assert "total output budget" in result.metadata["error_hint"]


@pytest.mark.parametrize("tier,phase", [(InferenceTier.NANO, "repair"),
    (InferenceTier.ULTRA, "repair"), (InferenceTier.SUPER, "triage")])
def test_does_not_send_super_extension_to_other_models_or_phases(monkeypatch, tier, phase):
    _, calls = request_once(monkeypatch, tier=tier, phase=phase)
    assert "chat_template_kwargs" not in calls[0]
