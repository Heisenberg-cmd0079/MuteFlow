"""A frozen launcher restarts its worker only after abnormal termination."""
import os
import subprocess
import sys
import time
import win32api
import win32event

def supervise():
    handle = win32event.CreateMutex(None, False, r'Local\AutoMuteBG.Supervisor.v3')
    result = win32event.WaitForSingleObject(handle, 0)
    if result not in (win32event.WAIT_OBJECT_0, win32event.WAIT_ABANDONED):
        win32api.CloseHandle(handle)
        return
    try:
        failures = 0
        while True:
            env = dict(os.environ, PYINSTALLER_RESET_ENVIRONMENT='1')
            started = time.monotonic()
            child = subprocess.Popen([sys.executable, '--worker'], cwd=os.getcwd(), env=env)
            code = child.wait()
            if code == 0:
                return
            failures = 1 if time.monotonic() - started > 60 else failures + 1
            os.makedirs('logs', exist_ok=True)
            with open(os.path.join('logs', 'supervisor.log'), 'a', encoding='utf-8') as f:
                f.write(time.strftime('%Y-%m-%d %H:%M:%S') + f' worker exited {code}; failure {failures}\n')
            if failures >= 5:
                return
            time.sleep(min(failures, 5))
    finally:
        win32event.ReleaseMutex(handle)
        win32api.CloseHandle(handle)
