import asyncio
import math
import os
from time import perf_counter
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .base import LocalBackendError, LocalBackendStatus, LocalInferenceBackend, LocalInferenceResponse


class _Generation(BaseModel):
    model_config = ConfigDict(strict=True)
    model: str = Field(min_length=1)
    response: str = Field(min_length=1)
    done: bool
    prompt_eval_count: int | None = Field(default=None, ge=0)
    eval_count: int | None = Field(default=None, ge=0)


class OllamaBackend(LocalInferenceBackend):
    """Non-streaming Ollama adapter. Never installs or downloads models.

    An injected AsyncClient is owned by the caller; otherwise each request owns
    its client. This keeps the adapter usable across separate asyncio.run calls.
    """

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self.url = os.getenv("AGENTKERNEL_OLLAMA_URL", "http://localhost:11434").strip().rstrip("/")
        self.model = os.getenv("AGENTKERNEL_LOCAL_MODEL", "").strip() or None
        self._timeout_value = os.getenv("AGENTKERNEL_LOCAL_TIMEOUT_SECONDS", "120")
        self._client = client

    def _configuration(self, *, require_model: bool = True) -> float:
        try:
            url = urlsplit(self.url)
            valid = (url.scheme in {"http", "https"} and url.hostname in {"localhost", "127.0.0.1", "::1"}
                     and not url.username and not url.password and not url.query and not url.fragment
                     and url.path in {"", "/"})
            _ = url.port
        except ValueError:
            valid = False
        if not valid:
            raise LocalBackendError("AGENTKERNEL_OLLAMA_URL must be a loopback HTTP(S) URL, e.g. http://localhost:11434.")
        try:
            timeout = float(self._timeout_value)
            if not math.isfinite(timeout) or timeout <= 0:
                raise ValueError
        except ValueError as exc:
            raise LocalBackendError("AGENTKERNEL_LOCAL_TIMEOUT_SECONDS must be a positive finite number.") from exc
        if require_model and not self.model:
            raise LocalBackendError("Set AGENTKERNEL_LOCAL_MODEL to an already installed model name from `ollama list`.")
        if self.model and (self.model.endswith("-cloud") or self.model.endswith(":cloud")):
            raise LocalBackendError("Cloud models are not supported. Set AGENTKERNEL_LOCAL_MODEL to an installed local model.")
        return timeout

    async def _request(self, method: str, path: str, timeout: float,
                       payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            # A total deadline bounds even a server that sends a trickle of bytes.
            async with asyncio.timeout(timeout):
                if self._client is not None:
                    response = await self._client.request(method, self.url + path, json=payload, timeout=timeout)
                else:
                    async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                                timeout=httpx.Timeout(timeout, connect=min(5.0, timeout))) as client:
                        response = await client.request(method, self.url + path, json=payload)
            response.raise_for_status()
        except (httpx.TimeoutException, TimeoutError) as exc:
            raise LocalBackendError(f"Ollama timed out after {timeout:g}s at {self.url}. Check the server or increase AGENTKERNEL_LOCAL_TIMEOUT_SECONDS.") from exc
        except httpx.HTTPStatusError as exc:
            hint = " Check AGENTKERNEL_LOCAL_MODEL against `ollama list`." if exc.response.status_code == 404 else " Check the Ollama server logs."
            raise LocalBackendError(f"Ollama returned HTTP {exc.response.status_code}.{hint}") from exc
        except httpx.RequestError as exc:
            raise LocalBackendError(f"Could not connect to {self.url}. Start Ollama and check AGENTKERNEL_OLLAMA_URL.") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise LocalBackendError("Ollama returned malformed JSON.") from exc
        if not isinstance(data, dict):
            raise LocalBackendError("Ollama returned malformed response: expected a JSON object.")
        if "error" in data:
            raise LocalBackendError("Ollama reported an error. Check the configured model and Ollama server logs.")
        return data

    async def generate(self, prompt: str, system_prompt: str | None = None) -> LocalInferenceResponse:
        timeout = self._configuration()
        payload: dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False}
        if system_prompt is not None:
            payload["system"] = system_prompt
        start = perf_counter()
        data = await self._request("POST", "/api/generate", timeout, payload)
        latency_ms = (perf_counter() - start) * 1000
        try:
            parsed = _Generation.model_validate(data)
            if not parsed.done or not parsed.response.strip():
                raise ValueError("Incomplete generation")
        except (ValidationError, ValueError) as exc:
            raise LocalBackendError("Ollama returned malformed or incomplete generation data.") from exc
        return LocalInferenceResponse(
            output_text=parsed.response, model=parsed.model, latency_ms=latency_ms,
            input_tokens=parsed.prompt_eval_count, output_tokens=parsed.eval_count,
            metadata={"backend": "ollama", "configured_model": self.model,
                      "latency_source": "wall_clock", "gpu_verified": False},
        )

    async def health_check(self) -> LocalBackendStatus:
        try:
            timeout = self._configuration(require_model=False)
            data = await self._request("GET", "/api/tags", min(5.0, timeout))
            models = data.get("models")
            if not isinstance(models, list) or any(
                not isinstance(model, dict) or not isinstance(model.get("name"), str) for model in models
            ):
                raise LocalBackendError("Ollama returned malformed model-list data.")
            self._configuration()
            names = {model["name"] for model in models}
            # Ollama resolves an untagged name to :latest.
            model_name = self.model or ""
            if ":" not in model_name.rsplit("/", 1)[-1]:
                model_name += ":latest"
            if self.model not in names and model_name not in names:
                raise LocalBackendError("Configured model is not installed. Set AGENTKERNEL_LOCAL_MODEL to a name from `ollama list`; AgentKernel will not download it.")
        except LocalBackendError as exc:
            return LocalBackendStatus(available=False, backend="ollama", configured_model=self.model, error=str(exc))
        return LocalBackendStatus(available=True, backend="ollama", configured_model=self.model)
