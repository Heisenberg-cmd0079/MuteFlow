#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
后台静音工具 · 配置管理器（GUI）

解决痛点：以前添加一个进程要「打开 yaml + 任务管理器找 exe 名 + 手写配置」。
现在：打开本工具 → 列表里勾选正在运行的进程 → 点一下就写进 config.yaml。

用法：
    双击「进程静音管理.bat」，或   pythonw muter_gui.py
自检：
    python muter_gui.py --selftest
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import os
import re
import shutil
import subprocess
import sys
import winreg
import time
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

from datetime import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None


# --------------------------------------------------------------------------- #
# 路径与常量
# --------------------------------------------------------------------------- #
def enable_dpi_awareness() -> None:
    """必须在创建 Tk 窗口之前调用，否则高 DPI 屏幕上界面会糊/尺寸失控。"""
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def activate_existing_window() -> bool:
    """已经有一个管理器窗口时，把它唤到前台（托盘菜单点「进程管理」不该开出第二个）。"""
    try:
        import win32con
        import win32gui
    except ImportError:
        return False
    try:
        hwnd = win32gui.FindWindow(None, WINDOW_TITLE)
        if not hwnd:
            return False
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        else:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        try:
            win32gui.SetForegroundWindow(hwnd)
        except Exception:
            pass
        return True
    except Exception:
        return False


def _app_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _app_dir()
CONFIG_PATH = os.path.join(APP_DIR, "config.yaml")
BACKUP_DIR = os.path.join(APP_DIR, "config_backups")
SETTINGS_PATH = os.path.join(APP_DIR, "muter_gui_settings.json")
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_VALUE = "BackgroundMuter"
STARTUP_DIR = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")),
                           r"Microsoft\Windows\Start Menu\Programs\Startup")
AUTOSTART_LNK = os.path.join(STARTUP_DIR, "静音工具.lnk")
MANUAL_HINT = "手动输入进程名（例如 SomeGame.exe）"
WINDOW_TITLE = "后台静音助手"

DEFAULT_SETTINGS = {    "auto_start_muter": True,     # 打开管理器时自动把静音工具带起来
    "restart_after_add": True,    # 写入配置后重启静音工具
    "template": "standard",
    "filter_mode": "window",
    "auto_refresh": False,
}


def load_settings() -> dict:
    s = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            s.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    except Exception:
        pass
    return s


def save_settings(data: dict) -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def boot_autostart_exe() -> str:
    """读取启动文件夹里那个自启快捷方式指向的目标（没有则空串）。"""
    if not os.path.exists(AUTOSTART_LNK):
        return ""
    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        return str(shell.CreateShortcut(AUTOSTART_LNK).TargetPath or "")
    except Exception:
        return ""


def set_boot_autostart(exe: str | None) -> bool:
    """开关开机自启（exe 为 None 时关闭）。

    用「启动文件夹里的快捷方式」而不是注册表 Run，原因很重要：
    这个程序是按 **工作目录** 去找 config.yaml 的，
    而注册表 Run 启动它时工作目录是 System32 —— 会读不到自己的配置，
    然后在那里重新生成一份默认配置，你的规则就全不生效了。
    快捷方式里写好「起始位置」，就能保证工作目录 = 程序所在目录。
    """
    # 顺手清理早期版本可能留下的注册表启动项
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            try:
                winreg.DeleteValue(k, RUN_VALUE)
            except FileNotFoundError:
                pass
    except Exception:
        pass

    try:
        import win32com.client
        shell = win32com.client.Dispatch("WScript.Shell")
        if not exe:
            if os.path.exists(AUTOSTART_LNK):
                os.remove(AUTOSTART_LNK)
            return True
        os.makedirs(STARTUP_DIR, exist_ok=True)
        sc = shell.CreateShortcut(AUTOSTART_LNK)
        sc.TargetPath = exe
        sc.WorkingDirectory = os.path.dirname(exe)     # ★ 关键
        sc.IconLocation = f"{exe},0"
        sc.Description = "后台静音工具（开机自动启动）"
        sc.WindowStyle = 1
        sc.Save()
        return os.path.exists(AUTOSTART_LNK)
    except Exception:
        return False

TEMPLATE_STANDARD = {
    "mode": "standard",
    "fg_volume": "auto",
    "bg_volume": "0",
    "easing": "null",
}
TEMPLATE_DEFAULT = {"mode": "null"}


def find_muter_exe() -> str | None:
    """在当前目录里找 background_muter*.exe（排除本工具自身）。"""
    try:
        names = os.listdir(APP_DIR)
    except OSError:
        return None
    cands = [n for n in names if n.lower().endswith(".exe") and "muter" in n.lower()]
    if not cands:
        cands = [n for n in names if n.lower().endswith(".exe")]
    if not cands:
        return None
    cands.sort(key=lambda n: (0 if "muter" in n.lower() else 1, len(n)))
    return os.path.join(APP_DIR, cands[0])


# --------------------------------------------------------------------------- #
# config.yaml 文本级读写（保留原有格式、注释、空行，只动 processes 段）
# --------------------------------------------------------------------------- #
class Entry:
    __slots__ = ("name", "start", "end", "inline", "body")

    def __init__(self, name: str, start: int, inline: str = ""):
        self.name = name
        self.start = start          # 该条目首行在 lines 中的下标
        self.end = start + 1        # 该条目结束（不含）行下标
        self.inline = inline        # 形如 "  StarRail.exe: null" 里的 null
        self.body = []              # 缩进更深的行（原始文本）

    def summary(self) -> str:
        if self.inline:
            return "null（使用 default 设置）" if self.inline == "null" else self.inline
        text = "\n".join(self.body)
        fg = re.search(r"fg_volume\s*:\s*([^#\n]+)", text)
        bg = re.search(r"bg_volume\s*:\s*([^#\n]+)", text)
        ea = re.search(r"easing\s*:\s*([^#\n]+)", text)
        parts = []
        if fg:
            parts.append(f"前台 {fg.group(1).strip()}")
        if bg:
            parts.append(f"后台 {bg.group(1).strip()}")
        if ea:
            parts.append(f"easing {ea.group(1).strip()}")
        return " / ".join(parts) if parts else "（自定义）"

    def render(self, newline: str = "\n") -> str:
        if self.inline:
            return f"  {self.name}: {self.inline}"
        body = self.body if self.body else ["    fg_volume: auto", "", "    bg_volume: 0", "", "    easing: null"]
        return "\n".join([f"  {self.name}:"] + body)


