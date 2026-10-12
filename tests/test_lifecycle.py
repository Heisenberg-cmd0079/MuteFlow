import logging
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.PIDLockUtil import PIDLockUtil
from utils.ControlUtil import is_running, request_stop
from utils.ProcessUtil import ProcessUtil

class LifecycleTests(unittest.TestCase):
    def setUp(self):
        namespace = 'Local\\MuteFlow.Test.' + uuid.uuid4().hex
        self.mutex_name = namespace + '.Mutex'
        self.stop_name = namespace + '.Stop'
        for target, value in [('utils.PIDLockUtil.MUTEX_NAME', self.mutex_name),
                              ('utils.PIDLockUtil.STOP_NAME', self.stop_name),
                              ('utils.ControlUtil.MUTEX_NAME', self.mutex_name),
                              ('utils.ControlUtil.STOP_NAME', self.stop_name)]:
            p = patch(target, value)
            p.start()
            self.addCleanup(p.stop)
    def test_separate_process_duplicate_and_graceful_stop_event(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = PIDLockUtil(SimpleNamespace(logger=logging.getLogger('test')))
            lock.lockfile = os.path.join(folder, 'lock.json')
            self.assertFalse(lock.is_locked())
            lock.create_lock()
            try:
                script = '''
import logging
import os
import importlib
from types import SimpleNamespace
locks = importlib.import_module('utils.PIDLockUtil')
control = importlib.import_module('utils.ControlUtil')
locks.MUTEX_NAME = control.MUTEX_NAME = os.environ['MUTEFLOW_TEST_MUTEX']
locks.STOP_NAME = control.STOP_NAME = os.environ['MUTEFLOW_TEST_STOP']
from utils.PIDLockUtil import PIDLockUtil
from utils.ControlUtil import request_stop
lock = PIDLockUtil(SimpleNamespace(logger=logging.getLogger('test')))
assert lock.is_locked(), 'Duplicate must be refused'
assert request_stop(), 'Stop event must reach owner'
'''
                result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True,
                                        env=dict(os.environ, MUTEFLOW_TEST_MUTEX=self.mutex_name,
                                                 MUTEFLOW_TEST_STOP=self.stop_name))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(lock.stop_requested())
            finally:
                lock.remove_lock()
            self.assertFalse(is_running())
            self.assertFalse(os.path.exists(lock.lockfile))

    def test_stale_json_lock_does_not_prevent_start(self):
        with tempfile.TemporaryDirectory() as folder:
            lock = PIDLockUtil(SimpleNamespace(logger=logging.getLogger('test')))
            lock.lockfile = os.path.join(folder, 'lock.json')
            with open(lock.lockfile, 'w') as f: f.write('{"pid":999999,"exe":"old.exe","create_time":0}')
            self.assertFalse(lock.is_locked())
            lock.create_lock()
            lock.remove_lock()

    def test_windowless_child_follows_same_executable_foreground(self):
        child = SimpleNamespace(pid=20, exe=lambda: r'C:\Game\DRAPLINE.exe', name=lambda:'DRAPLINE.exe')
        main = SimpleNamespace(pid=10, exe=lambda: r'C:\Game\DRAPLINE.exe', name=lambda:'DRAPLINE.exe')
        other = SimpleNamespace(pid=30, exe=lambda: r'C:\Windows\explorer.exe', name=lambda:'explorer.exe')
        util = ProcessUtil(child)
        with patch('utils.ProcessUtil.psutil.Process', side_effect=lambda pid: {10:main,30:other}[pid]):
            with patch.object(util, 'foreground_pid', return_value=10):
                self.assertTrue(util.is_window_in_foreground())
            with patch.object(util, 'foreground_pid', return_value=30):
                self.assertFalse(util.is_window_in_foreground())
            with patch.object(util, 'foreground_pid', return_value=20):
                self.assertTrue(util.is_window_in_foreground())

if __name__ == '__main__': unittest.main(verbosity=2)
