"""Only recover sessions recorded by this tool, never every zero-volume app."""
import json
import os
import threading

class RecoveryUtil:
    def __init__(self, path='volume_recovery.json'):
        self.path = path
        self.lock = threading.RLock()
        try:
            with open(path, encoding='utf-8') as f:
                self.records = json.load(f)
        except FileNotFoundError:
            self.records = {}

    def save(self):
        temp = self.path + '.tmp'
        with open(temp, 'w', encoding='utf-8') as f:
            json.dump(self.records, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp, self.path)

    def remember(self, session, volume):
        with self.lock:
            self.records[session.InstanceIdentifier] = volume
            self.save()

    def forget(self, session):
        with self.lock:
            self.records.pop(session.InstanceIdentifier, None)
            self.save()

    def recover(self, sessions, logger):
        with self.lock:
            for session in sessions:
                try:
                    key = session.InstanceIdentifier
                    if key not in self.records:
                        continue
                    volume = self.records[key]
                    session.SimpleAudioVolume.SetMasterVolume(volume, None)
                    del self.records[key]
                    logger.info('Recovered previously controlled session PID %s to %s', session.ProcessId, volume)
                except Exception as exc:
                    logger.warning('Session recovery failed (will retry next startup): %s', exc)
            self.save()

_journal = None
def journal():
    global _journal
    if _journal is None:
        _journal = RecoveryUtil()
    return _journal