class ConfigDoc:
    """极简 YAML 片段管理：只解析 processes 段，其余内容原样保留。"""

    def __init__(self, path: str):
        self.path = path
        self.bom = False
        self.newline = "\n"
        self.lines: list[str] = []
        self.proc_start: int | None = None
        self.proc_end: int | None = None
        self.entries: list[Entry] = []
        self.exists = os.path.exists(path)
        self.load()

    # -- 读 ---------------------------------------------------------------- #
    def load(self) -> None:
        if not self.exists:
            self.lines = ["default:", "  loop_interval: 0.2", "  fg_volume: 1",
                          "  bg_volume: 0", "  easing:", "    duration: 0.5",
                          "    steps: 50", "", "processes:", ""]
            self._parse()
            return
        with open(self.path, "rb") as f:
            data = f.read()
        if data.startswith(b"\xef\xbb\xbf"):
            self.bom = True
            data = data[3:]
        text = data.decode("utf-8", errors="replace")
        self.newline = "\r\n" if "\r\n" in text else "\n"
        self.lines = text.replace("\r\n", "\n").split("\n")
        self._parse()

    def _parse(self) -> None:
        lines = self.lines
        self.entries = []
        self.proc_start = None
        self.proc_end = None
        for i, ln in enumerate(lines):
            if re.match(r"^processes\s*:\s*$", ln):
                self.proc_start = i
                break
        if self.proc_start is None:                       # 没有 processes 段
            self.proc_start = len(lines)
            self.proc_end = len(lines)
            return
        end = len(lines)
        for i in range(self.proc_start + 1, len(lines)):
            ln = lines[i]
            if not ln.strip() or ln.lstrip().startswith("#"):
                continue
            if not ln[0].isspace():                       # 下一个顶层键
                end = i
                break
        self.proc_end = end

        base = None
        cur = None
        for i in range(self.proc_start + 1, end):
            ln = lines[i]
            if not ln.strip():
                continue
            indent = len(ln) - len(ln.lstrip())
            m = re.match(r"^\s*([^#\s][^:]*?)\s*:\s*(.*)$", ln)
            if m and (base is None or indent == base):
                if base is None:
                    base = indent
                if cur is not None:
                    cur.end = i
                name = m.group(1).strip().strip('"').strip("'")
                cur = Entry(name, i, m.group(2).strip())
                self.entries.append(cur)
            elif cur is not None:
                cur.body.append(ln)
        if cur is not None:
            cur.end = end

    # -- 查 ---------------------------------------------------------------- #
    def names_lower(self) -> set[str]:
        return {e.name.lower() for e in self.entries}

    def find(self, name: str) -> Entry | None:
        low = name.lower()
        for e in self.entries:
            if e.name.lower() == low:
                return e
        return None

    # -- 写 ---------------------------------------------------------------- #
    def _ensure_section(self) -> None:
        if self.proc_start is None or self.proc_start >= len(self.lines):
            if self.lines and self.lines[-1].strip():
                self.lines.append("")
            self.lines.append("processes:")
            self.lines.append("")
            self._parse()

    def _block_lines(self, entry: Entry) -> list[str]:
        """把条目渲染成行（末尾带一个空行做分隔）。"""
        out = []
        for ln in entry.render(self.newline).split("\n"):
            out.append(ln)
        out.append("")
        return out

    def _commit(self) -> None:
        text = "\n".join(self.lines)
        data = text.encode("utf-8")
        if self.bom:
            data = b"\xef\xbb\xbf" + data
        if self.newline == "\r\n":
            data = data.replace(b"\n", b"\r\n")
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        temp_path = self.path + ".tmp"
        with open(temp_path, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, self.path)
        self.exists = True
        self.load()

    def backup(self) -> str | None:
        if not os.path.exists(self.path):
            return None
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = os.path.join(BACKUP_DIR, f"config_{stamp}.yaml")
        shutil.copy2(self.path, dst)
        return dst

    def add(self, name: str, template: dict) -> bool:
        """新增条目；已存在返回 False。"""
        self._ensure_section()
        if self.find(name) is not None:
            return False
        e = Entry(name, 0)
        if template.get("mode") == "null":
            e.inline = "null"
        else:
            e.body = [
                f"    fg_volume: {template.get('fg_volume', 'auto')}",
                "",
                f"    bg_volume: {template.get('bg_volume', '0')}",
                "",
                f"    easing: {template.get('easing', 'null')}",
            ]
        insert_at = self.proc_end if self.proc_end is not None else len(self.lines)
        block = self._block_lines(e)
        if insert_at > 0 and self.lines[insert_at - 1].strip():
            block.insert(0, "")          # 和上一条之间留个空行，跟手写的配置风格一致
        self.lines[insert_at:insert_at] = block
        self._commit()
        return True

    def remove(self, names: list[str]) -> int:
        """删除若干条目。"""
        lows = {n.lower() for n in names}
        targets = [e for e in self.entries if e.name.lower() in lows]
        if not targets:
            return 0
        # 按行号倒序删除，避免下标错乱
        for e in sorted(targets, key=lambda x: x.start, reverse=True):
            del self.lines[e.start:e.end]
        self._commit()
        return len(targets)

    def rename(self, old: str, new: str) -> bool:
        """只改名字，保留原有参数（用于修正大小写）。"""
        e = self.find(old)
        if e is None:
            return False
        other = self.find(new)
        if other is not None and other is not e:
            return False
        line = self.lines[e.start]
        indent = len(line) - len(line.lstrip())
        self.lines[e.start] = line[:indent] + f"{new}:" + (f" {e.inline}" if e.inline else "")
        self._commit()
        return True

    def duplicates(self) -> list[str]:
        seen, dup = set(), []
        for e in self.entries:
            low = e.name.lower()
            if low in seen:
                dup.append(e.name)
            seen.add(low)
        return dup

    def update(self, name: str, template: dict) -> bool:
        e = self.find(name)
        if e is None:
            return False
        if template.get("mode") == "null":
            new = Entry(e.name, e.start, "null")
        else:
            new = Entry(e.name, e.start, "")
            new.body = [
                f"    fg_volume: {template.get('fg_volume', 'auto')}",
                "",
                f"    bg_volume: {template.get('bg_volume', '0')}",
                "",
                f"    easing: {template.get('easing', 'null')}",
            ]
        self.lines[e.start:e.end] = self._block_lines(new)
        self._commit()
        return True


