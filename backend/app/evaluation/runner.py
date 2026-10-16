"""串行评测控制器与可信调用计量；Worker 的自报 trace 永不作为证据。"""
from copy import deepcopy
from datetime import datetime, timezone
import threading
import time
from uuid import uuid4

from .assertions import assert_case_postconditions, assert_forbidden_effects, assert_trace_policy, _terminal
from .cases import validate_case
from .evidence import EvaluationEvidence, capture_worker_output, capture_mcp_response
from .models import AgentRun, AgentRunContext, EvaluationReport, ToolTraceEvent
from .worker import ScriptedWorkerAgent
from .report import diagnose_report


def _utc():
    return datetime.now(timezone.utc).isoformat()


class CallRejected(RuntimeError):
    pass


class RestrictedClient:
    """给 Worker 的窄 facade；不提供 SDK、fixture、快照或底层资源。"""
    __slots__ = ('__call',)
    def __init__(self, call): self.__call = call
    def call_tool(self, name, arguments=None): return self.__call(name, arguments or {})


class TrustedCalls:
    def __init__(self, harness, case, deadline, after_call=None):
        self.harness, self.case, self.deadline = harness, case, deadline
        self.after_call = after_call
        self.revoked = threading.Event()
        self.lock = threading.Lock()
        self.trace, self.proofs, self.failures = [], [], []

    def reject(self, code):
        self.revoked.set()
        self.failures.append(code)
        raise CallRejected(code)

    def call(self, name, arguments):
        # 同一运行串行执行工具，排队的调用仍重新核对绝对截止时间。
        with self.lock:
            if self.revoked.is_set(): self.reject('CLIENT_REVOKED')
            if time.monotonic() >= self.deadline: self.reject('WORKER_TIMEOUT')
            if name not in self.case.allowed_tools: self.reject('TOOL_FORBIDDEN')
            if len(self.trace) >= self.case.max_tool_calls: self.reject('TOOL_BUDGET_EXCEEDED')
            arguments = deepcopy(arguments)
            started = _utc()
            code, operation, result = 'MCP_CALL_FAILED', None, None
            try:
                result = self.harness.call_tool(name, arguments)
                body = result.structured_content
                valid = (isinstance(body, dict) and {'operation_id', 'data', 'observation', 'audit', 'error'} <= body.keys()
                         and isinstance(body['observation'], dict) and isinstance(body['audit'], dict)
                         and (body['operation_id'] is None or isinstance(body['operation_id'], str))
                         and (body['error'] is None or isinstance(body['error'], dict)
                              and isinstance(body['error'].get('code'), str)) and type(result.is_error) is bool)
                if valid:
                    error = body.get('error')
                    code = error.get('code') if isinstance(error, dict) else None
                    if result.is_error and code is None: code = 'MCP_CALL_FAILED'
                    operation = body.get('operation_id')
                else:
                    code = 'MCP_INVALID_RESPONSE'
            except Exception:
                self.failures.append('MCP_CALL_FAILED')
                self.revoked.set()
            event = ToolTraceEvent(len(self.trace)+1, name, arguments, code, operation, started, _utc())
            self.trace.append(event)
            if result is not None:
                self.proofs.append(capture_mcp_response(event, result.structured_content,
                    is_error=result.is_error, sensitive_values=self.harness.sensitive_values))
                if self.after_call is not None:
                    try:
                        self.after_call(name, deepcopy(arguments), deepcopy(result.structured_content))
                    except Exception:
                        self.reject('HARNESS_HOOK_FAILED')
            if code in {'MCP_CALL_FAILED', 'MCP_INVALID_RESPONSE', 'UPSTREAM_TIMEOUT',
                        'UPSTREAM_UNAVAILABLE', 'UPSTREAM_INVALID_RESPONSE', 'MCP_INTERNAL_ERROR'}:
                self.reject(code)
            if time.monotonic() >= self.deadline: self.reject('WORKER_TIMEOUT')
            if self.revoked.is_set(): self.reject('CLIENT_REVOKED')
            if result is None: raise CallRejected('MCP_CALL_FAILED')
            return deepcopy(result.structured_content)

    def quiesce(self, timeout):
        # 不 cancel Future；持锁意味着 SDK 调用及可信采集仍未真正结束。
        acquired = self.lock.acquire(timeout=max(0, timeout))
        if acquired: self.lock.release()
        return acquired


