"""Small buffered REST adapter; no LangSmith calls in runtime/application logic."""
import asyncio
import os
from datetime import datetime, timezone
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from agentkernel.telemetry.redaction import redact
from .base import ObservabilityBackend, SpanHandle
from .safety import FEEDBACK, safe_metadata


class LangSmithObserver(ObservabilityBackend):
    def __init__(self, *, client: httpx.AsyncClient | None = None):
        self.client = client
        self.key = os.getenv("LANGSMITH_API_KEY", "").strip()
        self.endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com").rstrip("/")
        self.project = os.getenv("LANGSMITH_PROJECT", "concurrency-bug-hunter")
        self.workspace = os.getenv("LANGSMITH_WORKSPACE_ID", "")
        self.enabled = os.getenv("LANGSMITH_TRACING", "false").lower() == "true"
        self.operations = []
        self.spans: dict[str, SpanHandle] = {}
        self.feedback = []
        self.overflow = False

    async def start_span(self, name, parent, metadata, run_type="chain"):
        if not self.enabled:
            return None
        if len(self.spans) >= 128:
            self.overflow = True
            return None
        started = datetime.now(timezone.utc)
        run_id = str(uuid4())
        order = started.strftime("%Y%m%dT%H%M%S%fZ") + run_id
        if parent:
            order = parent.dotted_order + "." + order
        handle = SpanHandle(run_id, name, parent.trace_id if parent else run_id, parent.id if parent else None, order)
        self.spans[run_id] = handle
        self.operations.append(("POST", "/runs", {
            "id": run_id, "name": name[:80], "run_type": run_type, "session_name": redact(self.project),
            "trace_id": handle.trace_id, "dotted_order": order, "parent_run_id": handle.parent_id,
            "start_time": started.isoformat(), "inputs": {}, "extra": {"metadata": safe_metadata(metadata)}}))
        return handle

    async def end_span(self, span, metadata, error=None):
        if span is not None:
            payload = {"end_time": datetime.now(timezone.utc).isoformat(), "outputs": safe_metadata(metadata),
                       "trace_id": span.trace_id, "dotted_order": span.dotted_order,
                       "parent_run_id": span.parent_id}
            if error:
                payload["error"] = "Operation failed: " + type(error).__name__ if not isinstance(error, str) else redact(error[:100])
            self.operations.append(("PATCH", "/runs/" + span.id, payload))

    async def record_feedback(self, span, key, value):
        if span is not None and key in FEEDBACK and value is not None and type(value) in (bool, int, float, str) and len(self.feedback) < 128:
            field = {'value': value[:80]} if isinstance(value, str) else {'score': int(value) if isinstance(value, bool) else value}
            self.feedback.append({"id": str(uuid4()), "run_id": span.id, "key": key, **field,
                                  "feedback_source": {"type": "api", "metadata": {"origin": "deterministic_execution"}}})

    async def flush(self):
        result = {"backend": "langsmith", "project": redact(self.project), "status": "disabled", "spans_submitted": 0,
                  "spans_observed": [], "feedback_submitted": 0,
                  "trace_ids": sorted({span.trace_id for span in self.spans.values()})}
        if not self.enabled:
            return result
        if not self.key:
            return {**result, "status": "unavailable", "error_code": "missing_langsmith_api_key"}
        try:
            url = urlsplit(self.endpoint)
            if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment:
                raise ValueError
        except ValueError:
            return {**result, "status": "unavailable", "error_code": "invalid_langsmith_endpoint"}
        headers = {"x-api-key": self.key}
        if self.workspace:
            headers["x-tenant-id"] = self.workspace
        async def send(client, method, path, payload=None):
            response = await client.request(method, self.endpoint + path, headers=headers, json=payload,
                                            timeout=10, follow_redirects=False)
            if not 200 <= response.status_code < 300:
                raise RuntimeError(f"langsmith_http_{response.status_code}")
            return response
        async def deliver(client):
            for method, path, payload in self.operations:
                await send(client, method, path, payload)
                if method == "POST":
                    result["spans_submitted"] += 1
            sessions = {}
            # Confirm server-visible hierarchy; submission alone is not a verified trace.
            for run_id, span in self.spans.items():
                # Accepted ingestion is asynchronous; only retry readback's not-found.
                for attempt in range(4):
                    try:
                        response = await send(client, "GET", "/runs/" + run_id)
                        break
                    except RuntimeError as exc:
                        if str(exc) != "langsmith_http_404" or attempt == 3:
                            raise
                        await asyncio.sleep(0.5 * 2 ** attempt)
                data = response.json()
                if str(data.get("id")) != run_id or data.get("parent_run_id") != span.parent_id:
                    raise RuntimeError("langsmith_hierarchy_mismatch")
                sessions[run_id] = data.get("session_id")
                result["spans_observed"].append({"id": run_id, "name": span.name, "parent_id": span.parent_id})
            for feedback in self.feedback:
                session_id = sessions.get(feedback["run_id"])
                if not session_id:
                    raise RuntimeError("langsmith_session_id_unavailable")
                await send(client, "POST", "/feedback", {**feedback, "session_id": session_id})
                result["feedback_submitted"] += 1
        try:
            async with asyncio.timeout(60):
                if self.client is not None:
                    await deliver(self.client)
                else:
                    async with httpx.AsyncClient(trust_env=False) as client:
                        await deliver(client)
            result["status"] = "confirmed" if not self.overflow else "partial"
        except (httpx.RequestError, TimeoutError, ValueError):
            result.update(status="unavailable", error_code="langsmith_transport_or_response_error")
        except RuntimeError as exc:
            result.update(status="unavailable", error_code=str(exc))
        finally:
            self.operations.clear()
            self.feedback.clear()
            self.spans.clear()
        return result
