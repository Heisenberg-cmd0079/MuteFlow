import psutil
import win32gui
import win32process
from pycaw.utils import AudioUtilities


def get_all_audio_sessions():
    """枚举当前所有音频会话（已注册到音量合成器的进程）。

    ★ 健壮性修复：以前用列表推导 `session.Process is not None`，
    开机瞬间音量合成器里常有一批刚启动/刚退出的短命进程，
    pycaw 的 session.Process 内部是 psutil.Process(pid)，
    进程已退出时会抛 NoSuchProcess，导致整个枚举直接失败。
    现在改成逐个会话容错：单个会话异常只跳过它，不影响其余会话。
    """
    sessions = AudioUtilities.GetAllSessions()
    res = []
    for session in sessions:
        try:
            if session.Process is not None:
                res.append(session)
        except Exception:
            # 该会话对应的进程已经没了（或拿不到进程信息），跳过
            continue
    return res


def get_all_window_processes():
    window_processes = []
    ignore_list = ['TextInputHost.exe']  # 添加过滤列表

    def enum_window_callback(hwnd, _):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            try:
                p = psutil.Process(pid)
                process_name = p.name()
                if process_name not in ignore_list:
                    window_title = win32gui.GetWindowText(hwnd)
                    window_processes.append((process_name, window_title))
            except psutil.NoSuchProcess:
                pass
            except Exception:
                pass

    win32gui.EnumWindows(enum_window_callback, None)
    return window_processes