# --------------------------------------------------------------------------- #
# 进程枚举
# --------------------------------------------------------------------------- #
def window_titles_by_pid() -> dict[int, list[str]]:
    """枚举可见顶层窗口，返回 pid -> [标题] 映射。"""
    user32 = ctypes.windll.user32
    result: dict[int, list[str]] = {}
    WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            n = user32.GetWindowTextLengthW(hwnd)
            if n <= 0:
                return True
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            title = buf.value.strip()
            if not title:
                return True
            pid = ctypes.wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            result.setdefault(int(pid.value), [])
            if title not in result[int(pid.value)]:
                result[int(pid.value)].append(title)
        except Exception:
            pass
        return True

    try:
        user32.EnumWindows(WNDENUMPROC(_cb), 0)
    except Exception:
        pass
    return result


def _is_system_path(path: str) -> bool:
    if not path:
        return False
    low = path.lower()
    win = os.environ.get("SystemRoot", r"C:\Windows").lower()
    return low.startswith(win + "\\") or "\\windowsapps\\" in low


def collect_processes() -> list[dict]:
    """汇总当前进程（同名合并），带窗口标题、内存、路径、是否系统进程。"""
    if psutil is None:
        return []
    titles = window_titles_by_pid()
    rows: dict[str, dict] = {}
    processes = list(psutil.process_iter(["pid", "name", "exe", "memory_info"]))
    discovered = {proc.pid for proc in processes}
    # Window owners can be absent from a cached/filtered process enumeration.
    # Resolve these known PIDs separately before grouping by executable name.
    for pid in titles:
        if pid not in discovered:
            try:
                processes.append(psutil.Process(pid))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    for proc in processes:
        try:
            info = getattr(proc, 'info', None) or proc.as_dict(["pid", "name", "exe", "memory_info"], ad_value=None)
            name = info.get("name") or ""
            if not name:
                continue
            pid = int(info["pid"])
            exe = info.get("exe") or ""
            mem = 0
            mi = info.get("memory_info")
            if mi is not None:
                mem = int(getattr(mi, "rss", 0) or 0)
        except Exception:
            continue
        key = name.lower()
        row = rows.get(key)
        if row is None:
            row = rows[key] = {
                "name": name, "pids": [], "titles": [], "mem": 0, "path": "",
                "system": _is_system_path(exe),
            }
        row["pids"].append(pid)
        row["mem"] += mem
        if exe and not row["path"]:
            row["path"] = exe
        for t in titles.get(pid, []):
            if t not in row["titles"]:
                row["titles"].append(t)
    out = []
    for row in rows.values():
        row["has_window"] = bool(row["titles"])
        out.append(row)
    return out


def fmt_mem(n: int) -> str:
    if not n:
        return ""
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024 or unit == "GB":
            return f"{f:.0f} {unit}" if unit in ("B", "KB", "MB") else f"{f:.1f} GB"
        f /= 1024
    return f"{f:.1f} GB"


