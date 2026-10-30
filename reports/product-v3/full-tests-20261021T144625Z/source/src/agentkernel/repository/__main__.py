import argparse
from pathlib import Path
from .onboarding import create_plan


def main():
    parser = argparse.ArgumentParser(description='Plan repository onboarding without executing code or calling models')
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    try:
        plan = create_plan(args.root, args.config, args.out)
    except (ValueError, OSError):
        parser.exit(2, 'Onboarding rejected: check contract, paths, file limits and unused output directory.\n')
    print(f"Planned {plan['contract']['project']}: {len(plan['files'])} files, {plan['upload_bytes']} bytes. No execution or model calls.")
    print(args.out.resolve() / 'plan.json')


if __name__ == '__main__':
    main()
