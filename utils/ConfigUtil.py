import copy
import os
import shutil
import hashlib
import logging
import threading

import yaml
from injector import singleton, inject

from utils.ResourceUtil import resource_path


@singleton
class ConfigUtil:
    config = None

    @inject
    def __init__(self):
        self.config_file = "config.yaml"
        self.default_config_path = resource_path("resource/default_config.yaml")
        self.config = None
        self.default_config = None
        self._mutex = threading.RLock()
        self._digest = None

        self._read()

    def _read(self):
        if not os.path.exists(self.config_file):
            shutil.copy2(self.default_config_path, self.config_file)
        with open(self.config_file, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)
        self._verify()
        self.validate(self.config)
        with open(self.config_file, 'rb') as f:
            self._digest = hashlib.sha256(f.read()).digest()

    def reload_if_changed(self):
        """Publish a fully validated snapshot; never reset a live user's file."""
        try:
            with open(self.config_file, 'rb') as f:
                raw = f.read()
            digest = hashlib.sha256(raw).digest()
            if digest == self._digest:
                return False
            candidate = yaml.safe_load(raw.decode('utf-8-sig'))
            self.validate(candidate)
            with self._mutex:
                self.config = candidate
                self._digest = digest
            logging.getLogger().info('Configuration reloaded: %s rules', len(candidate['processes']))
            return True
        except Exception as exc:
            logging.getLogger().warning('Configuration reload rejected; keeping last valid rules: %s', exc)
            return False

    def validate(self, config):
        if not isinstance(config, dict) or not isinstance(config.get('processes'), dict):
            raise ValueError('processes must be a mapping')
        def required(target, reference):
            if not isinstance(target, dict):
                raise ValueError('Configuration section must be a mapping')
            for key, value in reference.items():
                if key not in target:
                    raise ValueError('Missing setting: ' + key)
                if isinstance(value, dict) and target[key] is not None:
                    required(target[key], value)
        required(config.get('setting'), self.default_config['setting'])
        required(config.get('default'), self.default_config['default'])
        interval = config['setting']['bg_scan_interval']
        if not isinstance(interval, (int, float)) or not 0 < interval <= 60:
            raise ValueError('bg_scan_interval must be in (0, 60]')
        for name, override in [('default', None)] + list(config['processes'].items()):
            if override is not None and not isinstance(override, dict):
                raise ValueError('Invalid rule: ' + name)
            rule = copy.deepcopy(config['default'])
            if override:
                if not set(override).issubset(rule):
                    raise ValueError('Unknown rule setting: ' + name)
                for key, value in override.items():
                    if isinstance(value, dict) and isinstance(rule.get(key), dict):
                        rule[key].update(value)
                    else:
                        rule[key] = value
            for key in ('fg_volume', 'bg_volume'):
                value = rule[key]
                if key == 'fg_volume' and value == 'auto':
                    continue
                if not isinstance(value, (int, float)) or not 0 <= value <= 1:
                    raise ValueError('Invalid volume: ' + name)
            if not isinstance(rule['loop_interval'], (int, float)) or not 0 < rule['loop_interval'] <= 60:
                raise ValueError('Invalid loop_interval: ' + name)
            easing = rule['easing']
            if easing is not None and (not isinstance(easing, dict) or
                    not isinstance(easing.get('steps'), int) or easing['steps'] <= 0 or
                    not isinstance(easing.get('duration'), (int, float)) or easing['duration'] < 0):
                raise ValueError('Invalid easing: ' + name)

    def has_process(self, name):
        with self._mutex:
            return name in self.config['processes']

    def _verify(self):
        with open(self.default_config_path, "r", encoding="utf-8") as f:
            self.default_config = yaml.safe_load(f)
        try:
            self._verify_consistency(self.config["setting"], self.default_config["setting"])
            self._verify_consistency(self.config["default"], self.default_config["default"])
        except KeyError:
            self._reset()

    def _verify_consistency(self, target_config, reference_config):
        for key in reference_config:
            if key not in target_config:
                self._reset()
            if isinstance(reference_config[key], dict) and isinstance(target_config[key], dict):
                self._verify_consistency(target_config[key], reference_config[key])

    def _reset(self):
        if os.path.exists(self.config_file):
            shutil.move(self.config_file, "backup_" + self.config_file)
        shutil.copy2(self.default_config_path, self.config_file)
        raise CustomException(f"Configuration file verification failed. {self.config_file} has been reset. "
                              f"Please modify and run the program again.")

    def get_by_process(self, process_name):
        def merge_configs(parent_config, child_config):
            if not set(child_config.keys()).issubset(set(parent_config.keys())):
                raise CustomException(f"Process configuration error for {process_name}.", child_config)
            merged = parent_config.copy()
            for key, value in child_config.items():
                if key in merged and isinstance(value, dict) and isinstance(merged[key], dict):
                    merged[key] = merge_configs(merged[key], value)
                else:
                    merged[key] = value
            return merged

        with self._mutex:
            snapshot = self.config
        process_config = snapshot["processes"][process_name]
        # ★ 修复：以前这里直接返回 self.config["default"]（全局共享的同一个 dict），
        #   而 AudioUtil 会把 fg_volume="auto" 就地改写成实测音量，
        #   于是配置成 null 的进程会污染全局 default，影响其它进程的判定。
        #   现在一律返回深拷贝，互不影响。
        if process_config is None:
            return copy.deepcopy(snapshot["default"])
        default_config = copy.deepcopy(snapshot["default"])
        return merge_configs(default_config, process_config)


class CustomException(Exception):
    pass
