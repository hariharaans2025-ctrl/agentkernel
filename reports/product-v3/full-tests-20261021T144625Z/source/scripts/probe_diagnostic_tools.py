import asyncio
import os
from pathlib import Path
from agentkernel.config import load_env_file
from agentkernel.concurrency.sandbox.nebius import NebiusSandboxBackend

async def main():
    load_env_file(Path('.env'))
    os.environ['AGENTKERNEL_SANDBOX_IMAGE'] = 'agentkernel-clang:20261003122908'
    staging = Path('reports/diagnostic-staging')
    staging.mkdir(exist_ok=True)
    async with NebiusSandboxBackend(temporary_parent=staging) as box:
        result = await box.run_command(['python3', '-c', 'import shutil; print({x:shutil.which(x) for x in ["gdb", "clang", "addr2line", "apt-get"]})'], timeout=10)
        print(result.stdout)

if __name__ == '__main__': asyncio.run(main())
