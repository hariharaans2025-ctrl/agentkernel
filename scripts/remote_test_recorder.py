"""Pytest evidence recorder used inside the remote validation container."""
import json
from pathlib import Path

import pytest

COLLECTED = []
DESELECTED = []
REPORTS = []
COLLECTION_ERRORS = []


def pytest_addoption(parser):
    parser.addoption('--ak-report', required=True, help='Remote JSON evidence output path')


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    COLLECTED.extend({'nodeid': item.nodeid, 'markers': sorted({m.name for m in item.iter_markers()})} for item in items)


def pytest_deselected(items):
    DESELECTED.extend({'nodeid': item.nodeid, 'markers': sorted({m.name for m in item.iter_markers()})} for item in items)


def pytest_runtest_logreport(report):
    REPORTS.append({'nodeid': report.nodeid, 'phase': report.when, 'outcome': report.outcome,
        'duration_s': report.duration, 'details': str(report.longrepr) if report.failed or report.skipped else None})


def pytest_collectreport(report):
    if report.failed:
        COLLECTION_ERRORS.append({'nodeid': report.nodeid, 'details': str(report.longrepr)})


def pytest_sessionfinish(session, exitstatus):
    grouped = {}
    for row in REPORTS:
        grouped.setdefault(row['nodeid'], []).append(row)
    outcomes = []
    for nodeid, rows in grouped.items():
        failure = next((row for row in rows if row['outcome'] == 'failed'), None)
        skipped = next((row for row in rows if row['outcome'] == 'skipped'), None)
        if failure:
            kind = 'failed' if failure['phase'] == 'call' else 'error'
            details = failure['details']
        elif skipped:
            kind, details = 'skipped', skipped['details']
        elif any(row['phase'] == 'call' and row['outcome'] == 'passed' for row in rows):
            kind, details = 'passed', None
        else:
            kind, details = 'error', 'No completed call phase'
        outcomes.append({'nodeid': nodeid, 'outcome': kind,
            'duration_s': sum(row['duration_s'] for row in rows), 'details': details})
    data = {'exitstatus': int(exitstatus), 'collected': COLLECTED, 'deselected': DESELECTED,
        'collection_errors': COLLECTION_ERRORS, 'outcomes': outcomes, 'phase_reports': REPORTS}
    Path(session.config.getoption('--ak-report')).write_text(json.dumps(data, indent=2), encoding='utf-8')
