import sys

import pytest

from agentkernel.cli import main
from agentkernel.local.base import LocalBackendStatus
from agentkernel.providers.local_rtx import LocalRTXProvider


def test_cli_mock(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["agentkernel", "--task", "ImportError", "--verification-plan", '{"LOCAL": true}'])
    main()
    output = capsys.readouterr().out
    assert "Execution: MOCK" in output
    assert "Latency (simulated)" in output
    assert "Cloud cost: $0.0000" in output


def test_cli_real_missing_model(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("AGENTKERNEL_LOCAL_MOCK", "false")
    monkeypatch.setattr(sys, "argv", ["agentkernel", "--task", "ImportError"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert "AGENTKERNEL_LOCAL_MODEL" in capsys.readouterr().out


@pytest.mark.parametrize("available", [True, False])
def test_cli_health(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], available: bool) -> None:
    async def health(self: LocalRTXProvider) -> LocalBackendStatus:
        return LocalBackendStatus(available=available, backend="ollama", configured_model="test-model",
                                  error=None if available else "Could not connect")
    monkeypatch.setattr(LocalRTXProvider, "health_check", health)
    monkeypatch.setattr(sys, "argv", ["agentkernel", "--health"])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == (0 if available else 1)
    output = capsys.readouterr().out
    assert f"Status: {'AVAILABLE' if available else 'UNAVAILABLE'}" in output
