"""真实 MySQL/MCP 的串行 smoke 入口：0 通过、1 硬失败、2 配置或环境不安全。"""
import argparse
import os
from pathlib import Path

from .cases import load_cases
from .fixtures import _validate_url, verify_test_database
from .report import write_report
from .runner import EvaluationRunner
from .smoke import conflict_hook, smoke_worker
from app.persistence.database import create_mysql_engine


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        # argparse 默认会回显不合法参数，其中可能包含连接凭据。
        raise ValueError('EVALUATION_ARGUMENTS_INVALID')


def _preflight(database_url):
    _validate_url(database_url)
    engine = create_mysql_engine(database_url)
    try:
        with engine.connect() as connection:
            verify_test_database(connection)
    finally:
        engine.dispose()


def run(argv=None, *, runner_factory=None):
    parser = _Parser(description='在专用 MySQL _test 库运行六个 scripted Agent smoke 用例。')
    parser.add_argument('--suite', choices=['smoke'], default='smoke')
    parser.add_argument('--case', action='append', dest='case_ids')
    parser.add_argument('--database-url', default=os.getenv('ORG_TEST_DATABASE_URL'))
    parser.add_argument('--output', type=Path, default=Path('.evaluation-reports'))
    try:
        options = parser.parse_args(argv)
        cases = load_cases(sorted((Path(__file__).resolve().parents[2] / 'tests/evaluation/cases').glob('*.yaml')))
        if options.case_ids:
            selected = set(options.case_ids)
            if not selected <= {case.case_id for case in cases}:
                raise ValueError('EVALUATION_CASE_UNKNOWN')
            cases = tuple(case for case in cases if case.case_id in selected)
        if not cases:
            raise ValueError('EVALUATION_CASE_REQUIRED')
        if runner_factory is None:
            _preflight(options.database_url)
        factory = runner_factory or EvaluationRunner
        runner = factory(worker=smoke_worker(), database_url=options.database_url, after_tool=conflict_hook())
        reports = runner.run_suite(cases)
        for report in reports:
            write_report(report, options.output)
            print(f'{report.case_id}: {"PASS" if report.hard_passed else "FAIL"}')
        unsafe = {'HARNESS_FAILED', 'CLEANUP_FAILED', 'SYSTEM_NOT_QUIET'}
        if any(unsafe.intersection(report.hard_failures) for report in reports):
            return 2
        return 0 if len(reports) == len(cases) and all(report.hard_passed for report in reports) else 1
    except SystemExit as error:
        return 0 if error.code == 0 else 2
    except Exception:
        print('EVALUATION_CONFIGURATION_OR_ENVIRONMENT_FAILED')
        return 2


if __name__ == '__main__':
    raise SystemExit(run())
