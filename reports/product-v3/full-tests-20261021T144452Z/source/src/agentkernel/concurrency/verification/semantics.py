"""Trusted, immutable harnesses; no model-generated commands are executed."""
async def check_semantics(task, sandbox):
    checks = []
    for spec in task.verification_config.semantic_checks:
        build = await sandbox.run_command(spec.build_command, timeout=task.compile_timeout_seconds, environment=task.environment)
        build_ok = build.exit_code == 0 and not build.timed_out and not build.metadata.get('error')
        run = await sandbox.run_command(spec.run_command, timeout=task.max_runtime_seconds, environment=task.environment) if build_ok else None
        infrastructure = bool(build.metadata.get('error') or (run and run.metadata.get('error')))
        passed = bool(build_ok and run and run.exit_code == 0 and not run.timed_out and spec.expected_stdout in run.stdout and not infrastructure)
        checks.append({'name': spec.name, 'required': spec.required, 'passed': passed,
                       'infrastructure_failure': infrastructure, 'build': build.model_dump(),
                       'run': run.model_dump() if run else None})
        if build.metadata.get('execution_policy_blocked') or (run and run.metadata.get('execution_policy_blocked')):
            break
    required = [c for c in checks if c['required']]
    return {'configured': bool(task.verification_config.semantic_checks),
            'passed': all(c['passed'] for c in required) if required else None,
            'required_passed': len(checks) == len(task.verification_config.semantic_checks) and all(c['passed'] for c in required),
            'regression': any(not c['passed'] and not c['infrastructure_failure'] and c['required'] for c in checks),
            'infrastructure_failures': sum(c['infrastructure_failure'] for c in checks), 'checks': checks}
