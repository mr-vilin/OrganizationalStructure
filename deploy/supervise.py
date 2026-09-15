"""单应用容器的进程监督：任何必要子进程退出都停止整个实例。"""
from __future__ import annotations

import logging
import signal
import subprocess
import sys
import time
from collections.abc import Sequence

log = logging.getLogger(__name__)


def supervise(commands: Sequence[Sequence[str]], poll_interval: float = 0.5) -> int:
    children: list[subprocess.Popen] = []
    try:
        for command in commands:
            children.append(subprocess.Popen(command))
        while children:
            for child in children:
                code = child.poll()
                if code is not None:
                    log.error('必要子进程退出，退出码：%s', code)
                    return code if code > 0 else 1
            time.sleep(poll_interval)
        return 1
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        deadline = time.monotonic() + 10
        for child in children:
            if child.poll() is None:
                try:
                    child.wait(timeout=max(0.1, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait()


def main() -> int:
    def shutdown(_signum, _frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, shutdown)
    logging.basicConfig(level=logging.INFO)
    return supervise([
        [sys.executable, '-m', 'uvicorn', 'deploy.asgi:app', '--host', '0.0.0.0', '--port', '8000', '--no-access-log'],
        [sys.executable, '-m', 'app.sync.worker'],
        [sys.executable, '-m', 'app.feishu.listener'],
    ])


if __name__ == '__main__':
    raise SystemExit(main())
