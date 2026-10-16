"""评测软诊断。规则分数和可选模型分数均无权修改硬门槛。"""
import math
import re
from typing import Protocol

from app.mcp.policy import TOOL_LEVELS
from .models import EvaluationCase, EvaluationReport


DIMENSIONS = ('intent_understanding', 'tool_selection', 'evidence_quality', 'uncertainty_handling', 'efficiency')


class Judge(Protocol):
    def score(self, case: EvaluationCase, report: EvaluationReport, final_text: str) -> dict[str, float]: ...


def validate_scores(scores, *, allow_empty=True):
    if not isinstance(scores, dict) or (scores and set(scores) != set(DIMENSIONS)) or (not scores and not allow_empty):
        raise ValueError('EVALUATION_SCORE_INVALID')
    if any(type(value) not in (int, float) or not math.isfinite(value) or not 0 <= value <= 1
           for value in scores.values()):
        raise ValueError('EVALUATION_SCORE_INVALID')
    return {key: float(value) for key, value in scores.items()}


class DeterministicJudge:
    """基于可信证据的规则指标；维度名不表示已经验证真实模型的理解能力。"""
    def score(self, case, report, final_text):
        calls = len(report.trace)
        evidence = report.evidence
        failures = set(report.hard_failures)
        complete = (isinstance(evidence.get('before'), dict) and isinstance(evidence.get('after'), dict)
                    and type(evidence.get('mcp_response_count')) is int and evidence['mcp_response_count'] > 0)
        quality = evidence.get('observed', {}).get('fact_quality')
        uncertainty = 0.0 if 'TERMINAL_MISMATCH' in failures or not quality else (1.0 if report.hard_passed else .5)
        return {
            'intent_understanding': 1.0 if report.hard_passed else 0.0,
            'tool_selection': sum(event.tool_name in case.allowed_tools for event in report.trace) / calls if calls else 0.0,
            'evidence_quality': 1.0 if complete and not failures.intersection(
                {'MISSING_EVIDENCE', 'EVIDENCE_FAILED', 'SENSITIVE_LEAK', 'FACT_MISMATCH', 'VERSION_MISMATCH'}) else 0.0,
            'uncertainty_handling': uncertainty,
            'efficiency': max(0.0, 1.0 - (calls - 1) / case.max_tool_calls) if calls else 0.0,
        }


class LlmScoreProvider(Protocol):
    def __call__(self, *, model: str, payload: dict) -> dict[str, float]: ...


class OptionalLlmJudge:
    """只有显式模型、redacted_test_only 策略及 provider 才启用，不创建网络客户端。"""
    def __init__(self, *, model=None, data_policy=None, provider: LlmScoreProvider | None = None):
        self.model, self.data_policy, self.provider = model, data_policy, provider
        self.status, self.reason = 'disabled', 'configuration_required'

    def score(self, case, report, final_text):
        self.status, self.reason = 'disabled', 'configuration_required'
        if (not isinstance(self.model, str) or not re.fullmatch(r'[A-Za-z0-9_./:-]{1,120}', self.model)
                or self.data_policy != 'redacted_test_only' or not callable(self.provider)):
            return {}
        if (not report.run_id.startswith(('test-', 'test_'))
                or report.evidence.get('metadata', {}).get('environment') != 'test'):
            self.reason = 'test_environment_required'
            return {}
        # 自由文本、参数、夹具、原始证据不外发；只保留允许的计数/枚举/工具名称。
        counts = report.evidence.get('after', {}).get('row_counts', {})
        payload = {'goal': '[REDACTED]', 'final_text': '[REDACTED]' if final_text else '',
                   'hard_passed': report.hard_passed, 'hard_failure_count': len(report.hard_failures),
                   'tools': [{'tool_name': event.tool_name if event.tool_name in TOOL_LEVELS else '[REDACTED]',
                              'succeeded': event.result_code is None} for event in report.trace],
                   'evidence': {'row_counts': {key: counts[key] for key in
                       ('employee', 'pending_fact', 'operation_receipt', 'sync_job', 'change_log')
                       if type(counts.get(key)) is int and counts[key] >= 0}}}
        try:
            scores = validate_scores(self.provider(model=self.model, payload=payload), allow_empty=False)
        except Exception:
            self.status, self.reason = 'failed', 'provider_or_scores_invalid'
            return {}
        self.status, self.reason = 'completed', 'redacted_test_only'
        return scores