# --------------------------------------------------------------------------- #
# 主界面
# --------------------------------------------------------------------------- #
class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.doc = ConfigDoc(CONFIG_PATH)
        self.proc_rows: list[dict] = []
        self.settings = load_settings()
        self.auto_refresh = tk.BooleanVar(value=bool(self.settings.get("auto_refresh")))
        self.restart_after_add = tk.BooleanVar(value=bool(self.settings.get("restart_after_add", True)))
        self.var_auto_start = tk.BooleanVar(value=bool(self.settings.get("auto_start_muter", True)))
        self.var_boot_autostart = tk.BooleanVar(value=bool(boot_autostart_exe()))
        self.filter_mode = tk.StringVar(value=self.settings.get("filter_mode", "window") or "window")
        self.search_var = tk.StringVar()
        self.template_var = tk.StringVar(value=self.settings.get("template", "standard") or "standard")

        root.title(WINDOW_TITLE)
        self._init_style()
        self._fit_window()
        self._build_ui()
        for _v in (self.restart_after_add, self.template_var, self.filter_mode,
                   self.auto_refresh, self.var_auto_start):
            _v.trace_add("write", lambda *_a: self._save_ui_settings())
        self.refresh_processes()
        self.refresh_entries()
        self._tick_status()
        # 打开本工具时，把静音工具本体也带起来，省得开两个程序
        root.after(700, self._auto_ensure_muter)

    # ---------------- 样式 ---------------- #
    def _fit_window(self) -> None:
        """按屏幕大小自适应窗口，避免在高 DPI 屏上过小或超出屏幕。"""
        r = self.root
        r.update_idletasks()
        try:
            dpi = ctypes.windll.user32.GetDpiForSystem() or 96
        except Exception:
            dpi = 96
        scale = max(1.0, dpi / 96.0)          # 175% 缩放 -> 1.75
        try:
            sw = ctypes.windll.user32.GetSystemMetrics(0) or r.winfo_screenwidth()
            sh = ctypes.windll.user32.GetSystemMetrics(1) or r.winfo_screenheight()
        except Exception:
            sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        # 目标是「约 1150x790 逻辑像素」的窗口，再按当前 DPI 缩放换算成物理像素
        w = max(900, min(int(1150 * scale), int(sw * 0.94)))
        h = max(600, min(int(790 * scale), int(sh * 0.92)))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 3)
        r.geometry(f"{w}x{h}+{x}+{y}")
        r.minsize(900, 600)

    def _init_style(self) -> None:
        style = ttk.Style()
        try:
            style.theme_use("vista")
        except Exception:
            pass
        base = ("Microsoft YaHei UI", 9)
        self.root.option_add("*Font", base)
        style.configure("Treeview", font=base, rowheight=24)
        style.configure("Treeview.Heading", font=("Microsoft YaHei UI", 9, "bold"))
        style.configure("TNotebook.Tab", font=("Microsoft YaHei UI", 10), padding=(18, 8))
        style.configure("Title.TLabel", font=("Microsoft YaHei UI", 12, "bold"))
        style.configure("Hint.TLabel", foreground="#666")

    def _build_ui(self) -> None:
        nb = ttk.Notebook(self.root)
        nb.pack(fill="both", expand=True, padx=10, pady=(10, 0))
        self.tab_add = ttk.Frame(nb)
        self.tab_manage = ttk.Frame(nb)
        nb.add(self.tab_add, text="  ① 选进程添加  ")
        nb.add(self.tab_manage, text="  ② 管理已有配置  ")
        self._build_add_tab()
        self._build_manage_tab()

        bar = ttk.Frame(self.root)
        bar.pack(fill="x", padx=12, pady=(6, 10))
        self.lbl_status = ttk.Label(bar, text="", style="Hint.TLabel")
        self.lbl_status.pack(side="left")
        self.lbl_muter = ttk.Label(bar, text="", style="Hint.TLabel")
        self.lbl_muter.pack(side="right")

    # ---------------- Tab 1 ---------------- #
    def _build_add_tab(self) -> None:
        f = self.tab_add

        top = ttk.Frame(f)
        top.pack(fill="x", padx=12, pady=(12, 6))
        ttk.Label(top, text="搜索：").pack(side="left")
        ent = ttk.Entry(top, textvariable=self.search_var, width=26)
        ent.pack(side="left", padx=(0, 12))
        ent.bind("<KeyRelease>", lambda _e: self.fill_process_tree())

        ttk.Label(top, text="显示：").pack(side="left")
        for val, label in (("window", "有窗口的程序"), ("game", "非系统进程"), ("all", "全部进程")):
            ttk.Radiobutton(top, text=label, value=val, variable=self.filter_mode,
                            command=self.fill_process_tree).pack(side="left", padx=2)
        ttk.Checkbutton(top, text="每 5 秒自动刷新", variable=self.auto_refresh,
                        command=self._schedule_auto).pack(side="left", padx=(12, 0))
        ttk.Button(top, text="立即刷新", command=self.refresh_processes).pack(side="right")

        hint = ttk.Label(
            f,
            text="提示：按住 Ctrl / Shift 可多选；双击某一行 = 直接添加。绿色 ✔ 表示已经在配置里了。",
            style="Hint.TLabel",
        )
        hint.pack(anchor="w", padx=12)

        box = ttk.Frame(f)
        box.pack(fill="both", expand=True, padx=12, pady=6)
        cols = ("name", "title", "pid", "mem", "state", "path")
        self.tree_proc = ttk.Treeview(box, columns=cols, show="headings", selectmode="extended")
        heads = {"name": "进程名（exe）", "title": "窗口标题", "pid": "PID",
                 "mem": "内存", "state": "状态", "path": "程序路径"}
        widths = {"name": 210, "title": 300, "pid": 70, "mem": 80, "state": 90, "path": 380}
        for c in cols:
            self.tree_proc.heading(c, text=heads[c],
                                   command=lambda cc=c: self._sort_by(cc))
            self.tree_proc.column(c, width=widths[c], anchor="w",
                                  stretch=(c in ("title", "path")))
        vs = ttk.Scrollbar(box, orient="vertical", command=self.tree_proc.yview)
        self.tree_proc.configure(yscrollcommand=vs.set)
        self.tree_proc.pack(side="left", fill="both", expand=True)
        vs.pack(side="left", fill="y")
        self.tree_proc.tag_configure("added", foreground="#0a7d28")
        self.tree_proc.tag_configure("nowin", foreground="#888888")
        self.tree_proc.bind("<Double-1>", self._on_double_add)

        bottom = ttk.LabelFrame(f, text=" 添加时使用的设置 ")
        bottom.pack(fill="x", padx=12, pady=(4, 12))
        row = ttk.Frame(bottom)
        row.pack(fill="x", padx=10, pady=8)
        ttk.Radiobutton(row, text="标准（前台 auto / 后台 0，推荐）",
                        value="standard", variable=self.template_var).pack(side="left")
        ttk.Radiobutton(row, text="使用 default 里的全局设置（null）",
                        value="null", variable=self.template_var).pack(side="left", padx=(16, 0))
        ttk.Checkbutton(row, text="写入后自动启动静音工具（运行中自动应用配置）",
                        variable=self.restart_after_add).pack(side="left", padx=(16, 0))

        row2 = ttk.Frame(bottom)
        row2.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(row2, text="手动输入进程名：").pack(side="left")
        self.var_manual = tk.StringVar()
        e2 = ttk.Entry(row2, textvariable=self.var_manual, width=34)
        e2.pack(side="left", padx=(0, 8))
        e2.bind("<Return>", lambda _e: self.add_manual())
        ttk.Button(row2, text="添加这个进程名", command=self.add_manual).pack(side="left")
        self.btn_add = ttk.Button(row2, text="✔ 把选中的进程加到静音配置",
                                  command=self.add_selected)
        self.btn_add.pack(side="right")

    # ---------------- Tab 2 ---------------- #
    def _build_manage_tab(self) -> None:
        f = self.tab_manage
        ttk.Label(f, text="已经在 config.yaml 里的进程", style="Title.TLabel").pack(
            anchor="w", padx=12, pady=(12, 2))
        ttk.Label(f, text="双击一行可修改它的音量设置；下面按钮可删除 / 备份 / 恢复。",
                  style="Hint.TLabel").pack(anchor="w", padx=12)

        box = ttk.Frame(f)
        box.pack(fill="both", expand=True, padx=12, pady=8)
        cols = ("name", "summary")
        self.tree_cfg = ttk.Treeview(box, columns=cols, show="headings", selectmode="extended")
        self.tree_cfg.heading("name", text="进程名")
        self.tree_cfg.heading("summary", text="配置")
        self.tree_cfg.column("name", width=280, anchor="w")
        self.tree_cfg.column("summary", width=640, anchor="w", stretch=True)
        vs = ttk.Scrollbar(box, orient="vertical", command=self.tree_cfg.yview)
        self.tree_cfg.configure(yscrollcommand=vs.set)
        self.tree_cfg.pack(side="left", fill="both", expand=True)
        vs.pack(side="left", fill="y")
        self.tree_cfg.tag_configure("warn", foreground="#c0392b")
        self.tree_cfg.tag_configure("off", foreground="#888888")
        self.tree_cfg.bind("<Double-1>", lambda _e: self.edit_selected())

        opt = ttk.LabelFrame(f, text=" 启动方式（不用再开两个程序） ")
        opt.pack(fill="x", padx=12, pady=(0, 8))
        r1 = ttk.Frame(opt)
        r1.pack(fill="x", padx=10, pady=(8, 2))
        ttk.Checkbutton(r1, text="打开本管理器时，自动启动静音工具（推荐）",
                        variable=self.var_auto_start,
                        command=self._save_ui_settings).pack(side="left")
        r2 = ttk.Frame(opt)
        r2.pack(fill="x", padx=10, pady=(2, 8))
        ttk.Checkbutton(r2, text="开机时自动启动静音工具（让它一直后台常驻，平时就不用管了）",
                        variable=self.var_boot_autostart,
                        command=self._toggle_boot_autostart).pack(side="left")

        bar = ttk.Frame(f)
        bar.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(bar, text="删除选中条目", command=self.delete_selected).pack(side="left")
        ttk.Button(bar, text="编辑选中条目", command=self.edit_selected).pack(side="left", padx=6)
        ttk.Button(bar, text="体检 / 修正大小写", command=self.health_check).pack(side="left", padx=6)
        ttk.Button(bar, text="打开 config.yaml", command=self.open_config).pack(side="left", padx=6)
        ttk.Button(bar, text="打开所在文件夹", command=lambda: os.startfile(APP_DIR)).pack(side="left", padx=6)
        ttk.Button(bar, text="立即备份", command=self.do_backup).pack(side="right")
        ttk.Button(bar, text="从备份恢复…", command=self.restore_backup).pack(side="right", padx=6)
        ttk.Button(bar, text="启动 / 重启静音工具", command=self.restart_muter).pack(side="right", padx=6)

    # ---------------- 进程表 ---------------- #
    def refresh_processes(self) -> None:
        self.lbl_status.configure(text="正在扫描进程…")
        self.root.update_idletasks()
        try:
            self.proc_rows = collect_processes()
        except Exception as exc:
            messagebox.showerror("扫描失败", f"读取进程列表出错：\n{exc}")
            self.proc_rows = []
        self.fill_process_tree()
        self.update_status()

    def _visible_rows(self) -> list[dict]:
        doc_names = self.doc.names_lower()
        mode = self.filter_mode.get()
        kw = self.search_var.get().strip().lower()
        out = []
        for r in self.proc_rows:
            r["in_config"] = r["name"].lower() in doc_names
            if mode == "window" and not r["has_window"]:
                continue
            if mode == "game" and (r["system"] or not r["has_window"]):
                continue
            if kw:
                hay = (r["name"] + " " + " ".join(r["titles"]) + " " + r["path"]).lower()
                if kw not in hay:
                    continue
            out.append(r)
        out.sort(key=self._sort_key)
        return out

    def _sort_key(self, r: dict):
        key = getattr(self, "_sort_col", None)
        rev = getattr(self, "_sort_rev", False)
        base = (1 if r["in_config"] else 0, 0 if r["has_window"] else 1, -r["mem"])
        if key == "name":
            return (r["name"].lower(),) + base
        if key == "mem":
            return (r["mem"],) + base
        if key == "pid":
            return (r["pids"][0],) + base
        if key == "title":
            return ((" ".join(r["titles"])).lower(),) + base
        if key == "path":
            return (r["path"].lower(),) + base
        if key == "state":
            return (1 if r["in_config"] else 0, -r["mem"])
        return base

    def _sort_by(self, col: str) -> None:
        if getattr(self, "_sort_col", None) == col:
            self._sort_rev = not getattr(self, "_sort_rev", False)
        else:
            self._sort_col = col
            self._sort_rev = False
        self.fill_process_tree()

    def fill_process_tree(self) -> None:
        tree = self.tree_proc
        tree.delete(*tree.get_children())
        for r in self._visible_rows():
            tags = []
            if r["in_config"]:
                tags.append("added")
                state = "✔ 已添加"
            else:
                state = "可添加"
            if not r["has_window"]:
                tags.append("nowin")
            pid_txt = str(r["pids"][0]) + (f" +{len(r['pids']) - 1}" if len(r["pids"]) > 1 else "")
            tree.insert("", "end", iid=r["name"].lower(), values=(
                r["name"],
                " ｜ ".join(r["titles"])[:120],
                pid_txt,
                fmt_mem(r["mem"]),
                state,
                r["path"],
            ), tags=tags)
        self.update_status()

    def _selected_process_names(self) -> list[str]:
        names = []
        for iid in self.tree_proc.selection():
            for r in self.proc_rows:
                if r["name"].lower() == iid:
                    names.append(r["name"])
                    break
        return names

    def _on_double_add(self, _event) -> None:
        self.add_selected()

    # ---------------- 添加 / 删除 ---------------- #
    def _template(self) -> dict:
        return dict(TEMPLATE_STANDARD) if self.template_var.get() == "standard" else dict(TEMPLATE_DEFAULT)

    def add_selected(self) -> None:
        names = self._selected_process_names()
        if not names:
            messagebox.showinfo("还没选", "请先在上面的列表里点选要静音的进程（可按住 Ctrl 多选）。")
            return
        self._add_names(names)

    def add_manual(self) -> None:
        raw = self.var_manual.get().strip()
        if not raw:
            messagebox.showinfo("提示", "请输入进程名，例如 SomeGame.exe")
            return
        name = raw if raw.lower().endswith(".exe") else raw + ".exe"
        self._add_names([name])
        self.var_manual.set("")

    def _add_names(self, names: list[str]) -> None:
        tpl = self._template()
        auto = bool(self.restart_after_add.get())
        added, existed = [], []
        backup = self.doc.backup()
        for n in names:
            if self.doc.add(n, tpl):
                added.append(n)
            else:
                existed.append(n)
        self.refresh_entries()
        self.fill_process_tree()
        self.update_status()

        applied = self.apply_changes(bool(added))

        msg = []
        if added:
            msg.append("已添加 {} 个：\n  {}".format(len(added), "\n  ".join(added)))
        if existed:
            msg.append("以下已经在配置里，跳过：\n  {}".format("\n  ".join(existed)))
        if backup:
            msg.append(f"\n原文件已备份到：\n  {backup}")
        if added:
            msg.append("\n" + applied)
        messagebox.showinfo("完成", "\n".join(msg) if msg else "没有变化。")

    def delete_selected(self) -> None:
        items = self.tree_cfg.selection()
        if not items:
            messagebox.showinfo("还没选", "请先在列表里选中要删除的条目。")
            return
        names = [self.tree_cfg.item(i, "values")[0] for i in items]
        if not messagebox.askyesno("确认删除", "确定从 config.yaml 删除以下 {} 项？\n\n{}".format(
                len(names), "\n".join(names))):
            return
        self.doc.backup()
        n = self.doc.remove(names)
        self.refresh_entries()
        self.fill_process_tree()
        self.update_status()
        messagebox.showinfo("完成", f"已删除 {n} 个条目。\n" + self.apply_changes(n > 0))

    def edit_selected(self) -> None:
        items = self.tree_cfg.selection()
        if len(items) != 1:
            messagebox.showinfo("提示", "请选中一行再编辑。")
            return
        name = self.tree_cfg.item(items[0], "values")[0]
        entry = self.doc.find(name)
        if entry is None:
            return
        EditDialog(self.root, self, entry)

    # ---------------- 配置列表 ---------------- #
    def refresh_entries(self) -> None:
        self.doc = ConfigDoc(CONFIG_PATH)
        tree = self.tree_cfg
        tree.delete(*tree.get_children())
        live = {r["name"].lower(): r["name"] for r in self.proc_rows}
        dups = {n.lower() for n in self.doc.duplicates()}
        for e in self.doc.entries:
            tags = []
            summary = e.summary()
            actual = live.get(e.name.lower())
            if e.name.lower() in dups:
                tags.append("warn")
                summary += "     ⚠ 重复条目（后面那条会覆盖它）"
            if actual and actual != e.name:
                tags.append("warn")
                summary += f"     ⚠ 大小写不符，实际进程名是 {actual}"
            elif not actual:
                tags.append("off")
            tree.insert("", "end", iid=e.name, values=(e.name, summary), tags=tags)
        self.update_status()

    def health_check(self) -> None:
        """检查：大小写不符（会导致静音失效）、重复条目。"""
        live = {r["name"].lower(): r["name"] for r in self.proc_rows}
        mismatch, not_running = [], []
        for e in self.doc.entries:
            actual = live.get(e.name.lower())
            if actual is None:
                not_running.append(e.name)
            elif actual != e.name:
                mismatch.append((e.name, actual))
        dups = self.doc.duplicates()

        lines = []
        if mismatch:
            lines.append("① 大小写不符（静音不会生效，建议修正）：")
            lines += [f"     {a}  →  {b}" for a, b in mismatch]
        if dups:
            lines.append("② 重复条目（请手动删除多余的一条）：")
            lines += [f"     {d}" for d in dups]
        if not mismatch and not dups:
            lines.append("没有发现大小写不符或重复的条目 ✔")
        lines.append("")
        lines.append(f"配置共 {len(self.doc.entries)} 条；当前进程列表里没找到的条目 {len(not_running)} 条")
        lines.append("（没找到只代表此刻没运行，不影响以后启动时生效）")

        text = "\n".join(lines)
        if not mismatch:
            messagebox.showinfo("配置体检", text)
            return
        if messagebox.askyesno("配置体检", text + "\n\n要把这些条目改成实际进程名（只改大小写）吗？"):
            backup = self.doc.backup()
            fixed, failed = [], []
            for old, new in mismatch:
                (fixed if self.doc.rename(old, new) else failed).append(f"{old} → {new}")
            self.refresh_entries()
            self.fill_process_tree()
            out = []
            if fixed:
                out.append("已修正：\n  " + "\n  ".join(fixed))
            if failed:
                out.append("未能修正（目标名已存在，请手动处理）：\n  " + "\n  ".join(failed))
            if backup:
                out.append(f"\n备份：{backup}")
            out.append(self.apply_changes(bool(fixed)))
            messagebox.showinfo("完成", "\n".join(out))

    def update_status(self) -> None:
        n = len(self.doc.entries)
        self.lbl_status.configure(
            text=f"配置文件：{CONFIG_PATH}    已有 {n} 条静音规则    列表显示 {len(self.tree_proc.get_children())} 项")

    # ---------------- 工具动作 ---------------- #
    def _save_ui_settings(self) -> None:
        try:
            save_settings({
                "auto_start_muter": bool(self.var_auto_start.get()),
                "restart_after_add": bool(self.restart_after_add.get()),
                "template": self.template_var.get(),
                "filter_mode": self.filter_mode.get(),
                "auto_refresh": bool(self.auto_refresh.get()),
            })
        except Exception:
            pass

    def _toggle_boot_autostart(self) -> None:
        exe = find_muter_exe()
        if self.var_boot_autostart.get():
            if not exe:
                self.var_boot_autostart.set(False)
                messagebox.showerror("找不到程序", "当前目录下没有找到 background_muter*.exe")
                return
            if set_boot_autostart(exe):
                messagebox.showinfo(
                    "已开启开机自启",
                    f"开机时会自动启动：\n{exe}\n\n"
                    "以后电脑一开机静音工具就已经在后台工作了，\n"
                    "你只在需要加新游戏时打开本管理器即可。\n\n"
                    "（已放在「启动」文件夹里，并设好了起始位置，\n"
                    "  不会出现读不到配置的问题）")
            else:
                self.var_boot_autostart.set(False)
                messagebox.showerror("设置失败", "写入注册表启动项失败。")
        else:
            if set_boot_autostart(None):
                messagebox.showinfo("已关闭", "已取消开机自动启动静音工具。")
            else:
                messagebox.showerror("设置失败", "删除注册表启动项失败。")

    def _auto_ensure_muter(self) -> None:
        """打开管理器时顺手把静音工具本体带起来，省得开两个程序。"""
        if not self.var_auto_start.get():
            return
        if self.muter_running():
            return
        if find_muter_exe():
            self.restart_muter(silent=True)
            self.root.after(1500, self.update_status)

    def muter_running(self) -> bool:
        return is_running()

    def apply_changes(self, changed: bool) -> str:
        if not changed:
            return "没有配置变化。"
        if self.muter_running():
            return "配置已保存，本体会在约 1 秒内自动应用；删除条目会恢复音量。"
        if self.restart_after_add.get():
            if self.restart_muter(silent=True):
                return "静音工具已启动，新配置将自动应用。"
            return "配置已保存，但本体启动失败，请查看错误提示。"
        return "配置已保存。静音工具未运行，请点「启动 / 重启静音工具」。"

    def restart_muter(self, silent: bool = False) -> bool:
        exe = find_muter_exe()
        if not exe:
            messagebox.showerror("找不到程序", "当前目录下没有找到 background_muter*.exe")
            return False
        running = self.muter_running()
        if running:
            if not request_stop():
                messagebox.showerror("重启失败", "无法请求安全退出；请从本体托盘退出后重试。")
                return False
            deadline = time.monotonic() + 8
            while (self.muter_running() or supervisor_running()) and time.monotonic() < deadline:
                time.sleep(.1)
            if self.muter_running() or supervisor_running():
                messagebox.showerror("重启超时", "本体还未完成音量恢复，重启已取消。请从托盘退出后重试。")
                return False
        try:
            subprocess.Popen([exe], cwd=APP_DIR, close_fds=True)
            deadline = time.monotonic() + 10
            while not self.muter_running() and time.monotonic() < deadline:
                time.sleep(.1)
            if not self.muter_running():
                raise RuntimeError("本体未就绪，请查看 logs 下最新日志")
        except Exception as exc:
            messagebox.showerror("启动失败", f"无法启动 {exe}\n{exc}")
            return False
        if not silent:
            messagebox.showinfo("已重启" if running else "已启动", "静音工具已就绪，运行中修改配置会自动生效。")
        return True

    def open_config(self) -> None:
        if not os.path.exists(CONFIG_PATH):
            messagebox.showerror("找不到文件", CONFIG_PATH)
            return
        try:
            os.startfile(CONFIG_PATH)
        except Exception as exc:
            messagebox.showerror("打开失败", str(exc))

    def do_backup(self) -> None:
        dst = self.doc.backup()
        if dst:
            messagebox.showinfo("已备份", dst)
        else:
            messagebox.showinfo("无需备份", "config.yaml 还不存在。")

    def restore_backup(self) -> None:
        if not os.path.isdir(BACKUP_DIR):
            messagebox.showinfo("没有备份", "还没有任何备份。")
            return
        files = sorted((f for f in os.listdir(BACKUP_DIR) if f.lower().endswith((".yaml", ".yml"))),
                       reverse=True)
        if not files:
            messagebox.showinfo("没有备份", "备份文件夹是空的。")
            return
        pick = filedialog.askopenfilename(
            title="选择要恢复的备份", initialdir=BACKUP_DIR,
            filetypes=[("YAML", "*.yaml"), ("全部文件", "*.*")])
        if not pick:
            return
        if not messagebox.askyesno("确认恢复", f"用备份覆盖当前 config.yaml？\n\n{pick}"):
            return
        self.doc.backup()
        shutil.copy2(pick, CONFIG_PATH)
        self.refresh_entries()
        self.fill_process_tree()
        messagebox.showinfo("已恢复", "配置已从备份恢复。\n" + self.apply_changes(True))

    # ---------------- 状态栏 / 定时 ---------------- #
    def _tick_status(self) -> None:
        state = "运行中" if self.muter_running() else "未运行"
        exe = find_muter_exe()
        self.lbl_muter.configure(text=f"静音工具（{os.path.basename(exe) if exe else '?'}）：{state}")
        self.root.after(4000, self._tick_status)

    def _schedule_auto(self) -> None:
        if getattr(self, "_auto_job", None):
            self.root.after_cancel(self._auto_job)
            self._auto_job = None
        if self.auto_refresh.get():
            self._auto_tick()

    def _auto_tick(self) -> None:
        if not self.auto_refresh.get():
            return
        self.refresh_processes()
        self._auto_job = self.root.after(5000, self._auto_tick)


