import json
import os
import tempfile
import psutil
import win32api
import win32event
from injector import singleton, inject
from utils.LoggerUtil import LoggerUtil
from utils.ControlUtil import MUTEX_NAME, STOP_NAME

@singleton
class PIDLockUtil:
    @inject
    def __init__(self, logger_util: LoggerUtil):
        self.logger = logger_util.logger
        self.lockfile = os.path.join(tempfile.gettempdir(), 'run.lock')
        self.mutex = None
        self.stop_handle = None
        self.owns_lock = False

    def is_locked(self):
        self.mutex = win32event.CreateMutex(None, False, MUTEX_NAME)
        result = win32event.WaitForSingleObject(self.mutex, 0)
        if result not in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
            return True
        self.owns_lock = True
        try:
            with open(self.lockfile, encoding='utf-8') as f:
                old = json.load(f)
            if isinstance(old, int) and old != os.getpid():
                process = psutil.Process(old)
                if 'muter' in process.name().lower():
                    self.remove_lock(remove_file=False)
                    return True
        except (OSError, ValueError, psutil.Error):
            pass
        return False

    def create_lock(self):
        process = psutil.Process()
        with open(self.lockfile, 'w', encoding='utf-8') as f:
            json.dump({'pid': process.pid, 'exe': process.exe(),
                       'create_time': process.create_time()}, f)
        self.stop_handle = win32event.CreateEvent(None, True, False, STOP_NAME)
        win32event.ResetEvent(self.stop_handle)
        self.logger.info('Lock acquired (PID, path and creation time recorded).')

    def stop_requested(self):
        return self.stop_handle is not None and win32event.WaitForSingleObject(self.stop_handle, 0) == win32event.WAIT_OBJECT_0

    def remove_lock(self, remove_file=True):
        if self.owns_lock:
            if remove_file:
                try:
                    os.remove(self.lockfile)
                except OSError:
                    pass
            win32event.ReleaseMutex(self.mutex)
            self.owns_lock = False
        for handle in (self.stop_handle, self.mutex):
            if handle is not None:
                win32api.CloseHandle(handle)
        self.stop_handle = self.mutex = None
        self.logger.info('Lock released.')
