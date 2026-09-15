"""验证应用子进程退出后，容器监督进程不会继续假装健康。"""
import subprocess
import sys
import unittest
from unittest.mock import patch

from deploy.supervise import supervise


class SupervisionTests(unittest.TestCase):
    def test_child_failure_stops_sibling_and_propagates_error(self):
        children = []
        actual_popen = subprocess.Popen

        def start(*args, **kwargs):
            process = actual_popen(*args, **kwargs)
            children.append(process)
            return process

        with patch('deploy.supervise.subprocess.Popen', side_effect=start):
            result = supervise([
                [sys.executable, '-c', 'import time; time.sleep(60)'],
                [sys.executable, '-c', 'raise SystemExit(7)'],
            ], poll_interval=0.02)
        self.assertEqual(result, 7)
        self.assertTrue(all(child.poll() is not None for child in children))

    def test_unexpected_clean_exit_is_failure(self):
        self.assertEqual(supervise([[sys.executable, '-c', 'pass']], poll_interval=0.02), 1)

    def test_startup_error_stops_already_started_child(self):
        children = []
        actual_popen = subprocess.Popen

        def start(*args, **kwargs):
            process = actual_popen(*args, **kwargs)
            children.append(process)
            return process

        with patch('deploy.supervise.subprocess.Popen', side_effect=start):
            with self.assertRaises(FileNotFoundError):
                supervise([
                    [sys.executable, '-c', 'import time; time.sleep(60)'],
                    ['organization-nonexistent-test-executable'],
                ], poll_interval=0.02)
        self.assertTrue(all(child.poll() is not None for child in children))


if __name__ == '__main__':
    unittest.main()