# --------------------------------------------------------------------------- #
# 编辑对话框
# --------------------------------------------------------------------------- #
class EditDialog(tk.Toplevel):
    def __init__(self, master, app: App, entry: Entry):
        super().__init__(master)
        self.app = app
        self.entry = entry
        self.title(f"编辑 {entry.name}")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()

        self.mode = tk.StringVar(value="null" if entry.inline == "null" else "custom")
        fg = re.search(r"fg_volume\s*:\s*(\S+)", "\n".join(entry.body))
        bg = re.search(r"bg_volume\s*:\s*(\S+)", "\n".join(entry.body))
        self.var_fg = tk.StringVar(value=fg.group(1) if fg else "auto")
        self.var_bg = tk.StringVar(value=bg.group(1) if bg else "0")

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text=f"进程：{entry.name}", style="Title.TLabel").grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Radiobutton(body, text="使用 default 段里的全局设置（写 null，最简单）",
                        value="null", variable=self.mode,
                        command=self._sync).grid(row=1, column=0, columnspan=3, sticky="w")
        ttk.Radiobutton(body, text="单独设置：", value="custom", variable=self.mode,
                        command=self._sync).grid(row=2, column=0, sticky="w", pady=(8, 0))

        ttk.Label(body, text="前台音量 fg_volume").grid(row=3, column=1, sticky="e", pady=3)
        self.e_fg = ttk.Entry(body, textvariable=self.var_fg, width=16)
        self.e_fg.grid(row=3, column=2, sticky="w", padx=8)
        ttk.Label(body, text="后台音量 bg_volume").grid(row=4, column=1, sticky="e", pady=3)
        self.e_bg = ttk.Entry(body, textvariable=self.var_bg, width=16)
        self.e_bg.grid(row=4, column=2, sticky="w", padx=8)
        ttk.Label(body, text="（fg_volume 可填 auto 或 0~1 的小数；bg_volume 一般填 0）",
                  style="Hint.TLabel").grid(row=5, column=1, columnspan=2, sticky="w")

        bar = ttk.Frame(self, padding=(14, 0, 14, 14))
        bar.pack(fill="x")
        ttk.Button(bar, text="保存", command=self.save).pack(side="right")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right", padx=6)
        self._sync()

    def _sync(self) -> None:
        st = "normal" if self.mode.get() == "custom" else "disabled"
        self.e_fg.configure(state=st)
        self.e_bg.configure(state=st)

    def save(self) -> None:
        if self.mode.get() == "null":
            tpl = dict(TEMPLATE_DEFAULT)
        else:
            tpl = {"mode": "standard", "fg_volume": self.var_fg.get().strip() or "auto",
                   "bg_volume": self.var_bg.get().strip() or "0", "easing": "null"}
        if tpl.get("mode") == "standard":
            try:
                fg, bg = tpl['fg_volume'], tpl['bg_volume']
                if fg != 'auto' and not 0 <= float(fg) <= 1:
                    raise ValueError()
                if not 0 <= float(bg) <= 1:
                    raise ValueError()
            except (ValueError, TypeError):
                messagebox.showerror("音量无效", "前台音量请填 auto 或 0~1，后台音量请填 0~1。")
                return
        self.app.doc.backup()
        self.app.doc.update(self.entry.name, tpl)
        self.app.refresh_entries()
        self.app.fill_process_tree()
        messagebox.showinfo("已保存", self.app.apply_changes(True))
        self.destroy()


