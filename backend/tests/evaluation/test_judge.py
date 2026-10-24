"""软诊断不覆盖硬门槛，外部模型仅接收允许的脱敏摘要。"""
from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from app.evaluation.cases import load_case
from app.evaluation.models import EvaluationReport, ToolTraceEvent


def inputs():
    case = load_case(Path(__file__).parent / 'cases/ORG_AGENT_READ_PRIMARY_STORE.yaml')
    report = EvaluationReport(case.case_id, 'test-judge', True, (), {}, {
        'metadata': {'environment': 'test'}, 'before': {'row_counts': {'employee': 1}},
        'after': {'row_counts': {'employee': 1, 'pending_fact': 0}}, 'mcp_response_count': 1,
        'observed': {'execution': 'verified', 'fact_quality': 'resolved'}},
        (ToolTraceEvent(1, 'get_employee', {}, None, None, '', ''),))
    return case, report


def test_deterministic_dimensions_are_bounded_and_missing_evidence_reduces_score():
    from app.evaluation.judge import DeterministicJudge, DIMENSIONS
    case, report = inputs()
    judge = DeterministicJudge()
    scores = judge.score(case, report, '[REDACTED]')
    assert set(scores) == set(DIMENSIONS)
    assert all(type(value) is float and 0 <= value <= 1 for value in scores.values())
    missing = replace(report, hard_passed=False, hard_failures=('MISSING_EVIDENCE',), evidence={})
    failed = judge.score(case, missing, '')
    assert failed['evidence_quality'] < scores['evidence_quality']
    assert failed['intent_understanding'] == 0


def test_honest_unknown_and_pending_are_recognized():
    from app.evaluation.judge import DeterministicJudge
    case, report = inputs()
    expected = {**case.expected_state, 'fact_quality': 'partial'}
    case = replace(case, expected_state=expected)
    report.evidence['observed'] = {'execution': 'partial', 'fact_quality': 'partial'}
    report.evidence['after']['row_counts']['pending_fact'] = 1
    score = DeterministicJudge().score(case, report, '[REDACTED]')
    assert score['uncertainty_handling'] == 1
    mismatch = replace(report, hard_passed=False, hard_failures=('TERMINAL_MISMATCH',))
    assert DeterministicJudge().score(case, mismatch, '')['uncertainty_handling'] == 0


@pytest.mark.parametrize('configuration', [{}, {'model': 'synthetic-model'},
    {'model': 'synthetic-model', 'data_policy': 'unrestricted'},
    {'data_policy': 'redacted_test_only'}])
def test_optional_provider_never_called_without_explicit_model_and_policy(configuration):
    from app.evaluation.judge import OptionalLlmJudge
    case, report = inputs()
    calls = []
    provider = lambda **kwargs: calls.append(kwargs)
    judge = OptionalLlmJudge(provider=provider, **configuration)
    assert judge.score(case, report, 'private-canary') == {}
    assert judge.status == 'disabled'
    assert calls == []


def test_optional_provider_receives_no_source_text_arguments_or_fixture():
    from app.evaluation.judge import OptionalLlmJudge, DIMENSIONS
    case, report = inputs()
    case = replace(case, goal='private-person password=private-canary a@private.example')
    report.evidence['raw'] = 'mysql+pymysql://private:private-canary@private/production'
    report = replace(report, trace=(replace(report.trace[0], arguments={'name': 'private-person'}),))
    calls = []
    def provider(**kwargs):
        calls.append(kwargs)
        return {key: .9 for key in DIMENSIONS}
    judge = OptionalLlmJudge(model='synthetic-model', data_policy='redacted_test_only', provider=provider)
    assert judge.score(case, report, 'private-person Bearer private-canary')
    material = json.dumps(calls, ensure_ascii=False)
    for secret in ('private-person', 'private-canary', 'private.example', 'mysql+', 'fixture', 'arguments'):
        assert secret not in material
    assert judge.status == 'completed'


@pytest.mark.parametrize('variant', ['exception', 'bad_scores', 'missing_dimension', 'production'])
def test_optional_failure_is_safe_and_never_changes_hard_gate(variant):
    from app.evaluation.judge import OptionalLlmJudge, DIMENSIONS
    from app.evaluation.report import diagnose_report, report_json
    case, report = inputs()
    report = replace(report, hard_passed=False, hard_failures=('FACT_MISMATCH',))
    calls = []
    def provider(**kwargs):
        calls.append(kwargs)
        if variant == 'exception':
            raise RuntimeError('Bearer private-canary')
        scores = {key: 1.0 for key in DIMENSIONS}
        if variant == 'bad_scores':
            scores['efficiency'] = float('nan')
        if variant == 'missing_dimension':
            del scores['efficiency']
        return scores
    if variant == 'production':
        report.evidence['metadata']['environment'] = 'production'
    judge = OptionalLlmJudge(model='synthetic-model', data_policy='redacted_test_only', provider=provider)
    result = diagnose_report(case, report, '[REDACTED]', llm_judge=judge)
    assert not result.hard_passed and result.hard_failures == ('FACT_MISMATCH',)
    assert result.evidence['metadata']['llm_judge']['status'] in {'disabled', 'failed'}
    assert 'private-canary' not in report_json(result)
    if variant == 'production':
        assert not calls


def test_even_high_llm_scores_do_not_make_failed_report_pass():
    from app.evaluation.judge import OptionalLlmJudge, DIMENSIONS
    from app.evaluation.report import diagnose_report, report_markdown
    case, report = inputs()
    failed = replace(report, hard_passed=False, hard_failures=('FACT_MISMATCH',))
    judge = OptionalLlmJudge(model='synthetic-model', data_policy='redacted_test_only',
        provider=lambda **kwargs: {key: 1.0 for key in DIMENSIONS})
    result = diagnose_report(case, failed, '', llm_judge=judge)
    assert not result.hard_passed
    assert '硬门槛：失败' in report_markdown(result)
    assert result.evidence['metadata']['llm_judge']['scores']['efficiency'] == 1


def test_no_implicit_provider_and_rule_judge_failure_remain_diagnostic():
    from app.evaluation.judge import OptionalLlmJudge
    from app.evaluation.report import diagnose_report
    case, report = inputs()
    optional = OptionalLlmJudge(model='synthetic-model', data_policy='redacted_test_only')
    assert optional.score(case, report, '') == {} and optional.status == 'disabled'
    class BrokenJudge:
        def score(self, *args):
            raise RuntimeError('private-canary')
    result = diagnose_report(case, report, '', judge=BrokenJudge())
    assert result.hard_passed and result.soft_scores == {}
    assert result.evidence['metadata']['judge'] == 'failed'
    assert result.evidence['metadata']['llm_judge']['status'] == 'disabled'


def test_real_mcp_runner_attaches_diagnostics_without_model_configuration():
    from app.evaluation.judge import DIMENSIONS
    from app.evaluation.runner import EvaluationRunner
    url = os.getenv('ORG_TEST_DATABASE_URL')
    if not url:
        pytest.skip('需要显式测试 MySQL')
    case, _ = inputs()
    report = EvaluationRunner(database_url=url).run_case(case)
    assert report.hard_passed and report.hard_failures == ()
    assert set(report.soft_scores) == set(DIMENSIONS)
    assert all(0 <= value <= 1 for value in report.soft_scores.values())
    assert report.evidence['metadata']['judge'] == 'completed'
    assert report.evidence['metadata']['llm_judge'] == {'status': 'disabled', 'scores': {}}
