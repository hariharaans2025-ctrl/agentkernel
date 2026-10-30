"""Never selected by default. These checks use real accounts when explicitly selected."""
import asyncio
import os

import pytest

from agentkernel.concurrency.smoke import smoke
from agentkernel.observability import trace, span
from agentkernel.observability.langsmith_observer import LangSmithObserver
from agentkernel.providers.nebius_token_factory import NebiusTokenFactoryProvider


@pytest.mark.nebius
def test_live_token_factory_catalog():
    if not os.getenv("NEBIUS_API_KEY"):
        pytest.skip("NEBIUS_API_KEY is required for this opt-in account check")
    result = asyncio.run(NebiusTokenFactoryProvider().check_models())
    assert not result.error, result.error
    assert result.model_ids


@pytest.mark.nebius
@pytest.mark.integration
def test_live_nano_structured_smoke():
    if not os.getenv("NEBIUS_API_KEY"):
        pytest.skip("NEBIUS_API_KEY is required for this opt-in paid smoke test")
    result = asyncio.run(smoke("nano"))
    assert result["status"] == "passed", result["status"]
    assert result["calls"][0]["model_id"]


@pytest.mark.langsmith
def test_live_langsmith_span_delivery(monkeypatch):
    if not os.getenv("LANGSMITH_API_KEY"):
        pytest.skip("LANGSMITH_API_KEY is required for this opt-in tracing check")
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    async def run():
        observer = LangSmithObserver()
        async with trace("AgentKernelObservabilitySmoke", observer, task_id="tracing-smoke"):
            async with span("transport_check", status="completed"):
                pass
        return await observer.flush()
    result = asyncio.run(run())
    assert result["status"] == "confirmed", result.get("error_code")
    assert len(result["spans_observed"]) == 2