# --------------------------------------------------------------------------- #
# 自检（不开界面，直接测配置文件读写）
# --------------------------------------------------------------------------- #
def selftest() -> int:
    print(f"配置文件: {CONFIG_PATH}")
    print(f"存在: {os.path.exists(CONFIG_PATH)}")
    doc = ConfigDoc(CONFIG_PATH)
    original = "\n".join(doc.lines)
    before = [e.name for e in doc.entries]
    print(f"解析到 {len(before)} 个条目：{before[:5]}{' ...' if len(before) > 5 else ''}")
    print(f"processes 段: 第 {doc.proc_start} 行 ~ 第 {doc.proc_end} 行")

    b1 = doc.backup()
    print(f"备份 -> {b1}")

    fake = "__selftest_dummy__.exe"
    assert doc.add(fake, TEMPLATE_STANDARD), "新增失败"
    doc2 = ConfigDoc(CONFIG_PATH)
    assert fake in [e.name for e in doc2.entries], "写入后读不到新条目"
    got = doc2.find(fake)
    print(f"新增成功，摘要: {got.summary()}")

    assert doc2.update(fake, TEMPLATE_DEFAULT), "更新失败"
    doc3 = ConfigDoc(CONFIG_PATH)
    assert doc3.find(fake).inline == "null", "更新为 null 失败"
    print("更新为 null 成功")

    assert doc3.remove([fake]) == 1, "删除失败"
    doc4 = ConfigDoc(CONFIG_PATH)
    assert fake not in [e.name for e in doc4.entries], "删除后仍在"
    after = [e.name for e in doc4.entries]
    print(f"删除成功，剩余 {len(after)} 个条目")
    assert before == after, f"条目顺序/内容被破坏：{before} != {after}"

    # 大小写重命名（体检修正用）
    assert doc4.add("CaseTest.exe", TEMPLATE_STANDARD), "新增大小写测试条目失败"
    d5 = ConfigDoc(CONFIG_PATH)
    assert d5.rename("CaseTest.exe", "casetest.exe"), "重命名失败"
    d6 = ConfigDoc(CONFIG_PATH)
    e6 = d6.find("casetest.exe")
    assert e6 is not None, "重命名后找不到新名字"
    assert e6.summary() == "前台 auto / 后台 0 / easing null", f"重命名丢了参数：{e6.summary()}"
    assert d6.remove(["casetest.exe"]) == 1, "清理大小写测试条目失败"
    print("大小写重命名测试通过（参数保留）")

    try:
        import yaml
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert "processes" in data and len(data["processes"]) == len(after), "PyYAML 校验不一致"
        print(f"PyYAML 校验通过，processes 条目数 = {len(data['processes'])}")
    except ImportError:
        print("（未安装 PyYAML，跳过 YAML 校验）")

    if original == "\n".join(doc4.lines):
        print("文本内容与自检前完全一致 ✔（格式未被破坏）")
    else:
        print("文本有细微差别（空行），已从备份还原原文件")
        shutil.copy2(b1, CONFIG_PATH)
    print("SELFTEST OK")
    return 0


from modern_ui import build_app
App = build_app(sys.modules[__name__])


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()
    import logging
    from logging.handlers import RotatingFileHandler
    os.makedirs(os.path.join(APP_DIR, 'logs'), exist_ok=True)
    logger = logging.getLogger('muter.manager')
    logger.setLevel(logging.INFO)
    handler = RotatingFileHandler(os.path.join(APP_DIR, 'logs', 'manager.log'), maxBytes=262144, backupCount=1, encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
    logger.addHandler(handler)
    logger.info('Starting modern manager: %s', APP_DIR)
    if psutil is None:
        logger.warning('psutil unavailable')
    if activate_existing_window():
        logger.info('Reused existing manager window')
        return 0
    enable_dpi_awareness()
    root = tk.Tk()
    app = App(root)
    def callback_error(exc, value, tb):
        logger.error('UI callback failed', exc_info=(exc, value, tb))
        app.toast('操作未完成，请查看 logs/manager.log。', error=True)
    root.report_callback_exception = callback_error
    logger.info('Modern interface ready')
    root.mainloop()
    logger.info('Manager closed')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
