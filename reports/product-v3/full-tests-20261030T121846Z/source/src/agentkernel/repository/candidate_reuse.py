"""Reuse a proposal, never its verification verdict. Local workspace scoped and opt-in."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from time import perf_counter, time

from agentkernel.concurrency.sandbox.local import safe_path
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend
from agentkernel.concurrency.verification.concurrency_verifier import ConcurrencyVerifier
from agentkernel.repository.learning import require_verified


def hash_bytes(value):
    return hashlib.sha256(value).hexdigest()


def validate_contract(task):
    v = task.verification_config
    if (v.stress_runs < 100 or v.sanitizer_runs < 3 or not v.required_build_success
            or not v.required_original_tests or not v.original_test_commands
            or not v.semantic_checks or not all(c.required for c in v.semantic_checks)
            or not v.sanitizer_required or not v.sanitizer_enabled
            or v.allowed_deadlocks or v.allowed_races or v.allowed_crashes):
        raise ValueError('Candidate reuse requires the complete independent verifier')


class VerifiedCandidateCache:
    def __init__(self, root, *, ttl_seconds=604800, clock=time):
        self.root = Path(root)
        if not 0 < ttl_seconds <= 604800:
            raise ValueError('Candidate cache TTL must be at most seven days')
        self.ttl = ttl_seconds
        self.clock = clock

    def identity(self, task, policy):
        validate_contract(task)
        files = {}
        for name in task.source_files + task.support_files:
            path = safe_path(task.workspace.resolve(), name)
            if not path.is_file() or path.stat().st_size > 2000000:
                raise ValueError('Invalid candidate reuse file scope')
            files[name] = hash_bytes(path.read_bytes())
        # Any verifier/runtime implementation change invalidates the proposal cache.
        package = Path(__file__).resolve().parents[1]
        verifier = {p.relative_to(package).as_posix(): hash_bytes(p.read_bytes())
                    for p in (package/'concurrency').rglob('*.py')}
        identity = {'schema': 1, 'policy': policy, 'task': task.model_dump(mode='json'), 'files': files,
                    'verifier': verifier, 'image': os.getenv('AGENTKERNEL_SANDBOX_IMAGE', 'python:3.12'),
                    'reuse_implementation': hash_bytes(Path(__file__).read_bytes())}
        key = hash_bytes(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode())
        return key, identity

    def lookup(self, key, identity):
        path = self.root / (key+'.json')
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 2000000:
            return None
        try:
            entry = json.loads(path.read_text(encoding='utf-8'))
            age = self.clock()-entry['created']
            if (not 0 <= age <= self.ttl or entry['identity'] != identity
                    or hash_bytes(entry['patch'].encode()) != entry['patch_sha256']):
                return None
            require_verified(entry['verification'], identity['task']['verification_config'])
            if entry['verification'].get('evidence',{}).get('original_tests',{}).get('passed') is not True:
                return None
            return entry
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def admit(self, key, identity, patch, verification, origin):
        require_verified(verification, identity['task']['verification_config'])
        if verification.get('evidence',{}).get('original_tests',{}).get('passed') is not True:
            raise ValueError('Original tests did not pass')
        if not isinstance(patch, str) or not patch or len(patch.encode()) > 300000:
            raise ValueError('Invalid canonical proposal')
        entry = {'created': self.clock(), 'identity': identity, 'patch': patch,
                 'patch_sha256': hash_bytes(patch.encode()), 'verification': verification,
                 'origin_evidence': str(origin)}
        self.root.mkdir(parents=True, exist_ok=True)
        # Never overwrite a prior cache record. Expired entries are misses until removed explicitly.
        path = self.root / (key+'.json')
        if not path.exists():
            with path.open('x', encoding='utf-8') as stream:
                json.dump(entry, stream, indent=2)


async def run_with_candidate_reuse(task, folder, *, cache, policy, run_fresh,
                                   campaign_factory, on_progress=None):
    """A miss invokes the unchanged route. A hit runs only fresh remote verification."""
    tick = perf_counter()
    key, identity = cache.identity(task, policy)
    entry = cache.lookup(key, identity)
    lookup_ms = (perf_counter()-tick)*1000
    folder = Path(folder)
    if entry is None:
        result = await run_fresh(task, folder)
        admitted = False
        if result.get('status') == 'verified' and cache.identity(task, policy)[0] == key:
            successful = next((r for r in reversed(result.get('attempts',[])) if r.get('outcome')=='verified'), None)
            if successful:
                evidence = folder / successful['stage'] / 'verification.json'
                if evidence.is_file():
                    cache.admit(key, identity, successful['patch'], json.loads(evidence.read_text()), folder)
                    admitted = True
        metrics = {'hit': False, 'lookup_ms': lookup_ms, 'admitted': admitted, 'key': key}
        (folder/'candidate-reuse.json').write_text(json.dumps(metrics, indent=2), encoding='utf-8')
        result['candidate_reuse'] = metrics
        return result
    started = perf_counter()
    folder.mkdir(parents=True, exist_ok=False)
    result = {'status':'unknown', 'attempts':[], 'model_calls':0, 'remote_model_calls':0,
              'tokens':0, 'cost_usd':0, 'reserved_usd':0, 'inference_ms':0,
              'false_fix':False, 'patch':entry['patch'], 'response':None,
              'candidate_reuse':{'hit':True, 'lookup_ms':lookup_ms, 'key':key,
                                 'origin_evidence':entry['origin_evidence'], 'verdict_reused':False}}
    try:
        workspace = folder/'input'
        for name, expected in identity['files'].items():
            data = safe_path(task.workspace.resolve(), name).read_bytes()
            if hash_bytes(data) != expected:
                raise ValueError('Source changed after cache lookup')
            path = workspace/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        frozen = task.model_copy(update={'workspace':workspace})
        original = {n:(workspace/n).read_text(encoding='utf-8') for n in task.source_files}
        if on_progress:
            on_progress({'stage':'Reused proposal: fresh full sandbox verification'})
        async with NebiusSandboxBackend() as box:
            await box.upload_project(workspace,task.source_files+task.support_files)
            applied = await box.apply_patch(entry['patch'],task.source_files)
            if not applied.success:
                raise ValueError('Cached canonical patch did not apply')
            for name in task.support_files:
                if hash_bytes((await box.read_file(name)).encode()) != identity['files'][name]:
                    raise ValueError('Protected file changed')
            candidate = {n:await box.read_file(n) for n in task.source_files}
            hooks = all(candidate[n].count('sched_yield(')==original[n].count('sched_yield(') for n in original)
            verification = await ConcurrencyVerifier(campaigns=campaign_factory(folder)).verify_workspace(frozen,box)
            raw = verification.model_dump(mode='json')
            (folder/'verification.json').write_text(json.dumps(raw,indent=2),encoding='utf-8')
            result.update(status='unknown' if verification.infrastructure_failures else ('verified' if verification.passed and hooks else 'rejected'),
                          verification_ms=verification.duration_ms,
                          verification={'build_passed':verification.build_passed,'original_tests_passed':raw.get('evidence',{}).get('original_tests',{}).get('passed'),
                                        'passed_runs':verification.passed_runs,'total_runs':verification.total_runs,
                                        'semantic_passed':verification.semantic_passed,'tsan_passed':verification.sanitizer_passed,
                                        'scheduling_hooks_preserved':hooks})
            if result['status']=='verified':
                require_verified(raw,identity['task']['verification_config'])
            else:
                result['candidate_reuse']['reverification_failed'] = True
    except Exception as exc:
        result.update(status='unknown',error=type(exc).__name__)
    finally:
        result['end_to_end_ms']=(perf_counter()-started)*1000+lookup_ms
        result['created_at']=datetime.now(timezone.utc).isoformat()
        (folder/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result
