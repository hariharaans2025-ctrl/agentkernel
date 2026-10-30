import asyncio
import json

import httpx

from agentkernel.dashboard.metrics import benchmark_metrics
from agentkernel.dashboard.service import CapturingProvider
from agentkernel.concurrency.analyzer.routing import ConcurrencyRouter
from agentkernel.core.enums import InferenceTier
from agentkernel.core.models import TaskRequest


def test_combined_unknown_usage_and_weighted_verification():
    run = {'provenance': 'real', 'results': {
        'NANO': {'inference': {'latency_ms': 2000, 'metadata': {'actual_input_tokens': 30, 'actual_output_tokens': 10}},
                 'job': {'status': 'verified', 'verification': {'total_runs': 100, 'passed_runs': 100}}},
        'SUPER': {'job': {'verification': {'total_runs': 50, 'passed_runs': 25}}},
        'ULTRA': {'status': 'failed'}}}
    m = benchmark_metrics(run)
    assert m['combined']['total_tokens'] is None
    assert m['combined']['total_tokens_known_subtotal'] == 40
    assert m['combined']['estimated_inference_cost_usd'] is None
    assert m['combined']['verification_pass_rate'] == 125 / 150
    assert m['combined']['models_with_verification'] == 2
    assert m['individual']['NANO']['effective_output_tokens_per_second'] == 5
    assert m['individual']['ULTRA']['deadlocks'] is None
    run['provenance'] = 'saved_response_replay'
    assert benchmark_metrics(run)['combined']['total_tokens_known_subtotal'] is None


def test_budget_is_enforced_on_actual_http_payload(monkeypatch):
    monkeypatch.setenv('NEBIUS_API_KEY', 'offline-placeholder')
    async def run(prompt):
        p = CapturingProvider(lambda **kw: None)
        posts = []
        def handle(request):
            if request.method == 'GET':
                return httpx.Response(200, json={'data': [{'id': m} for m in p.models.values()]})
            posts.append(json.loads(request.content))
            return httpx.Response(200, json={'model': p.models[InferenceTier.SUPER],
                'choices': [{'message': {'content': '{}'}, 'finish_reason': 'stop'}],
                'usage': {'prompt_tokens': 12, 'completion_tokens': 2}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            p._client = client
            task = TaskRequest(task_id='bounded', task_type='concurrency_repair', prompt=prompt,
                               metadata={'phase': 'repair', 'max_output_tokens': 8192})
            result = await p.generate(task, await ConcurrencyRouter(InferenceTier.SUPER).route(task))
        return result, posts
    result, posts = asyncio.run(run('Return concise edits'))
    assert len(posts) == 1 and posts[0]['max_tokens'] == 2048
    assert result.metadata['requested_max_input_bytes'] == 12000
    result, posts = asyncio.run(run('x' * 12001))
    assert posts == []
    assert result.metadata['error_code'] == 'input_budget_exceeded'
