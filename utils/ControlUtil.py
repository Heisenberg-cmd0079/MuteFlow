import win32api
import win32event

MUTEX_NAME = r'Local\AutoMuteBG.Controller.v3'
STOP_NAME = r'Local\AutoMuteBG.Stop.v3'

def is_running():
    try:
        handle = win32event.OpenMutex(0x100000, False, MUTEX_NAME)
        win32api.CloseHandle(handle)
        return True
    except Exception:
        return False

def request_stop():
    try:
        handle = win32event.OpenEvent(0x0002, False, STOP_NAME)
        try:
            win32event.SetEvent(handle)
        finally:
            win32api.CloseHandle(handle)
        return True
    except Exception:
        return False

def supervisor_running():
    try:
        handle = win32event.OpenMutex(0x100000, False, r'Local\AutoMuteBG.Supervisor.v3')
        win32api.CloseHandle(handle)
        return True
    except Exception:
        return False
