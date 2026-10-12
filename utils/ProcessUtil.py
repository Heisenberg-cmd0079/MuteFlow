from typing import List

import psutil
import win32gui
import win32process


class ProcessUtil:
    """判断"目标进程所属的同一个应用"是否在前台。

    ★ 0.2.2 修复（"切回游戏还是没声音"）：
      旧实现只看 **进程自己的窗口句柄**，而且句柄列表在 AudioUtil 构造时
      就枚举缓存了一次：

          is_window_in_foreground() -> win32gui.GetForegroundWindow() in self.hwnd_list

      但很多游戏是「主进程开窗口 + 同目录子进程放音频」的结构。
      例如 DRAPLINE.exe：
        PID 65524  主进程，拥有窗口 "DRAPLINE"，但音频会话是 Inactive（不放声音）
        PID 94312  65524 的子进程，没有窗口，却是唯一 Active 的音频会话
      对 94312 来说 hwnd_list 永远是空列表 -> 永远判定为"后台"
      -> 音量被永久压到 bg_volume(0)，切回游戏也不会恢复。

      现在改为按 **同一个可执行文件路径** 归并成一个应用：
      前台窗口只要属于这个 exe 的任意一个进程（主进程或子进程），
      就算"应用在前台"。查询实时进行，不再缓存窗口句柄，
      因此也不会再受"窗口比音频会话晚创建"的影响。
    """

    def __init__(self, process: psutil.Process):
        self.process = process
        self.pid = process.pid
        self._exe_path = None
        self._image_name = None

    def is_running(self):
        try:
            return self.process.is_running()
        except Exception:
            return False

    # ---------------- 自身标识 ----------------
    def identity(self):
        """返回 (exe 路径, 进程名)，都转小写；读不到则为空串。"""
        if self._exe_path is None:
            try:
                self._exe_path = (self.process.exe() or "").lower()
            except Exception:
                self._exe_path = ""
            try:
                self._image_name = (self.process.name() or "").lower()
            except Exception:
                self._image_name = ""
        return self._exe_path, self._image_name

    def is_same_application(self, other_pid: int) -> bool:
        """other_pid 是否属于与本进程相同的应用（同一 exe 文件）。"""
        if not other_pid:
            return False
        if other_pid == self.pid:
            return True
        try:
            other = psutil.Process(other_pid)
        except Exception:
            return False

        my_exe, my_name = self.identity()
        try:
            other_exe = (other.exe() or "").lower()
        except Exception:
            other_exe = ""
        try:
            other_name = (other.name() or "").lower()
        except Exception:
            other_name = ""

        # 首选：可执行文件路径完全一致（最可靠，能区分同名不同版本）
        if my_exe and other_exe and my_exe == other_exe:
            return True
        # 兜底：路径不同（启动器 / venv 之类的 shim，进程会显示成另一个 exe）
        # 或路径读不到（提权进程）时，退回进程名比较 ——
        # 配置本身就是按进程名匹配的，这里保持同样的粒度，
        # 宁可"少静音一个"也不要"永久静音游戏"。
        return bool(my_name) and other_name == my_name

    # ---------------- 前台判定 ----------------
    @staticmethod
    def foreground_pid():
        hwnd = win32gui.GetForegroundWindow()
        if not hwnd:
            return None
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return pid or None
        except Exception:
            return None

    def is_window_in_foreground(self):
        fg_pid = self.foreground_pid()
        if fg_pid is None:
            return False
        return self.is_same_application(fg_pid)

    # ---------------- 兼容旧接口 ----------------
    def get_process_hwnd_list(self) -> List[int]:
        """实时枚举本进程的窗口句柄（不再缓存）。

        仅供诊断使用：主进程 + 子进程结构的游戏里，
        放音频的子进程这里会返回空列表，这是正常现象。
        """
        res: List[int] = []

        def callback(hwnd, _):
            try:
                _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
            except Exception:
                return
            if window_pid == self.pid:
                res.append(hwnd)

        try:
            win32gui.EnumWindows(callback, res)
        except Exception:
            pass
        return res
