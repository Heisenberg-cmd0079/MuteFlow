import copy
import logging
import os
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yaml
from utils.ConfigUtil import ConfigUtil
from utils.AudioUtil import AudioUtil

class Volume:
    def __init__(self): self.value = .65
    def GetMasterVolume(self): return self.value
    def SetMasterVolume(self, value, _): self.value = value

class Process:
    def name(self): return 'Game.exe'

class Session:
    Process = Process()
    ProcessId = 123
    SimpleAudioVolume = None
    InstanceIdentifier = 'fake-session'

class ReloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, 'config.yaml')
        with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), 'resource', 'default_config.yaml')) as f:
            self.data = yaml.safe_load(f)
        self.data['default'].update(fg_volume='auto', easing=None)
        self.data['processes'] = {'Game.exe': None}
        self.write()
        self.cfg = ConfigUtil()
        self.cfg.config_file = self.path
        self.cfg._read()
        from utils.RecoveryUtil import RecoveryUtil
        self.recovery = RecoveryUtil(os.path.join(self.tmp.name, 'recovery.json'))
        self.jpatch = patch('utils.AudioUtil.journal', return_value=self.recovery)
        self.jpatch.start()
        self.addCleanup(self.jpatch.stop)

    def write(self):
        with open(self.path, 'w') as f: yaml.safe_dump(self.data, f)

    def audio(self):
        session = Session()
        session.SimpleAudioVolume = Volume()
        with patch('utils.AudioUtil.ProcessUtil') as util:
            util.return_value.get_process_hwnd_list.return_value = [1]
            return AudioUtil(session, self.cfg, threading.Event(), logging.getLogger('test'))

    def test_delete_restores_and_stops_existing_controller(self):
        audio = self.audio()
        audio.set_volume(0)
        self.data['processes'] = {}
        self.write()
        self.assertTrue(self.cfg.reload_if_changed())
        audio.loop()
        self.assertEqual(audio.session.SimpleAudioVolume.value, .65)

    def test_edit_updates_existing_controller_and_preserves_auto(self):
        audio = self.audio()
        audio.set_volume(0)
        self.data['processes']['Game.exe'] = {'bg_volume': .2}
        self.write()
        self.cfg.reload_if_changed()
        self.assertTrue(audio.refresh_config())
        self.assertEqual(audio.config['bg_volume'], .2)
        self.assertEqual(audio.config['fg_volume'], .65)

    def test_invalid_reload_keeps_last_good_and_file(self):
        before = copy.deepcopy(self.cfg.config)
        with open(self.path, 'w') as f: f.write('processes: [')
        self.assertFalse(self.cfg.reload_if_changed())
        self.assertEqual(before, self.cfg.config)
        with open(self.path) as f: self.assertEqual(f.read(), 'processes: [')

    def test_null_still_means_default(self):
        self.assertEqual(self.cfg.get_by_process('Game.exe')['fg_volume'], 'auto')

    def test_crash_recovery_restores_only_owned_sessions(self):
        audio = self.audio()
        audio.set_volume(0)
        other = Session()
        other.InstanceIdentifier = 'unmanaged-session'
        other.SimpleAudioVolume = Volume()
        other.SimpleAudioVolume.value = 0
        self.recovery.recover([audio.session, other], logging.getLogger('test'))
        self.assertEqual(audio.session.SimpleAudioVolume.value, .65)
        self.assertEqual(other.SimpleAudioVolume.value, 0)

    def test_graceful_stop_restores_even_with_easing(self):
        audio = self.audio()
        audio.config['easing'] = {'duration': .1, 'steps': 20}
        audio.set_volume(.4)
        audio.set_volume(0)
        audio.event.set()
        audio.loop()
        self.assertFalse(audio.easing_thread.is_alive())
        self.assertEqual(audio.session.SimpleAudioVolume.value, .65)

if __name__ == '__main__': unittest.main(verbosity=2)
