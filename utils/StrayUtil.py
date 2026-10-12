import os
import subprocess
import sys
import threading

import pystray
import win32api
from PIL import Image
from injector import singleton, inject

from utils.ConfigUtil import ConfigUtil
from utils.GetProcessUtil import get_all_audio_sessions, get_all_window_processes
from utils.LoggerUtil import LoggerUtil
from utils.ResourceUtil import resource_path


def _manager_path():
    """在同目录里找进程管理器：优先 进程静音管理.exe，其次 muter_gui.py。"""
    if getattr(sys, 'frozen', False):
        base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name in ("后台静音助手.exe", "进程静音管理.exe"):
        exe = os.path.join(base, name)
        if os.path.exists(exe):
            return exe, base
    py = os.path.join(base, "muter_gui.py")
    if os.path.exists(py):
        return py, base
    return None, base


@singleton
class StrayUtil:
    @inject
    def __init__(self, config_util: ConfigUtil, logger_util: LoggerUtil, event: threading.Event):
        self.setup_msg = config_util.config["setting"]["setup_msg"]
        self.logger = logger_util.logger
        self.event = event

        name = "后台静音助手"
        menu = pystray.Menu(
            pystray.MenuItem("进程管理", self.open_manager, default=True),
            pystray.MenuItem("进程列表", self._save_process_list_to_txt),
            pystray.MenuItem("退出", self.exit_app)
        )
        icon = Image.open(resource_path("resource/mute.ico"))

        self.icon = pystray.Icon(name, icon, name, menu)

    def open_manager(self):
        """呼出进程管理器窗口（左键单击托盘图标也会调用它）。"""
        target, base = _manager_path()
        if target is None:
            win32api.MessageBox(
                0,
                "同目录下没有找到「进程静音管理.exe」或「muter_gui.py」。\n"
                "请把它们和本程序放在同一个文件夹里。",
                "进程管理器", 0x30
            )
            return
        try:
            if target.lower().endswith(".py"):
                pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                if not os.path.exists(pythonw):
                    pythonw = "pythonw.exe"
                subprocess.Popen([pythonw, target], cwd=base)
            else:
                subprocess.Popen([target], cwd=base)
            self.logger.info(f"Process manager launched: {target}")
        except Exception as exc:
            self.logger.info(f"Failed to launch process manager: {exc}")
            win32api.MessageBox(0, f"启动进程管理器失败：\n{exc}", "进程管理器", 0x30)

    def run_detached(self):
        def on_icon_ready(icon):
            if self.event.is_set():
                icon.stop()
                return
            icon.visible = True
            if self.setup_msg:
                icon.notify("程序启动成功，在系统托盘右键菜单中退出")
            threading.current_thread().setName("StrayRunCallbackThread")
            self.logger.info("Stray is running.")

        self.logger.info("Starting stray.")
        threading.Thread(target=self.icon.run, args=(on_icon_ready,), name="StrayThread", daemon=True).start()

    def _save_process_list_to_txt(self):
        filename = "process_name.txt"
        window_processes = get_all_window_processes()
        print(window_processes)
        audio_sessions = get_all_audio_sessions()
        with open(filename, 'w', encoding="utf-8") as file:
            if window_processes:
                file.write("当前在窗口管理器中注册的进程：\n窗口标题 - 进程名\n")
            else:
                file.write("当前在窗口管理器中没有进程，请先启动任意进程并打开窗口。")
            for process_name, window_title in window_processes:
                file.write(f"{window_title} - {process_name}\n")
            file.write("\n")
            if audio_sessions:
                file.write("当前在音量合成器中注册的进程：\n进程名\n")
            else:
                file.write("当前在音量合成器中没有进程，请先启动任意进程并播放声音。")
            for session in audio_sessions:
                process_name = session.Process.name()
                file.write(f"{process_name}\n")
        self.logger.info(f"Process list saved to {filename}.")
        os.startfile(filename)

    def exit_app(self):
        self.logger.info("Exiting by StrayUtil.")
        self.event.set()
        self.icon.stop()
