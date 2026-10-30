import asyncio
import difflib
import json
import sys
from pathlib import Path

import httpx
import pytest

from agentkernel.config import load_env_file
from agentkernel.core.enums import InferenceTier
from agentkernel.core.models import TaskRequest
from agentkernel.concurrency.analyzer.routing import ConcurrencyRouter
from agentkernel.concurrency.app import ConcurrencyBugHunter, ConcurrencyPolicy
from agentkernel.concurrency.models import ConcurrencyTask, VerificationConfig
from agentkernel.concurrency.mock_inference import mock_concurrency_response
from agentkernel.concurrency.smoke import RepairContractVerifier
from agentkernel.observability import span, trace
from agentkernel.observability.langsmith_observer import LangSmithObserver
from agentkernel.providers.local_rtx import LocalRTXProvider
from agentkernel.providers.mock_nebius import MockNebiusProvider
from agentkernel.providers.nebius_token_factory import DEFAULT_MODELS, NebiusTokenFactoryProvider
from agentkernel.runtime.kernel import AgentKernel
from agentkernel.telemetry.recorder import TelemetryRecorder

MODEL = DEFAULT_MODELS[InferenceTier.NANO]


@pytest.mark.parametrize("finish,code", [("length", "incomplete_response"), ("stop", "malformed_response")])
def test_unusable_completion_preserves_returned_usage(monkeypatch, finish, code):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-nebius-placeholder")
    def handler(request):
        if request.url.path.endswith("models"):
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        return httpx.Response(200, json={"id": "failed-completion", "model": MODEL,
            "choices": [{"message": {"content": None}, "finish_reason": finish}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 23}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = TaskRequest(task_id="t", task_type="test", prompt="test")
            return await NebiusTokenFactoryProvider(client=client).generate(task, await ConcurrencyRouter(InferenceTier.NANO).route(task))
    result = asyncio.run(run())
    assert result.status.value == "FAILED" and result.metadata["error_code"] == code
    assert (result.metadata["actual_input_tokens"], result.metadata["actual_output_tokens"]) == (11, 23)
    assert result.metadata["finish_reason"] == finish and result.metadata["request_id"] == "failed-completion"
    assert result.estimated_cost_usd is None


def test_schema_diagnostics_do_not_echo_invalid_values():
    from agentkernel.concurrency.repair.patch_parser import parse_repair, validation_details
    with pytest.raises(ValueError) as caught:
        parse_repair(json.dumps({"confidence": "private-value-not-for-logs"}))
    details = validation_details(caught.value)
    assert any(item["field"] == "confidence" for item in details)
    assert "private-value" not in json.dumps(details)


@pytest.mark.parametrize("failure", [429, 500, 503, "timeout", "connection"])
def test_bounded_transient_retry_and_real_metadata(monkeypatch, failure):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-nebius-placeholder")
    calls = []
    sleeps = []
    async def sleep(delay):
        sleeps.append(delay)
    monkeypatch.setattr("agentkernel.providers.nebius_token_factory.asyncio.sleep", sleep)
    def handler(request):
        if request.url.path.endswith("models"):
            return httpx.Response(200, json={"data": [{"id": MODEL}]})
        calls.append(request)
        if len(calls) < 3:
            if failure == "timeout":
                raise httpx.ReadTimeout("must never log test-nebius-placeholder")
            if failure == "connection":
                raise httpx.ConnectError("must never log test-nebius-placeholder")
            return httpx.Response(failure, text="test-nebius-placeholder")
        return httpx.Response(200, headers={"x-request-id": "request-123"}, json={
            "model": MODEL, "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 17, "completion_tokens": 4}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            task = TaskRequest(task_id="t", task_type="smoke", prompt="test")
            return await NebiusTokenFactoryProvider(client=client).generate(task, await ConcurrencyRouter(InferenceTier.NANO).route(task))
    result = asyncio.run(run())
    assert result.status.value == "SUCCESS" and len(calls) == 3 and sleeps == [0.5, 1.0]
    assert result.metadata["retry_count"] == 2 and result.metadata["request_id"] == "request-123"
    assert result.metadata["finish_reason"] == "stop" and result.metadata["actual_input_tokens"] == 17
    assert result.metadata["actual_output_tokens"] == 4 and result.latency_ms > 0
    assert result.estimated_cost_usd is None and "test-nebius-placeholder" not in result.model_dump_json()


@pytest.mark.parametrize("code", [400, 401, 403, 404, 422])
def test_permanent_errors_never_retry_or_escalate(monkeypatch, code):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-nebius-placeholder")
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(code, text="test-nebius-placeholder")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await AgentKernel(ConcurrencyRouter(InferenceTier.NANO), LocalRTXProvider(),
                NebiusTokenFactoryProvider(client=client), TelemetryRecorder(), RepairContractVerifier()).execute(
                    TaskRequest(task_id="t", task_type="test", prompt="test"))
    result = asyncio.run(run())
    assert len(calls) == 1 and len(result.attempts) == 1 and not result.success


def test_catalog_discovery_and_unknown_usage(monkeypatch):
    monkeypatch.setenv("NEBIUS_API_KEY", "test-nebius-placeholder")
    def handler(request):
        if request.url.path.endswith("models"):
            return httpx.Response(200, json={"data": [{"id": MODEL}, {"id": "other/available"}]})
        return httpx.Response(200, json={"id": "completion-id", "model": MODEL,
            "choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            provider = NebiusTokenFactoryProvider(client=client)
            health = await provider.check_models()
            assert health.model_ids == sorted([MODEL, "other/available"])
            task = TaskRequest(task_id="t", task_type="test", prompt="test")
            return await provider.generate(task, await ConcurrencyRouter(InferenceTier.NANO).route(task))
    result = asyncio.run(run())
    assert result.metadata["actual_input_tokens"] is None and not result.metadata["usage_available"]
    assert result.estimated_cost_usd is None and result.metadata["request_id"] == "completion-id"


def test_malformed_contract_gets_one_same_tier_correction_only():
    result = asyncio.run(AgentKernel(ConcurrencyRouter(InferenceTier.SUPER), LocalRTXProvider(),
        MockNebiusProvider(lambda task, route: "not JSON"), TelemetryRecorder(), RepairContractVerifier(),
        max_attempts=4, tier_schedule=(InferenceTier.SUPER, InferenceTier.ULTRA)).execute(
            TaskRequest(task_id="t", task_type="test", prompt="test")))
    assert [a.tier for a in result.attempts] == [InferenceTier.SUPER, InferenceTier.SUPER]
    assert result.stopped_reason == "invalid_model_output"
    assert "Invalid repair JSON" in result.attempts[1].input_prompt


def test_explicit_env_file_is_literal_and_does_not_echo_values(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("NEBIUS_API_KEY='literal-$(do-not-execute)'\nLANGSMITH_PROJECT=test\n")
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_PROJECT", "exported")
    load_env_file(path)
    import os
    assert os.environ["NEBIUS_API_KEY"] == "literal-$(do-not-execute)"
    assert os.environ["LANGSMITH_PROJECT"] == "exported"
    path.write_text("SECRET VALUE WITHOUT EQUALS")
    with pytest.raises(ValueError, match="line 1") as error:
        load_env_file(path)
    assert "SECRET VALUE" not in str(error.value)


def trace_server(visibility_misses=0):
    runs, feedback, requests = {}, [], []
    def handler(request):
        nonlocal visibility_misses
        payload = json.loads(request.content) if request.content else {}
        requests.append((request.method, request.url.path, payload))
        if request.method == "POST" and request.url.path == "/runs":
            runs[payload["id"]] = payload
        elif request.method == "PATCH":
            original = runs[request.url.path.split("/")[-1]]
            assert "parent_run_id" in payload
            assert payload["parent_run_id"] == original["parent_run_id"]
            assert payload["trace_id"] == original["trace_id"]
            assert payload["dotted_order"] == original["dotted_order"]
        elif request.method == "GET":
            if visibility_misses:
                visibility_misses -= 1
                return httpx.Response(404, json={"detail": "Not yet indexed"})
            return httpx.Response(200, json={**runs[request.url.path.split("/")[-1]], "session_id": "00000000-0000-0000-0000-000000000001"})
        elif request.url.path == "/feedback":
            feedback.append(payload)
        return httpx.Response(200, json={})
    return handler, runs, feedback, requests


def test_langsmith_hierarchy_redaction_feedback_and_confirmation(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-private-langsmith-value")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    handler, runs, feedback, requests = trace_server(visibility_misses=2)
    waits = []
    async def record_wait(delay):
        waits.append(delay)
    monkeypatch.setattr("agentkernel.observability.langsmith_observer.asyncio.sleep", record_wait)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            observer = LangSmithObserver(client=client)
            async with trace("Job", observer, task_id="t", api_key="leak", environment={"password": "leak"}):
                async with span("nano_triage", run_type="llm") as observed:
                    observed.update(model_id="test-private-langsmith-value", input_tokens=3, logs="secret raw logs")
                async with span("verification_campaign") as observed:
                    await observed.feedback(verification_passed=True, false_fix=False)
            return await observer.flush()
    result = asyncio.run(run())
    assert result["status"] == "confirmed" and result["spans_submitted"] == 3
    assert waits == [0.5, 1.0]
    root = next(run for run in runs.values() if run["parent_run_id"] is None)
    assert all(run["parent_run_id"] == root["id"] for run in runs.values() if run is not root)
    exported = json.dumps(requests)
    assert "test-private-langsmith-value" not in exported and "secret raw logs" not in exported and '"api_key"' not in exported
    assert {f["key"] for f in feedback} == {"verification_passed", "false_fix"}


def test_observer_transport_failure_does_not_replace_execution_result(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-private-langsmith-value")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(401, text="test-private-langsmith-value"))) as client:
            observer = LangSmithObserver(client=client)
            async with trace("Job", observer):
                pass
            return await observer.flush()
    result = asyncio.run(run())
    assert result["status"] == "unavailable" and result["error_code"] == "langsmith_http_401"
    assert "test-private" not in json.dumps(result)


def test_full_trace_with_mock_models_and_real_offline_execution(monkeypatch, tmp_path):
    monkeypatch.setenv("LANGSMITH_API_KEY", "test-langsmith-placeholder")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    source = "print('FAIL')\n"
    (tmp_path / "main.c").write_text(source)
    task = ConcurrencyTask(task_id="trace", workspace=tmp_path, source_files=["main.c"],
        build_command=[sys.executable, "-c", "pass"], run_command=[sys.executable, "main.c"],
        max_runtime_seconds=5, stress_runs=1, verification_config=VerificationConfig(stress_runs=2))
    def response(request, route):
        if request.metadata["phase"] == "triage":
            return mock_concurrency_response(request, route)
        replacement = "print('STILL FAILS')\n" if route.selected_tier == InferenceTier.SUPER else "print('PASS')\n"
        return json.dumps({"diagnosis": "test", "root_cause": "test", "confidence": 0.8,
            "patch": "".join(difflib.unified_diff(source.splitlines(True), replacement.splitlines(True), fromfile="a/main.c", tofile="b/main.c")),
            "expected_effect": "test", "risk_notes": []})
    handler, runs, feedback, requests = trace_server()
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await ConcurrencyBugHunter(MockNebiusProvider(response), policy=ConcurrencyPolicy(max_super_repairs=1),
                                               observer=LangSmithObserver(client=client)).run(task)
    result = asyncio.run(run())
    assert result.status == "verified" and result.route == ["NANO", "SUPER", "ULTRA"]
    by_name = {run["name"]: run for run in runs.values()}
    assert {"baseline_compile", "baseline_stress_campaign", "fingerprint_analysis", "nano_triage", "super_diagnosis",
            "patch_application", "verification_campaign", "ultra_escalation", "ultra_diagnosis"} <= by_name.keys()
    assert by_name["ultra_diagnosis"]["parent_run_id"] == by_name["ultra_escalation"]["id"]
    assert any(f["key"] == "false_fix" and f["score"] == 1 for f in feedback)
    assert (tmp_path / "main.c").read_text() == source
