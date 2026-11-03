"""六个固定用例与真实 CLI smoke；没有 MySQL 时不冒充业务通过。"""
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from app.evaluation.cases import load_cases


CASES = Path(__file__).parent / 'cases'


def test_six_versioned_cases_have_independent_contracts():
    cases = load_cases(sorted(CASES.glob('*.yaml')))
    assert {case.case_id for case in cases} == {
        'ORG_AGENT_READ_PRIMARY_STORE', 'ORG_AGENT_READ_NOT_IN_STORE',
        'ORG_AGENT_APPLY_STORE', 'ORG_AGENT_SYNC_SUBTREE',
        'ORG_AGENT_VERSION_CONFLICT', 'ORG_AGENT_PERMISSION_SHRINK',
    }
    for case in cases:
        assert case.expected_state and case.forbidden_effects


def test_cli_missing_or_non_test_database_exits_two(monkeypatch, tmp_path, capsys):
    from app.evaluation.cli import run
    monkeypatch.delenv('ORG_TEST_DATABASE_URL', raising=False)
    assert run(['--suite', 'smoke', '--output', str(tmp_path)]) == 2
    secret_url = 'mysql+pymysql://synthetic:private-canary@127.0.0.1/production'
    assert run(['--suite', 'smoke', '--database-url', secret_url]) == 2
    assert 'private-canary' not in capsys.readouterr().out


def test_cli_exit_codes_and_case_selection_with_explicit_double(tmp_path):
    from app.evaluation.cli import run
    from app.evaluation.models import EvaluationReport
    seen = []
    class Runner:
        def run_suite(self, cases):
            seen.extend(case.case_id for case in cases)
            return [EvaluationReport(case.case_id, 'test-cli-double', True, (), {}, {}, ()) for case in cases]
    factory = lambda **kwargs: Runner()
    args = ['--case', 'ORG_AGENT_READ_PRIMARY_STORE', '--output', str(tmp_path)]
    assert run(args, runner_factory=factory) == 0
    assert seen == ['ORG_AGENT_READ_PRIMARY_STORE']
    class FailingRunner:
        def run_suite(self, cases):
            return [EvaluationReport(cases[0].case_id, 'test-cli-failed', False,
                                     ('FACT_MISMATCH',), {}, {}, ())]
    assert run(args, runner_factory=lambda **kwargs: FailingRunner()) == 1
    assert run(['--case', 'UNKNOWN_CASE'], runner_factory=factory) == 2


def test_real_mysql_smoke_six_cases_twice(tmp_path):
    from sqlalchemy import func, select
    from app.evaluation.cli import run
    from app.persistence.database import create_mysql_engine
    from app.persistence.models import Base, DatasetState, WorkerLease
    url = os.getenv('ORG_TEST_DATABASE_URL')
    if not url:
        pytest.skip('需要显式测试 MySQL')
    run_ids = set()
    for iteration in range(2):
        output = tmp_path / str(iteration)
        assert run(['--suite', 'smoke', '--database-url', url, '--output', str(output)]) == 0
        reports = [json.loads(path.read_text(encoding='utf-8')) for path in output.glob('test-*.json')]
        assert len(reports) == 6 and all(report['hard_passed'] for report in reports)
        assert all(report['evidence']['versions']['after']['data_version'] >= 1 for report in reports)
        assert all(report['run_id'] not in run_ids for report in reports)
        run_ids.update(report['run_id'] for report in reports)
        conflict = next(report for report in reports if report['case_id'] == 'ORG_AGENT_VERSION_CONFLICT')
        assert any(event['result_code'] == 'DATASET_CHANGED' for event in conflict['trace'])
        shrink = next(report for report in reports if report['case_id'] == 'ORG_AGENT_PERMISSION_SHRINK')
        assert shrink['evidence']['after']['row_counts']['pending_fact'] > 0
    engine = create_mysql_engine(url)
    try:
        with engine.connect() as connection:
            baseline = {'dataset_state': 1, 'worker_lease': 1, 'system_setting': 2, 'feishu_connection': 1}
            for table in Base.metadata.tables.values():
                assert connection.scalar(select(func.count()).select_from(table)) == baseline.get(table.name, 0)
            assert connection.execute(select(DatasetState.dataset_epoch, DatasetState.data_version)).one() == ('pending', 0)
            assert connection.scalar(select(WorkerLease.owner)) is None
    finally:
        engine.dispose()


@pytest.mark.parametrize('resource', ['children', 'users'])
def test_subtree_smoke_detects_lost_later_pages(resource, monkeypatch):
    from app.evaluation.fake_feishu import FakeFeishu
    from app.evaluation.runner import EvaluationRunner
    from app.evaluation.smoke import smoke_worker
    url = os.getenv('ORG_TEST_DATABASE_URL')
    if not url:
        pytest.skip('需要显式测试 MySQL')
    original = FakeFeishu.pages
    def first_page(self, name, **params):
        for index, page in enumerate(original(self, name, **params)):
            if name == resource and index > 0:
                return
            yield page
    monkeypatch.setattr(FakeFeishu, 'pages', first_page)
    case = next(case for case in load_cases(CASES.glob('*.yaml')) if case.case_id == 'ORG_AGENT_SYNC_SUBTREE')
    report = EvaluationRunner(smoke_worker(), database_url=url).run_case(case)
    assert not report.hard_passed and 'FACT_MISMATCH' in report.hard_failures


def test_apply_smoke_rejects_skipped_preview_even_when_business_write_succeeds():
    from app.evaluation.runner import EvaluationRunner
    from app.evaluation.smoke import _steps
    from app.evaluation.worker import ScriptedWorkerAgent
    url = os.getenv('ORG_TEST_DATABASE_URL')
    if not url:
        pytest.skip('需要显式测试 MySQL')
    worker = ScriptedWorkerAgent(lambda goal, context: [step for step in _steps(goal, context)
                                                      if step.tool_name != 'preview_store_changes'])
    case = next(case for case in load_cases(CASES.glob('*.yaml')) if case.case_id == 'ORG_AGENT_APPLY_STORE')
    report = EvaluationRunner(worker, database_url=url).run_case(case)
    assert not report.hard_passed and 'MISSING_EVIDENCE' in report.hard_failures