class EvaluationRunner:
    def __init__(self, worker=None, *, database_url=None, harness_factory=None,
                 actor_id='evaluation-ci', shutdown_timeout=5.0, after_tool=None, judge=None, llm_judge=None):
        if shutdown_timeout <= 0: raise ValueError('EVALUATION_SHUTDOWN_TIMEOUT_INVALID')
        if harness_factory is None:
            from .harness import SystemHarness
            if database_url is None: raise ValueError('EVALUATION_TEST_DATABASE_REQUIRED')
            harness_factory = lambda case, context: SystemHarness(database_url, case, context)
        self.worker = worker or ScriptedWorkerAgent()
        self.harness_factory, self.actor_id = harness_factory, actor_id
        if after_tool is not None and not callable(after_tool):
            raise ValueError('EVALUATION_AFTER_TOOL_HOOK_INVALID')
        self.after_tool = after_tool
        self.judge, self.llm_judge = judge, llm_judge
        self.shutdown_timeout = shutdown_timeout
        self._retained = None
        self._serial = threading.Lock()

    def run_case(self, case):
        with self._serial:
            if self._retained: raise RuntimeError('EVALUATION_RECOVERY_REQUIRED')
            return self._run_case(validate_case(case))

    def _run_case(self, case):
        context = AgentRunContext('test-' + uuid4().hex, case.case_id, self.actor_id, 'test')
        harness = self.harness_factory(case, context)
        deadline = time.monotonic() + case.timeout_seconds
        hook = None
        if self.after_tool is not None:
            hook = lambda name, arguments, result: self.after_tool(
                case, context, harness, name, arguments, result)
        calls = TrustedCalls(harness, case, deadline, after_call=hook)
        errors, result = [], []
        evidence = {'metadata': {'environment': 'test'}, 'execution': 'unconfirmed'}
        safe_final_text = ''
        safe_trace = ()
        before = None
        def execute():
            try:
                returned = self.worker.run(case.goal, RestrictedClient(calls.call), context)
                if not isinstance(returned, AgentRun):
                    errors.append('WORKER_INVALID_RESULT')
                else:
                    result.append(deepcopy(returned))
            except CallRejected:
                pass
            except Exception:
                errors.append('WORKER_FAILED')
        try:
            harness.open()
            before = harness.snapshot()
            thread = threading.Thread(target=execute, name='evaluation-agent', daemon=True)
            thread.start()
            thread.join(max(0, deadline - time.monotonic()))
            if thread.is_alive() or time.monotonic() >= deadline: errors.append('WORKER_TIMEOUT')
        except Exception:
            errors.append('HARNESS_FAILED')
        finally:
            calls.revoked.set()
            quiet = self._quiet(harness, calls)
            if not quiet:
                errors.append('SYSTEM_NOT_QUIET')
                self._retained = (harness, calls)
            else:
                try:
                    after = harness.snapshot() if before is not None else None
                    reported = result[0] if result and isinstance(result[0], AgentRun) else AgentRun('', (), {})
                    raw = AgentRun(reported.final_text, tuple(calls.trace), reported.terminal_observation)
                    captured = capture_worker_output(raw, sensitive_values=harness.sensitive_values)
                    # 自报轨迹不参与判定，但仍须扫描其中的实际泄露。
                    try:
                        claimed = capture_worker_output(reported, sensitive_values=harness.sensitive_values)
                        captured.sensitive_leak |= claimed.sensitive_leak
                    except Exception:
                        captured.sensitive_leak = True
                    safe_trace = captured.redacted_run.trace
                    safe_final_text = captured.redacted_run.final_text
                    if before is not None and after is not None:
                        observation = EvaluationEvidence(before, after, context, harness.fake_writes(), captured,
                                                         mcp_responses=tuple(calls.proofs))
                        failures = (assert_case_postconditions(case, observation)
                                    + assert_forbidden_effects(case, observation)
                                    + assert_trace_policy(case, raw.trace))
                        errors.extend(f.code for f in failures)
                        evidence.update(observation.summary())
                        evidence['observed'] = dict(zip(('execution', 'fact_quality'), _terminal(observation)))
                except Exception:
                    errors.append('EVIDENCE_FAILED')
                finally:
                    try:
                        harness.close()
                    except Exception:
                        errors.append('CLEANUP_FAILED')
                        self._retained = (harness, calls)
        errors.extend(calls.failures)
        errors = tuple(dict.fromkeys(errors))
        if errors:
            evidence['execution'] = 'unconfirmed'
        else:
            evidence.pop('execution', None)
        evidence['metadata']['runner_status'] = 'unconfirmed' if errors else 'completed'
        report = EvaluationReport(case.case_id, context.run_id, not errors, errors, {}, evidence, safe_trace)
        return diagnose_report(case, report, safe_final_text, judge=self.judge, llm_judge=self.llm_judge)

    def _quiet(self, harness, calls):
        deadline = time.monotonic() + self.shutdown_timeout
        try:
            if not calls.quiesce(self.shutdown_timeout): return False
            return harness.quiesce(max(0, deadline - time.monotonic()))
        except Exception:
            return False

    def recover(self):
        """仅在可证明系统工作已静止时释放本次资源；否则保留阻断。"""
        with self._serial:
            if self._retained is None: return True
            harness, calls = self._retained
            if not self._quiet(harness, calls): return False
            harness.close()
            self._retained = None
            return True

    def run_suite(self, cases):
        reports = []
        for case in cases:
            reports.append(self.run_case(case))
            if self._retained: break
        return reports
