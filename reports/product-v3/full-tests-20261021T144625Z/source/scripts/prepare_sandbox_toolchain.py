"""Prepare and probe Clang/TSan in Nebius only. No model inference or host changes."""
import asyncio
import json
from pathlib import Path
from datetime import datetime, timezone
from agentkernel.config import load_env_file
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend

ROOT = Path(__file__).resolve().parents[1]


async def main():
    load_env_file(ROOT / '.env')
    report = {'status': 'preparing', 'security_controls_changed': False}
    out = ROOT / 'reports/toolchain.json'
    async with NebiusSandboxBackend() as box:
        for command in (['apt-get','update'], ['apt-get','install','-y','--no-install-recommends','clang','libclang-rt-dev']):
            result = await box.run_command(command, timeout=110)
            if result.exit_code != 0 or result.timed_out:
                report.update(status='installation_failed', evidence=result.model_dump())
                out.write_text(json.dumps(report,indent=2),encoding='utf-8')
                return
        source = '#include <pthread.h>\nint x; void *f(void *p){ x++; return p;} int main(){pthread_t a,b;pthread_create(&a,0,f,0);pthread_create(&b,0,f,0);pthread_join(a,0);pthread_join(b,0);return 0;}\n'
        await box._upload({'/workspace/tsan_probe.c': source.encode()})
        build = await box.run_command(['clang','-pthread','-fsanitize=thread','-g','-O1','tsan_probe.c','-o','tsan_probe'],timeout=30)
        probe = await box.run_command(['./tsan_probe'],timeout=10,environment={'TSAN_OPTIONS':'halt_on_error=1:exitcode=66'}) if build.exit_code == 0 else None
        image = await box.image.tag_as('agentkernel-clang:' + datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S'))
        report.update(status='ready' if probe and 'ThreadSanitizer: data race' in probe.stderr else 'tsan_runtime_unavailable',
                      image=image.tag, build=build.model_dump(), probe=probe.model_dump() if probe else None)
        out.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps({'status':report['status'],'image':image.tag}),flush=True)


if __name__ == '__main__': asyncio.run(main())
