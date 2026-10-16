"""CI 使用通用 Python 模块入口，缺失测试库时须安全失败。"""
import os
from pathlib import Path
import subprocess
import sys


def test_evaluation_module_requires_explicit_test_database(tmp_path):
    root = Path(__file__).resolve().parents[2]
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(('ORG_', 'FEISHU_', 'LARK_', 'OPENAI_', 'ANTHROPIC_'))}
    environment['PYTHONPATH'] = str(root / 'backend')
    environment['PYTHONIOENCODING'] = 'utf-8'
    process = subprocess.run([sys.executable, '-m', 'app.evaluation.cli', '--suite', 'smoke',
                              '--output', str(tmp_path)], cwd=root / 'backend', env=environment,
                             capture_output=True, text=True, encoding='utf-8', timeout=20)
    assert process.returncode == 2
    assert process.stdout.strip() == 'EVALUATION_CONFIGURATION_OR_ENVIRONMENT_FAILED'
    assert not list(tmp_path.iterdir())
