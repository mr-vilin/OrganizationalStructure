"""仅序列化 Runner 已公开的证据；不接收原始响应、快照或 Worker 对话。"""
from dataclasses import asdict
import json
import math
from pathlib import Path

from .models import EvaluationReport


def report_json(report: EvaluationReport) -> str:
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
           for v in report.soft_scores.values()):
        raise ValueError('EVALUATION_SCORE_INVALID')
    return json.dumps(asdict(report), ensure_ascii=False, indent=2, allow_nan=False)


def report_markdown(report: EvaluationReport) -> str:
    # 使用同一验证路径；公开证据以 JSON 代码块保持固定格式。
    value = json.loads(report_json(report))
    lines = [f'# 评测报告：{report.case_id}', '', f'运行：{report.run_id}', '',
             f'硬门槛：{"通过" if report.hard_passed else "失败"}', '',
             '失败代码：' + ('、'.join(report.hard_failures) or '无'), '',
             f'工具调用：{len(report.trace)} 次', '', '## 证据与诊断', '', '```json',
             json.dumps({'evidence': value['evidence'], 'soft_scores': value['soft_scores'],
                         'trace': value['trace']}, ensure_ascii=False, indent=2), '```', '']
    return '\n'.join(lines)


def write_report(report: EvaluationReport, directory: str | Path) -> tuple[Path, Path]:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    paths = (directory / (report.run_id + '.json'), directory / (report.run_id + '.md'))
    paths[0].write_text(report_json(report), encoding='utf-8')
    paths[1].write_text(report_markdown(report), encoding='utf-8')
    return paths
