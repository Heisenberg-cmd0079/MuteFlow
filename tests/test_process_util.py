# -*- coding: utf-8 -*-
"""前台判定回归测试。

覆盖 0.2.2 修复的 bug：主进程开窗口 + 同目录子进程放音频的游戏，
旧逻辑（只看自己的窗口）会让放音频的子进程永远被判成"后台"，永久静音。

运行：
  python tests/test_process_util.py
"""
import os
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psutil
import win32gui
import win32process

from utils.ProcessUtil import ProcessUtil


class FakeForeground(ProcessUtil):
    """把前台窗口 PID 固定成指定值，避免测试时真的抢占前台。"""

    def __init__(self, process, fg_pid):
        super().__init__(process)
        self._fg_pid = fg_pid

    def foreground_pid(self):
        return self._fg_pid


def drapline_family():
    """返回 (有窗口的 PID, 无窗口但放音频的 PID, 列表)，找不到返回 (None, None, [])。"""
    pids = []
    for p in psutil.process_iter(["pid", "name"]):
        try:
            if p.info["name"] and p.info["name"].lower() == "drapline.exe":
                pids.append(p.info["pid"])
        except Exception:
            continue
    if not pids:
        return None, None, []

    window_owner, windowless = None, []
    for pid in pids:
        has_window = False

        def cb(hwnd, _):
            nonlocal has_window
            _, wp = win32process.GetWindowThreadProcessId(hwnd)
            if wp == pid and win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                has_window = True

        win32gui.EnumWindows(cb, None)
        if has_window:
            window_owner = pid
        else:
            windowless.append(pid)

    if window_owner is None or not windowless:
        return window_owner, None, pids

    # 真正放音频的那个子进程
    audio_pid = None
    try:
        from pycaw.utils import AudioUtilities
        for s in AudioUtilities.GetAllSessions():
            try:
                if s.ProcessId in windowless and s.Process.name().lower() == "drapline.exe":
                    try:
                        state = s._ctl.GetState()
                    except Exception:
                        state = 1
                    if state == 1:
                        audio_pid = s.ProcessId
                        break
                    audio_pid = audio_pid or s.ProcessId
            except Exception:
                continue
    except Exception:
        pass
    return window_owner, (audio_pid or windowless[0]), pids


class TestSameApplication(unittest.TestCase):
    def test_same_exe_is_same_application(self):
        child = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"])
        try:
            time.sleep(1.5)
            me = ProcessUtil(psutil.Process(os.getpid()))
            self.assertTrue(me.is_same_application(child.pid),
                            "同一 python.exe 的父子进程应属同一应用")
            self.assertTrue(me.is_same_application(os.getpid()))
        finally:
            child.kill()
            child.wait()

    def test_other_exe_is_not_same_application(self):
        me = ProcessUtil(psutil.Process(os.getpid()))
        others = [p.pid for p in psutil.process_iter(["name"])
                  if p.info["name"] and p.info["name"].lower() == "explorer.exe"]
        if not others:
            self.skipTest("explorer.exe 未运行")
        self.assertFalse(me.is_same_application(others[0]),
                         "不同 exe 不应算同一应用")

    def test_dead_pid_is_not_same_application(self):
        me = ProcessUtil(psutil.Process(os.getpid()))
        self.assertFalse(me.is_same_application(999999))


class TestDrapLineRegression(unittest.TestCase):
    """真实场景回归：DRAPLINE.exe 主进程有窗口，放音频的是无窗口子进程。"""

    @classmethod
    def setUpClass(cls):
        cls.window_owner, cls.audio_pid, cls.pids = drapline_family()

    def setUp(self):
        if not self.window_owner or not self.audio_pid:
            self.skipTest("DRAPLINE.exe 未在运行（或没有窗口/音频会话）")

    def test_windowless_audio_process_follows_main_window(self):
        audio_proc = psutil.Process(self.audio_pid)
        util = FakeForeground(audio_proc, self.window_owner)

        # 放音频的子进程自己没有窗口 -> 旧逻辑必然判为后台（这就是 bug）
        self.assertEqual(util.get_process_hwnd_list(), [],
                         "该进程应确实没有自己的窗口")
        # 新逻辑：主进程窗口在前台 => 整个应用算前台 => 恢复音量
        self.assertTrue(util.is_window_in_foreground(),
                        "主进程窗口在前台时，无窗口的音频子进程必须判为前台")

    def test_other_foreground_is_background(self):
        audio_proc = psutil.Process(self.audio_pid)
        util = FakeForeground(audio_proc, self.window_owner)
        other = [p.pid for p in psutil.process_iter(["name"])
                 if p.info["name"] and p.info["name"].lower() == "explorer.exe"]
        if other:
            util._fg_pid = other[0]
            self.assertFalse(util.is_window_in_foreground(),
                             "别的程序在前台时，游戏应判为后台并静音")

    def test_own_pid_is_foreground(self):
        audio_proc = psutil.Process(self.audio_pid)
        util = FakeForeground(audio_proc, self.audio_pid)
        self.assertTrue(util.is_window_in_foreground())


if __name__ == "__main__":
    unittest.main(verbosity=2)
