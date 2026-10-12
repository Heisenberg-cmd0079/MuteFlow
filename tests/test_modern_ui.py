import hashlib
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch
import muter_gui as core
import yaml
from types import SimpleNamespace

CONFIG='''setting:
  bg_scan_interval: 1
  max_log_files: 3
  setup_msg: false
default:
  loop_interval: 0.2
  fg_volume: 1
  bg_volume: 0
  ignore: []
  easing: null
processes:
  Existing.exe:
    fg_volume: auto
    bg_volume: 0
    easing: null
'''

class ModernUITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=os.path.join(self.tmp.name,'config.yaml')
        with open(self.path,'w',encoding='utf-8') as f:f.write(CONFIG)
        self.patches=[patch.object(core,'CONFIG_PATH',self.path),patch.object(core,'BACKUP_DIR',os.path.join(self.tmp.name,'backups')),
                      patch.object(core,'SETTINGS_PATH',os.path.join(self.tmp.name,'settings.json')),
                      patch.object(core,'is_running',return_value=True),patch.object(core,'collect_processes',return_value=[])]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        self.root=tk.Tk(); self.root.withdraw(); self.app=core.App(self.root)
        self.addCleanup(self.app.close)
        self.app.proc_rows=[dict(name=n,pids=[1,2],titles=['Test'],mem=100,path='',system=False,has_window=True)
                            for n in ('Existing.exe','NewGame.exe','OtherGame.exe')]
        self.app.render_processes()
    def test_opening_and_navigation_do_not_change_config(self):
        with open(self.path,'rb') as f: before=f.read()
        for page in ('add','settings','rules'):self.app.show_page(page); self.root.update_idletasks()
        with open(self.path,'rb') as f:self.assertEqual(before,f.read())
    def test_selected_batch_add_and_remove_with_hot_apply(self):
        self.app.toggle_process('newgame.exe',True); self.app.toggle_process('othergame.exe',True)
        self.app.add_selected()
        with open(self.path,encoding='utf-8') as f: rules=yaml.safe_load(f)['processes']
        self.assertEqual(set(rules),{'Existing.exe','NewGame.exe','OtherGame.exe'})
        self.assertFalse(self.app.selected)
        self.app.remove_rules(['NewGame.exe','OtherGame.exe'],confirm=False)
        with open(self.path,encoding='utf-8') as f:self.assertEqual(list(yaml.safe_load(f)['processes']),['Existing.exe'])
    def test_invalid_edit_does_not_write_and_valid_edit_roundtrips(self):
        with open(self.path,'rb') as f:before=f.read()
        with self.assertRaises(ValueError):self.app.save_rule('Existing.exe','standard','auto','5')
        with open(self.path,'rb') as f:self.assertEqual(before,f.read())
        self.app.save_rule('Existing.exe','standard','0.8','0.2')
        self.assertEqual(self.app.rules['existing.exe'][0]['fg_volume'],.8)
        self.app.save_rule('Existing.exe','null','auto','0')
        self.assertTrue(self.app.rules['existing.exe'][1])
    def test_search_and_select_all_exclude_existing_rules(self):
        self.app.select_all_var.set(True); self.app.select_all_visible()
        self.assertEqual(self.app.selected,{'newgame.exe','othergame.exe'})
        self.app.search_var.set('NewGame')
        self.assertEqual([p['name'] for p in self.app.visible_processes()],['NewGame.exe'])
        self.app.rules_search.set('nothing')
        self.assertIn('找到 0 条',self.app.rule_count.cget('text'))

class ProcessEnumerationTests(unittest.TestCase):
    def test_visible_window_owner_missing_from_enumeration_is_resolved(self):
        proc=SimpleNamespace(pid=12345,as_dict=lambda *a,**k:dict(pid=12345,name='Game.exe',exe='',memory_info=None))
        with patch.object(core,'window_titles_by_pid',return_value={12345:['Game']}), \
             patch.object(core.psutil,'process_iter',return_value=[]), \
             patch.object(core.psutil,'Process',return_value=proc):
            rows=core.collect_processes()
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['name'],'Game.exe')
        self.assertTrue(rows[0]['has_window'])

if __name__=='__main__':unittest.main(verbosity=2)
