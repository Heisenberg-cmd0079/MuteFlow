import threading
import time

from comtypes import CoInitialize
from injector import Injector, singleton, inject

from utils.AudioUtil import AudioUtil
from utils.ConfigUtil import ConfigUtil
from utils.GetProcessUtil import get_all_audio_sessions
from utils.LoggerUtil import LoggerUtil
from utils.RecoveryUtil import journal


@singleton
class ThreadUtil:
    @inject
    def __init__(self, injector: Injector, config_util: ConfigUtil,
                 event: threading.Event, logger_util: LoggerUtil):
        self.injector = injector
        self.config_util = config_util
        self.event = event
        self.logger = logger_util.logger
        self.workers = []
        self.workers_lock = threading.Lock()
        self.recovered = False

    def join_workers(self):
        with self.workers_lock:
            workers = list(self.workers)
        for worker in workers:
            worker.join()

    def start_audio_control_threads(self):
        alive_process = [process.name for process in threading.enumerate() if process.is_alive()]

        # ★ 健壮性修复：枚举失败不再让整个扫描线程死掉
        try:
            sessions = get_all_audio_sessions()
            if not self.recovered:
                journal().recover(sessions, self.logger)
                self.recovered = True
        except Exception as exc:
            self.logger.warning(f"Enumerate audio sessions failed (will retry): {exc}")
            return

        for session in sessions:
            # ★ 每个会话单独兜底：开机时进程起落频繁，
            #   session.Process.name() / AudioUtil 构造都可能撞上"进程已退出"，
            #   以前这种异常会直接终结 BGScannerThread，导致静音功能永久失效。
            try:
                process = session.Process
                if process is None:
                    continue
                process_name = process.name()
                pid = session.ProcessId
                if self.event.is_set():
                    break
                if not self.config_util.has_process(process_name):
                    continue
                if str(pid) in alive_process:
                    continue
                self.logger.info(f"Found target process: {process_name} (PID: {pid})")
                audio_util = AudioUtil(session, self.config_util, self.event, self.logger)
                thread = threading.Thread(target=audio_util.loop, name=str(pid), daemon=True)
                with self.workers_lock:
                    self.workers = [t for t in self.workers if t.is_alive()]
                    self.workers.append(thread)
                    thread.start()
            except Exception as exc:
                pid_text = getattr(session, "ProcessId", "?")
                self.logger.warning(f"Skip audio session (PID {pid_text}): {exc}")
                continue

    def background_scanner(self):
        try:
            CoInitialize()
        except Exception as exc:
            self.logger.error(f"CoInitialize failed: {exc}")

        config = self.config_util.config
        bg_scan_interval = config["setting"]["bg_scan_interval"]
        self.logger.info(f"Starting with scan interval: {bg_scan_interval}s")

        # ★ 健壮性修复：以前这里是 `while True` 裸循环，任何一次迭代抛异常
        #   （开机首轮最常见）都会让扫描线程静默退出：进程还在、托盘还能用，
        #   但再也不会静音任何东西，日志里也看不到任何痕迹。
        #   现在单轮异常只记录并继续，扫描永不停止。
        while not self.event.is_set():
            try:
                self.config_util.reload_if_changed()
                self.start_audio_control_threads()
            except Exception as exc:
                self.logger.error(f"Scan round failed (will retry): {exc}", exc_info=True)
            self.event.wait(min(self.config_util.config['setting']['bg_scan_interval'], 1.0))
