import logging
import os
import sys
from datetime import datetime

from injector import singleton, inject

from utils.ConfigUtil import ConfigUtil

LOG_PATH = "../logs/"


def get_log_dir():
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        exe_dir = os.path.dirname(sys.executable)
        return os.path.join(exe_dir, 'logs')
    else:
        # Running as script
        script_dir = os.path.dirname(os.path.abspath(__file__))
        main_dir = os.path.dirname(script_dir)
        return os.path.join(main_dir, 'logs')


@singleton
class LoggerUtil:
    logger = None

    @inject
    def __init__(self, config_util: ConfigUtil):
        self.max_log_files = config_util.config["setting"]["max_log_files"]

        self.log_dir = get_log_dir()
        self.logger = self._setup_logging()

        self._delete_old_log_files()

    def _setup_logging(self):
        logger = logging.getLogger()
        logger.setLevel(logging.INFO)
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(threadName)s - %(message)s")

        # 设置控制台日志输出
        # ★ 修复：打包成窗口程序（--noconsole）后 sys.stderr 是 None，
        #   StreamHandler.emit 会抛异常并走 logging.handleError；
        #   在没有 stderr 的环境里这会让日志链路整体不可靠（严重时后面的
        #   FileHandler 也拿不到记录，出问题时连日志都没有）。这里只在
        #   真的存在 stderr 时才挂控制台 handler。
        if sys.stderr is not None:
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

        if self.max_log_files > 0:
            os.makedirs(self.log_dir, exist_ok=True)
            log_file = os.path.join(self.log_dir, datetime.now().strftime("%Y%m%d%H%M%S") + ".log")
            file_handler = logging.FileHandler(log_file, encoding="utf-8")
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

        if not logger.handlers:
            logger.addHandler(logging.NullHandler())

        return logger

    def _delete_old_log_files(self):
        if self.max_log_files <= 0 or not os.path.exists(self.log_dir):
            return

        log_files = [f for f in os.listdir(self.log_dir) if f.endswith(".log")]
        log_files.sort()

        if len(log_files) > self.max_log_files:
            files_to_delete = log_files[:len(log_files) - self.max_log_files]
            for file_name in files_to_delete:
                file_path = os.path.join(self.log_dir, file_name)
                try:
                    os.remove(file_path)
                except OSError:
                    pass          # 文件被占用就跳过，下次启动再清
