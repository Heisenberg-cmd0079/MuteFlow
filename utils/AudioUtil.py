import threading
import time

from pycaw.utils import AudioSession

from utils.ConfigUtil import ConfigUtil
from utils.LoggerUtil import LoggerUtil
from utils.ProcessUtil import ProcessUtil
from utils.RecoveryUtil import journal


# 两个缓动公式
# Source: https://blog.csdn.net/songche123/article/details/102520760
def _ease_in_cubic(t, b, c, d):
    t /= d
    return c * t * t * t + b


def _ease_out_cubic(t, b, c, d):
    t = t / d - 1
    return c * (t * t * t + 1) + b


class AudioUtil:
    def __init__(self, session: AudioSession, config_util: ConfigUtil,
                 event: threading.Event, logger: LoggerUtil.logger):
        self.session = session
        self.config_util = config_util
        self.process_name = session.Process.name()
        self.raw_config = config_util.get_by_process(self.process_name)
        self.config = config_util.get_by_process(session.Process.name())
        self.event = event
        self.logger = logger

        self.process_util = ProcessUtil(session.Process)
        self.last_target_volume = None
        self.last_volume = None
        self.easing_thread = None
        self.stop_easing_thread = False

        # ★ 诊断线索：主进程开窗口、子进程放音频的游戏（如 DRAPLINE.exe），
        #   放音频的那个进程自己没有窗口，前台判定会按"同一 exe"归并处理。
        try:
            if not self.process_util.get_process_hwnd_list():
                self.logger.info(
                    f"PID {session.ProcessId} has no window of its own; "
                    f"foreground state is merged with the same executable.")
        except Exception:
            pass

        # 运行函数
        self._check_fg_volume()
        self.auto_fg_volume = self.config['fg_volume']
        journal().remember(self.session, self.config['fg_volume'])

    def stop_easing(self):
        self.stop_easing_thread = True
        if self.easing_thread is not None and self.easing_thread.is_alive():
            self.easing_thread.join()
        self.stop_easing_thread = False

    def refresh_config(self):
        if not self.config_util.has_process(self.process_name):
            return False
        updated = self.config_util.get_by_process(self.process_name)
        if updated != self.raw_config:
            self.stop_easing()
            self.raw_config = updated
            self.config = dict(updated)
            if self.config['fg_volume'] == 'auto':
                self.config['fg_volume'] = self.auto_fg_volume
            self.last_target_volume = None
            journal().remember(self.session, self.config['fg_volume'])
            self.logger.info('Updated active rule: %s', self.process_name)
        return True

    def _check_fg_volume(self):
        if self.config["fg_volume"] == "auto":
            self.config["fg_volume"] = self.session.SimpleAudioVolume.GetMasterVolume()
            # 意外退出的情况
            if self.config["fg_volume"] == self.config["bg_volume"]:
                self.config["fg_volume"] = 1
            self.logger.info(f"Change fg_volume to {self.config['fg_volume']}.")

    def set_volume(self, volume: float):
        def no_easing(cur_volume=volume):
            self.session.SimpleAudioVolume.SetMasterVolume(cur_volume, None)
            self.last_volume = cur_volume

        def easing(stop_easing_thread):
            f = _ease_in_cubic if self.last_volume < volume else _ease_out_cubic
            c = volume - self.last_volume
            this_last_volume = self.last_volume
            for i in range(self.config["easing"]["steps"]):
                if stop_easing_thread():
                    break
                cur_volume = f(i + 1, this_last_volume, c, self.config["easing"]["steps"])
                # print("sep:{:}, {:.2f} -> {:.2f}".format(i, self.last_volume, cur_volume))
                no_easing(cur_volume)
                time.sleep(self.config["easing"]["duration"] / self.config["easing"]["steps"])

        def stop_easing():
            if self.easing_thread is not None and self.easing_thread.is_alive():
                self.stop_easing_thread = True
                self.easing_thread.join()
                self.stop_easing_thread = False

        if self.last_target_volume != volume:
            self.last_target_volume = volume
            if self.config["easing"] is None or self.last_volume is None:
                no_easing()
            else:
                stop_easing()
                self.easing_thread = threading.Thread(
                    target=easing,
                    args=(lambda: self.stop_easing_thread,),
                    name="EasingThread",
                    daemon=True
                )
                self.easing_thread.start()

    def loop(self):
        self.logger.info("Starting loop.")
        # ★ 健壮性修复：单次音量操作失败（进程刚退出 / 音频会话被系统回收 /
        #   COM 临时报错）以前会直接终结本线程且不写任何日志。
        #   现在失败只记录，循环继续；退出时用 finally 保证恢复前台音量。
        try:
            while not self.event.is_set() and self.process_util.is_running():
                try:
                    if not self.refresh_config():
                        self.logger.info('Rule removed: %s; restoring volume', self.process_name)
                        break
                    if self.process_util.is_window_in_foreground():
                        self.set_volume(self.config["fg_volume"])
                    else:
                        self.set_volume(self.config["bg_volume"])
                except Exception as exc:
                    self.logger.warning(
                        f"Volume control failed (PID {self.session.ProcessId}): {exc}")
                self.event.wait(min(self.config["loop_interval"], 0.5))
        except Exception as exc:
            self.logger.error(
                f"Loop aborted (PID {self.session.ProcessId}): {exc}", exc_info=True)
        finally:
            self.stop_easing()
            try:
                self.session.SimpleAudioVolume.SetMasterVolume(self.config["fg_volume"], None)
                journal().forget(self.session)
            except Exception:
                pass
            self.logger.info("Exiting loop.")
