"""Bridge boundary checks; no paid requests or repository program execution."""
import asyncio
import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
from sites_connection_agent import Agent, model_quote, safe_subdirectory, single_agent


class ConnectionTests(unittest.TestCase):
    def test_only_one_agent_can_hold_workspace_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            with single_agent(Path(directory)):
                with self.assertRaises(RuntimeError):
                    with single_agent(Path(directory)):
                        self.fail('A second agent acquired the live budget ledger')
            with single_agent(Path(directory)):
                pass

    def test_clean_release_can_seed_without_private_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'project'
            shutil.copytree(SCRIPTS.parent / 'examples/job-queue-service', root / 'examples/job-queue-service')
            shutil.copytree(SCRIPTS.parent / 'tests/fixtures/sites-seed', root / 'tests/fixtures/sites-seed')
            with patch('sites_connection_agent.ROOT', root):
                agent = Agent(Path(directory) / 'state')
                agent.seed()
            self.assertEqual(len(agent.state['repositories']), 2)
            self.assertTrue(all(row['ready'] for row in agent.state['repositories']))

    def test_bound_covers_input_reservation_and_output(self):
        self.assertAlmostEqual(model_quote({'context_length': 262144, 'pricing': {'prompt': '.0000001', 'completion': '.0000003'}}), .0054144)
        with self.assertRaises(ValueError):
            model_quote({'context_length': 262144, 'pricing': {'prompt': 'NaN', 'completion': '1'}})

    def test_rejects_escape_and_hidden_subdirectories(self):
        with tempfile.TemporaryDirectory() as directory:
            for value in ('../secrets', '/outside', 'C:/outside', '.git', 'x\\y'):
                with self.assertRaises(ValueError):
                    safe_subdirectory(Path(directory), value)

    def test_requires_review_before_any_run(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Agent(Path(directory))
            with self.assertRaises(ValueError):
                asyncio.run(agent.repair({'reviewed': False}, 'never-start'))
            self.assertFalse((Path(directory)/'runs').exists())

    CATALOG = [{'id': 'nvidia/nemotron-3-super-120b-a12b', 'context_length': 262144, 'pricing': {'prompt': '0.0000003', 'completion': '0.0000009'}},
               {'id': 'nvidia/Nemotron-3-Ultra-550b-a55b', 'context_length': 1048576, 'pricing': {'prompt': '0.000001', 'completion': '0.000003'}}]

    def offline_catalog(self, agent):
        rows = self.CATALOG
        class Response:
            def raise_for_status(self): pass
            def json(self): return {'data': rows}
        class Client:
            def __init__(self, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *exc): return False
            async def get(self, *a, **kw): return Response()
        with patch('sites_connection_agent.httpx.AsyncClient', Client), patch('sites_connection_agent.artifact_ready', lambda root: False), \
                patch.dict('os.environ', {'NEBIUS_API_KEY': 'offline-test'}):
            asyncio.run(agent.catalog())

    def test_v4_option_is_bounded_two_ultra_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Agent(Path(directory)); self.offline_catalog(agent)
            option = agent.models[0]
            self.assertEqual((option['id'], option['max_calls']), ('agentkernel/adaptive-v4', 2))
            self.assertAlmostEqual(option['bound_usd'], 2 * (0.000001 * 36000 + 0.000003 * 8192))

    def test_v4_rejects_short_contract_or_low_approval_before_any_run(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Agent(Path(directory))
            budgets = {'max_model_calls': 1, 'max_total_tokens': 150144, 'max_input_tokens_per_call': 48000, 'max_wall_seconds': 1800}
            agent.state['repositories'] = [{'id': 'r', 'ready': True, 'plan_sha256': 'p', 'contract': {'budgets': budgets}}]
            self.offline_catalog(agent)
            async def loaded(self): return None
            with patch.object(Agent, 'catalog', loaded):
                for approved, calls in ((0.25, 1), (0.01, 3)):
                    budgets['max_model_calls'] = calls
                    with self.assertRaises(ValueError):
                        asyncio.run(agent.repair({'reviewed': True, 'model': 'agentkernel/adaptive-v4', 'repository': 'r',
                                                  'plan_sha256': 'p', 'max_cost_usd': approved}, 'never-start'))
            self.assertFalse((Path(directory) / 'runs').exists())
            self.assertEqual(agent.state['runs'], [])

    def test_unknown_call_keeps_full_reservation_and_never_replays(self):
        with tempfile.TemporaryDirectory() as directory:
            agent = Agent(Path(directory))
            agent.state['runs'] = [{'id': 'interrupted', 'status': 'running', 'reserved_usd': .2, 'model_calls': 1}]
            agent.persist()
            resumed = Agent(Path(directory))
            self.assertEqual(resumed.state['runs'][0]['status'], 'unknown')
            self.assertAlmostEqual(resumed.remaining(), 9.7)
            asyncio.run(resumed.handle({'id': 'interrupted', 'payload': 'invalid JSON that must never be read'}))
            self.assertEqual(len(resumed.state['runs']), 1)

    def test_seeding_preserves_originals_and_requires_all_gates(self):
        with tempfile.TemporaryDirectory() as directory:
            # Production seeding reads an old experiment's task description. A
            # portable copy tests the same behavior without requiring private
            # reports or a particular developer's absolute workspace path.
            root = Path(directory) / 'project'
            project = SCRIPTS.parent
            shutil.copytree(project / 'examples/job-queue-service', root / 'examples/job-queue-service')
            fixture = project / 'tests/fixtures/sites-seed'
            pair = root / 'pair_snapshot'
            shutil.copytree(fixture / 'pair_snapshot', pair)
            task = json.loads((fixture / 'task.json').read_text())
            task['workspace'] = str(pair)
            history = root / 'reports/prompting-generalization/20261011T103149Z'
            history.mkdir(parents=True)
            (history / 'plan.json').write_text(json.dumps({'jobs': [{'task': task}]}))
            originals = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
            with patch('sites_connection_agent.ROOT', root):
                agent = Agent(Path(directory) / 'state')
                agent.seed()
            self.assertEqual(len(agent.state['repositories']), 2)
            for repo in agent.state['repositories']:
                self.assertTrue(repo['ready'])
                v = repo['contract']['verification']
                self.assertEqual(v['stress_runs'], 100)
                self.assertEqual(v['sanitizer_runs'], 3)
                self.assertTrue(v['required_original_tests'])
                self.assertTrue(v['sanitizer_required'])
                self.assertTrue(any(not f['editable'] for f in repo['files']))
            for path, digest in originals.items():
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), digest)


if __name__ == '__main__':
    unittest.main()
