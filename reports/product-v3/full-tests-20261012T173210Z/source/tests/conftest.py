import os

import pytest


@pytest.fixture(autouse=True)
def isolated_local_environment(monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> None:
    """A developer's real-mode environment must never activate network in tests."""
    if request.node.get_closest_marker("nebius") or request.node.get_closest_marker("langsmith"):
        return  # Explicitly selected live tests need the account's exact model IDs.
    for key in tuple(os.environ):
        if key.startswith("AGENTKERNEL_"):
            monkeypatch.delenv(key)
    # Legacy subprocess fixtures run only inside the remote test container.
    # Production constructors always use Nebius; this is explicit test injection.
    if os.getenv("AK_REMOTE_TEST_HOST") == "1" and request.node.path.name != "test_nebius_sandbox.py":
        from agentkernel.concurrency.sandbox.local import LocalSandboxBackend
        from agentkernel.concurrency import app, smoke
        from agentkernel.concurrency.verification import repair_verifier
        for module in (app, smoke, repair_verifier):
            monkeypatch.setattr(module, "NebiusSandboxBackend", LocalSandboxBackend)
