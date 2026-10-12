import sys
import os
import faulthandler
import threading
import time

import pywintypes
import win32api
import win32con
from injector import Injector, singleton

from utils.LoggerUtil import LoggerUtil
from utils.PIDLockUtil import PIDLockUtil
from utils.ShutdownUtil import ShutdownUtil
from utils.StrayUtil import StrayUtil
from utils.ThreadUtil import ThreadUtil

SCANNER_THREAD_NAME = "BGScannerThread"
WATCHDOG_INTERVAL = 5.0


def configure(binder):
    binder.bind(threading.Event, scope=singleton)


def check_lock():
    cur_lock_util = injector.get(PIDLockUtil)
    if cur_lock_util.is_locked():
        logger.info("Application is already running.")
        logger.info('Duplicate instance rejected without dialog.')
        sys.exit(0)
    else:
        cur_lock_util.create_lock()
    return cur_lock_util


def start_scanner(thread_util):
    threading.Thread(
        target=thread_util.background_scanner,
        name=SCANNER_THREAD_NAME,
        daemon=True
    ).start()


def watch_scanner(thread_util, event, logger):
    """★ 看门狗：扫描线程万一还是死了（未知异常），5 秒内自动把它拉起来。

    以前的版本一旦扫描线程意外退出，进程表面还在（托盘图标正常、菜单能用），
    但实际上再也不会静音任何进程 —— 用户只能靠"游戏没被静音"才发现。
    """
    while not event.is_set():
        time.sleep(WATCHDOG_INTERVAL)
        if event.is_set():
            break
        alive = any(t.name == SCANNER_THREAD_NAME and t.is_alive()
                    for t in threading.enumerate())
        if not alive:
            logger.warning(f"{SCANNER_THREAD_NAME} is not alive, restarting it.")
            start_scanner(thread_util)


def main():
    stray_util = injector.get(StrayUtil)
    stray_util.run_detached()

    thread_util = injector.get(ThreadUtil)
    event = injector.get(threading.Event)

    start_scanner(thread_util)
    threading.Thread(
        target=watch_scanner,
        args=(thread_util, event, logger),
        name="ScannerWatchdogThread",
        daemon=True
    ).start()

    shutdown_util = injector.get(ShutdownUtil)
    try:
        shutdown_util.loop()
    finally:
        event.set()
        stray_util.exit_app()
        for thread in threading.enumerate():
            if thread.name == SCANNER_THREAD_NAME:
                thread.join()
        thread_util.join_workers()
        logger.info('All controlled sessions restored; graceful shutdown complete.')


if __name__ == '__main__':
    if getattr(sys, 'frozen', False):
        os.chdir(os.path.dirname(os.path.abspath(sys.executable)))
        if '--worker' not in sys.argv:
            from utils.SupervisorUtil import supervise
            supervise()
            sys.exit(0)
    injector = Injector(configure)

    logger = injector.get(LoggerUtil).logger
    os.makedirs('logs', exist_ok=True)
    fault_log = open(os.path.join('logs', 'native-crash.log'), 'a', encoding='utf-8')
    faulthandler.enable(file=fault_log, all_threads=True)
    lock_util = check_lock()

    logger.info("Starting main function.")
    try:
        main()
    except Exception:
        logger.exception('Main loop failed.')
        raise
    finally:
        lock_util.remove_lock()

# 打包用
print(pywintypes)
# pyinstaller -Fw --add-data "resource/;resource/" -i "resource/mute.ico" -n background_muter.exe main.py
