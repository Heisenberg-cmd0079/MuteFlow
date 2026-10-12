"""Desktop presentation for the existing configuration and control services."""
import ctypes
import math
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, filedialog
from PIL import Image, ImageDraw, ImageFont, ImageTk
import yaml

COLORS = dict(bg='#FFFFFF', sidebar='#EEF2F8', ink='#18253A', muted='#58677B',
              border='#DCE3EC', blue='#326BE6', blue_hover='#2358CC', selected='#E9F1FF',
              soft='#F6F8FC', green='#218653', success='#EEF8F2', red='#C63636')
FRIENDLY = {'mumuplayer.exe':'木木模拟器', 'nemuplayer.exe':'木木模拟器',
            'mumunxdevice.exe':'木木模拟器', 'starrail.exe':'崩坏：星穹铁道',
            'masterduel.exe':'游戏王：大师决斗', 'mahjongsoul.exe':'雀魂',
            'chrome.exe':'Chrome', 'msedge.exe':'Microsoft Edge', 'steam.exe':'Steam',
            'drapline.exe':'DRAPLINE', 'gf2_exilium.exe':'少女前线 2：追放'}

class SoftButton(tk.Button):
    """Rounded paint with a native button's command, focus and disabled semantics."""
    def __init__(self,parent,text,command,scale,primary=False):
        self.scale=scale; self.primary=primary; self.hover=False
        self.face=tkfont.Font(family='Microsoft YaHei UI',size=10,weight='bold' if primary else 'normal')
        super().__init__(parent,text=text,command=command,font=self.face,compound='center',
            bg=parent.cget('bg'),fg='white' if primary else COLORS['ink'],
            activebackground=parent.cget('bg'),activeforeground='white' if primary else COLORS['ink'],
            disabledforeground='#64748B',bd=0,relief='flat',padx=0,pady=0,cursor='hand2',
            highlightthickness=1,highlightbackground=parent.cget('bg'),highlightcolor=COLORS['blue'],takefocus=True)
        self._render()
        self.bind('<Enter>',lambda e:self._hover(True)); self.bind('<Leave>',lambda e:self._hover(False))
    def _hover(self,value): self.hover=value; self._render()
    def _render(self):
        width=max(self.scale(80),self.face.measure(self.cget('text'))+self.scale(30)); height=self.scale(42)
        disabled=self.cget('state')=='disabled'
        fill=('#DBE3F0' if disabled else (COLORS['blue_hover'] if self.hover else COLORS['blue'])) if self.primary else (COLORS['selected'] if self.hover else 'white')
        im=Image.new('RGBA',(width*3,height*3)); draw=ImageDraw.Draw(im)
        draw.rounded_rectangle((1,1,width*3-2,height*3-2),radius=self.scale(7)*3,
                              fill=fill,outline=fill if self.primary else COLORS['border'],width=3)
        self.picture=ImageTk.PhotoImage(im.resize((width,height),Image.Resampling.LANCZOS))
        if disabled:
            # Tk 8.6 stipples disabled images and has no disabledimage option.
            # Paint a quiet native disabled button instead, retaining real disabled state.
            super().configure(image='',bg='#DBE3F0',
                padx=max(0,(width-self.face.measure(self.cget('text')))//2),
                pady=max(0,(height-self.face.metrics('linespace'))//2))
        else:
            super().configure(image=self.picture,bg=self.master.cget('bg'),padx=0,pady=0)
    def configure(self,cnf=None,**kw):
        result=super().configure(cnf,**kw)
        if 'text' in kw or 'state' in kw: self._render()
        return result
    config=configure

def display_name(name, titles=()):
    if name.lower() in FRIENDLY:
        return FRIENDLY[name.lower()]
    return re.sub(r'\.exe$', '', name, flags=re.I)

def volume_text(value):
    if value == 'auto':
        return '自动恢复'
    try:
        return f'{float(value)*100:g}%'
    except (TypeError, ValueError):
        return '配置异常'

def read_rules(path):
    with open(path, encoding='utf-8-sig') as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or not isinstance(data.get('processes'), dict):
        raise ValueError('配置中的 processes 必须是应用规则列表。')
    defaults = data.get('default', {})
    result = {}
    for name, override in data['processes'].items():
        rule = dict(defaults)
        if isinstance(override, dict):
            rule.update(override)
        result[name.lower()] = (rule, override is None)
    return result

def glyph(kind, color, size):
    k = 4
    im = Image.new('RGBA', (size*k, size*k))
    d = ImageDraw.Draw(im)
    def line(points):
        d.line([(int(x*size*k/24), int(y*size*k/24)) for x,y in points], fill=color, width=max(1,int(size*k/13)), joint='curve')
    def ellipse(box):
        d.ellipse(tuple(int(x*size*k/24) for x in box), outline=color, width=max(1,int(size*k/13)))
    if kind == 'list':
        for y in (6,12,18):
            ellipse((3,y-1,5,y+1)); line([(9,y),(21,y)])
    elif kind == 'plus':
        ellipse((3,3,21,21)); line([(12,7),(12,17)]); line([(7,12),(17,12)])
    elif kind == 'settings':
        points=[]
        for i in range(32):
            a=i*math.pi/16
            r=9 if i%4 in (0,1) else 7
            points.append((12+math.cos(a)*r,12+math.sin(a)*r))
        line(points+[points[0]]); ellipse((8,8,16,16))
    elif kind == 'search':
        ellipse((4,3,16,15)); line([(15,14),(21,20)])
    elif kind == 'speaker':
        line([(3,9),(7,9),(12,5),(12,19),(7,15),(3,15),(3,9)])
        line([(16,8),(18,10),(18,14),(16,16)]); line([(19,5),(22,9),(22,15),(19,19)])
    elif kind == 'check':
        line([(5,12),(10,17),(20,7)])
    return im.resize((size,size), Image.Resampling.LANCZOS)

class ScrollList(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=COLORS['bg'], highlightbackground=COLORS['border'], highlightthickness=1)
        self.canvas=tk.Canvas(self, bg=COLORS['bg'], bd=0, highlightthickness=0)
        self.scroll=ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.scroll.pack(side='right',fill='y'); self.canvas.pack(side='left',fill='both',expand=True)
        self.body=tk.Frame(self.canvas,bg=COLORS['bg'])
        self.item=self.canvas.create_window(0,0,anchor='nw',window=self.body)
        self.body.bind('<Configure>',lambda e:self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>',lambda e:self.canvas.itemconfigure(self.item,width=e.width))
    def clear(self):
        for child in self.body.winfo_children(): child.destroy()
    def reset_scroll(self): self.canvas.yview_moveto(0)

def build_app(core):
    class App:
        def __init__(self, root):
            self.root=root; self.core=core
            self.settings=core.load_settings()
            self.doc=core.ConfigDoc(core.CONFIG_PATH)
            self.proc_rows=[]; self.selected=set(); self.selected_rule=None
            self.messages=queue.Queue(); self.refreshing=False; self.restarting=False
            self.icons={}; self.closed=False; self.current_page='rules'
            self._config_stamp=None
            self.filter_mode=tk.StringVar(value=self.settings.get('filter_mode','window'))
            self.template_var=tk.StringVar(value=self.settings.get('template','standard'))
            self.auto_refresh=tk.BooleanVar(value=self.settings.get('auto_refresh',False))
            self.restart_after_add=tk.BooleanVar(value=self.settings.get('restart_after_add',True))
            self.var_auto_start=tk.BooleanVar(value=self.settings.get('auto_start_muter',True))
            self.var_boot_autostart=tk.BooleanVar(value=bool(core.boot_autostart_exe()))
            self.rules_search=tk.StringVar(); self.search_var=tk.StringVar()
            self.rules_search.trace_add('write',lambda *_:self.render_rules())
            self.search_var.trace_add('write',lambda *_:self.render_processes())
            self.scale=max(1, (ctypes.windll.user32.GetDpiForSystem() or 96)/96)
            root.tk.call('tk','scaling',self.scale*96/72)
            root.title(core.WINDOW_TITLE); root.configure(bg=COLORS['bg'])
            root.option_add('*Font',('Microsoft YaHei UI',10))
            sw=root.winfo_screenwidth(); sh=root.winfo_screenheight()
            w=min(self.s(1150),int(sw*.94)); h=min(self.s(790),int(sh*.90))
            root.geometry(f'{w}x{h}+{max(0,(sw-w)//2)}+{max(0,(sh-h)//3)}')
            root.minsize(self.s(960),self.s(620))
            try:
                root.iconphoto(True,ImageTk.PhotoImage(glyph('speaker',COLORS['blue'],self.s(32))))
            except Exception: pass
            style=ttk.Style(root); style.theme_use('clam')
            style.configure('Vertical.TScrollbar',background='#C9D4E3',troughcolor='#F6F8FC',borderwidth=0,arrowsize=self.s(12))
            self._build()
            self.rules={}
            self.refresh_entries()
            self.show_page('rules')
            self.refresh_processes()
            for var in (self.filter_mode,self.template_var,self.auto_refresh,self.restart_after_add,self.var_auto_start):
                var.trace_add('write',lambda *_:self._save_ui_settings())
            root.bind_all('<MouseWheel>',self._wheel)
            root.bind('<Control-f>',lambda e:self.focus_search())
            root.bind('<F5>',lambda e:self.refresh_processes())
            root.bind('<Prior>',lambda e:self.active_list().canvas.yview_scroll(-1,'pages'))
            root.bind('<Next>',lambda e:self.active_list().canvas.yview_scroll(1,'pages'))
            root.protocol('WM_DELETE_WINDOW',self.close)
            root.after(100,self._poll)
            root.after(700,self._auto_ensure_muter)
            root.after(1500,self._tick)

        def s(self,n): return max(1,round(n*self.scale))
        def label(self,parent,text='',size=10,bold=False,color=None,bg=None,**kw):
            return tk.Label(parent,text=text,font=('Microsoft YaHei UI',size,'bold' if bold else 'normal'),
                            bg=bg or parent.cget('bg'),fg=color or COLORS['ink'],anchor='w',**kw)
        def button(self,parent,text,command,primary=False,danger=False,quiet=False):
            if not quiet and not danger:
                return SoftButton(parent,text,command,self.s,primary)
            color=COLORS['red'] if danger else (COLORS['blue'] if quiet else COLORS['ink'])
            bg=COLORS['blue'] if primary else parent.cget('bg')
            b=tk.Button(parent,text=text,command=command,font=('Microsoft YaHei UI',10,'bold' if primary else 'normal'),
                        bg=bg,fg='white' if primary else color,activebackground=COLORS['blue_hover'] if primary else COLORS['selected'],
                        activeforeground='white' if primary else color,relief='flat',bd=0,
                        padx=self.s(14 if not quiet else 8),pady=self.s(8),cursor='hand2',
                        highlightthickness=1,highlightbackground=bg if primary or quiet else COLORS['border'],
                        highlightcolor=COLORS['blue'],takefocus=True)
            b.bind('<Enter>',lambda e:b.configure(bg=COLORS['blue_hover'] if primary else COLORS['selected']))
            b.bind('<Leave>',lambda e:b.configure(bg=bg))
            return b
        def search(self,parent,var,caption):
            f=tk.Frame(parent,bg='white',highlightbackground=COLORS['border'],highlightcolor=COLORS['blue'],highlightthickness=1)
            img=ImageTk.PhotoImage(glyph('search',COLORS['muted'],self.s(18)))
            icon=tk.Label(f,image=img,bg='white'); icon.image=img; icon.pack(side='left',padx=self.s(12))
            e=tk.Entry(f,textvariable=var,bd=0,relief='flat',font=('Microsoft YaHei UI',10),fg=COLORS['ink'],
                       bg='white',insertbackground=COLORS['blue'],highlightthickness=0)
            e.pack(fill='x',expand=True,pady=self.s(11),padx=(0,self.s(10)))
            # A visible label is used instead of a placeholder which disappears when typing.
            return f,e
        def _build(self):
            self.sidebar=tk.Frame(self.root,bg=COLORS['sidebar'],width=self.s(200))
            self.sidebar.pack(side='left',fill='y'); self.sidebar.pack_propagate(False)
            logo=tk.Frame(self.sidebar,bg=COLORS['sidebar']); logo.pack(fill='x',padx=self.s(18),pady=(self.s(28),self.s(24)))
            logoimg=ImageTk.PhotoImage(glyph('speaker',COLORS['blue'],self.s(24)))
            logoicon=tk.Label(logo,image=logoimg,bg=COLORS['sidebar']); logoicon.image=logoimg; logoicon.pack(side='left')
            self.label(logo,'后台静音助手',11,True).pack(side='left',padx=self.s(9))
            self.nav={}
            for key,text,kind in [('rules','静音规则','list'),('add','添加应用','plus'),('settings','设置与备份','settings')]:
                image=ImageTk.PhotoImage(glyph(kind,COLORS['muted'],self.s(20)))
                b=tk.Button(self.sidebar,text='  '+text,image=image,compound='left',anchor='w',
                    font=('Microsoft YaHei UI',11),bg=COLORS['sidebar'],fg=COLORS['ink'],relief='flat',bd=0,
                    activebackground='#DAE7FD',activeforeground=COLORS['blue'],cursor='hand2',
                    padx=self.s(14),pady=self.s(14),highlightthickness=1,highlightbackground=COLORS['sidebar'],
                    highlightcolor=COLORS['blue'],command=lambda k=key:self.show_page(k))
                b.image=image; b.pack(fill='x',padx=self.s(12),pady=self.s(4)); self.nav[key]=b
            bottom=tk.Frame(self.sidebar,bg=COLORS['sidebar']); bottom.pack(side='bottom',fill='x',padx=self.s(20),pady=self.s(26))
            self.service_dot=tk.Canvas(bottom,width=self.s(10),height=self.s(10),bg=COLORS['sidebar'],highlightthickness=0)
            self.service_dot.grid(row=0,column=0,padx=(0,self.s(10)))
            self.service_label=self.label(bottom,'检查服务状态',10); self.service_label.grid(row=0,column=1,sticky='w')
            self.label(bottom,'配置自动生效',9,color=COLORS['muted']).grid(row=1,column=1,sticky='w',pady=(self.s(4),0))
            self.content=tk.Frame(self.root,bg='white'); self.content.pack(side='left',fill='both',expand=True)
            self.pages={}
            for key in ('rules','add','settings'):
                self.pages[key]=tk.Frame(self.content,bg='white')
            self._build_rules(); self._build_add(); self._build_settings()
        def heading(self,parent,title,subtitle,action=None):
            top=tk.Frame(parent,bg='white'); top.pack(fill='x',padx=self.s(26),pady=(self.s(24),self.s(18)))
            if action: self.button(top,action[0],action[1],primary=True).pack(side='right',anchor='n')
            text=tk.Frame(top,bg='white'); text.pack(side='left',fill='x',expand=True)
            self.label(text,title,21,True).pack(anchor='w')
            self.label(text,subtitle,10,color=COLORS['muted']).pack(anchor='w',pady=(self.s(7),0))
        def _build_rules(self):
            p=self.pages['rules']
            self.heading(p,'静音规则','后台自动静音，切回应用恢复音量。',('+ 添加应用',lambda:self.show_page('add')))
            self.label(p,'搜索已添加的应用',9,color=COLORS['muted']).pack(anchor='w',padx=self.s(26),pady=(0,self.s(5)))
            f,self.rules_entry=self.search(p,self.rules_search,'搜索已添加的应用'); f.pack(fill='x',padx=self.s(26))
            bottom=tk.Frame(p,bg='white'); bottom.pack(side='bottom',fill='x',padx=self.s(26),pady=(0,self.s(20)))
            self.rule_count=self.label(bottom,''); self.rule_count.pack(side='left')
            self.clear_search=self.button(bottom,'清除筛选',lambda:self.rules_search.set(''),quiet=True); self.clear_search.pack(side='right')
            self.notice=self.label(p,'配置更改自动生效，无需重启。',9,color=COLORS['muted'],padx=self.s(12),pady=self.s(11))
            self.notice.pack(side='bottom',fill='x',padx=self.s(26),pady=(self.s(8),self.s(10)))
            self.label(p,'自动恢复：使用应用原来的音量。点击应用名称可查看进程详情。',9,color=COLORS['muted']).pack(side='bottom',anchor='w',padx=self.s(26),pady=(self.s(10),0))
            header=tk.Frame(p,bg=COLORS['soft']); header.pack(fill='x',padx=self.s(26),pady=(self.s(16),0))
            self._rule_columns(header)
            for col,text in enumerate(('应用','前台音量','后台音量','操作')):
                self.label(header,text,9,color=COLORS['muted'],padx=self.s(14),pady=self.s(11)).grid(row=0,column=col,sticky='w')
            self.rule_list=ScrollList(p,self); self.rule_list.pack(fill='both',expand=True,padx=self.s(26))
        def _rule_columns(self,frame):
            frame.grid_columnconfigure(0,weight=1)
            for c,w in [(1,140),(2,115),(3,144)]: frame.grid_columnconfigure(c,minsize=self.s(w))
        def _build_add(self):
            p=self.pages['add']
            self.heading(p,'添加应用','选择正在运行的应用，添加后台静音规则。')
            top=tk.Frame(p,bg='white'); top.pack(fill='x',padx=self.s(26),pady=(0,self.s(12)))
            self.label(top,'搜索应用名或进程名',9,color=COLORS['muted']).pack(anchor='w',pady=(0,self.s(5)))
            row=tk.Frame(top,bg='white'); row.pack(fill='x')
            self.refresh_button=self.button(row,'刷新',self.refresh_processes); self.refresh_button.pack(side='right',padx=(self.s(10),0))
            field,self.add_entry=self.search(row,self.search_var,'搜索应用名或进程名'); field.pack(side='left',fill='x',expand=True)
            filters=tk.Frame(p,bg='white'); filters.pack(fill='x',padx=self.s(26),pady=(0,self.s(14)))
            for key,text in [('window','有窗口的应用'),('game','非系统应用'),('all','全部进程')]:
                tk.Radiobutton(filters,text=text,value=key,variable=self.filter_mode,indicatoron=False,relief='flat',
                    bg=COLORS['soft'],fg=COLORS['muted'],selectcolor=COLORS['selected'],activebackground=COLORS['selected'],
                    activeforeground=COLORS['blue'],bd=0,padx=self.s(12),pady=self.s(7),
                    highlightthickness=1,highlightbackground=COLORS['border'],highlightcolor=COLORS['blue'],
                    command=lambda:(self.render_processes(),self.process_list.reset_scroll())).pack(side='left',padx=(0,self.s(6)))
            footer=tk.Frame(p,bg='white'); footer.pack(side='bottom',fill='x',padx=self.s(26),pady=(self.s(12),self.s(20)))
            self.selected_label=self.label(footer,'已选择 0 个应用'); self.selected_label.pack(side='left')
            self.add_button=self.button(footer,'添加应用',self.add_selected,primary=True); self.add_button.pack(side='right')
            self.add_notice=self.label(p,'选择应用后批量添加。',9,color=COLORS['muted'],pady=self.s(6))
            self.add_notice.pack(side='bottom',fill='x',padx=self.s(26))
            template=tk.Frame(p,bg=COLORS['soft'],highlightbackground=COLORS['border'],highlightthickness=1)
            template.pack(side='bottom',fill='x',padx=self.s(26),pady=(self.s(10),0))
            self.label(template,'添加时使用',9,bg=COLORS['soft']).pack(side='left',padx=self.s(12))
            for value,text in [('standard','前台自动恢复 / 后台静音'),('null','全局默认设置')]:
                tk.Radiobutton(template,text=text,value=value,variable=self.template_var,bg=COLORS['soft'],fg=COLORS['ink'],
                               selectcolor='white',activebackground=COLORS['soft'],bd=0,pady=self.s(12)).pack(side='left',padx=self.s(8))
            manual=tk.Frame(p,bg='white'); manual.pack(side='bottom',fill='x',padx=self.s(26),pady=(self.s(10),0))
            self.button(manual,'+ 手动输入进程名',self.manual_dialog,quiet=True).pack(side='left')
            header=tk.Frame(p,bg=COLORS['soft']); header.pack(fill='x',padx=self.s(26))
            self.select_all_var=tk.BooleanVar()
            tk.Checkbutton(header,variable=self.select_all_var,command=self.select_all_visible,bg=COLORS['soft'],
                           selectcolor='white',activebackground=COLORS['soft'],takefocus=True).pack(side='left',padx=self.s(12),pady=self.s(8))
            self.label(header,'应用',9,color=COLORS['muted']).pack(side='left')
            self.label(header,'状态',9,color=COLORS['muted']).pack(side='right',padx=self.s(28))
            self.process_list=ScrollList(p,self); self.process_list.pack(fill='both',expand=True,padx=self.s(26))
        def _build_settings(self):
            p=self.pages['settings']; self.heading(p,'设置与备份','启动方式、配置备份和维护工具。')
            self.settings_list=ScrollList(p,self); self.settings_list.pack(fill='both',expand=True,padx=self.s(26),pady=(0,self.s(22)))
            body=self.settings_list.body
            self.section(body,'启动方式')
            self.setting_check(body,'开机自动启动静音服务','登录 Windows 后在后台运行，无需打开管理器。',self.var_boot_autostart,self.toggle_boot)
            self.setting_check(body,'打开管理器时启动服务','如果静音服务没有运行，自动将它启动。',self.var_auto_start)
            self.setting_check(body,'保存规则后启动服务','运行中的服务会自动应用配置；此项只负责未运行时启动。',self.restart_after_add)
            self.section(body,'应用列表')
            self.setting_check(body,'每 5 秒自动刷新','自动更新正在运行的应用列表。',self.auto_refresh)
            self.section(body,'备份与恢复')
            self.setting_actions(body,'配置备份','每次修改前也会自动备份。',[('立即备份',self.do_backup),('从备份恢复',self.restore_backup)])
            self.section(body,'维护工具')
            self.setting_actions(body,'静音服务','重启前会恢复受管应用的音量。',[('启动 / 重启服务',self.restart_muter)])
            self.setting_actions(body,'配置检查','检查重复条目和进程名大小写。',[('检查配置',self.health_check)])
            self.setting_actions(body,'配置文件','高级编辑和日志位于程序所在目录。',[('打开配置文件',self.open_config),('打开所在文件夹',lambda:os.startfile(core.APP_DIR))])
            self.settings_notice=self.label(body,'',9,color=COLORS['muted'],pady=self.s(12)); self.settings_notice.pack(fill='x',padx=self.s(16))
        def section(self,parent,text): self.label(parent,text,12,True).pack(anchor='w',padx=self.s(16),pady=(self.s(20),self.s(7)))
        def setting_check(self,parent,title,detail,var,command=None):
            f=tk.Frame(parent,bg='white'); f.pack(fill='x',padx=self.s(16),pady=self.s(8))
            tk.Checkbutton(f,text=title,variable=var,command=command,bg='white',fg=COLORS['ink'],
                           selectcolor='white',activebackground='white',bd=0,anchor='w').pack(anchor='w')
            self.label(f,detail,9,color=COLORS['muted'],wraplength=self.s(650)).pack(anchor='w',padx=self.s(25),pady=(self.s(4),0))
        def setting_actions(self,parent,title,detail,actions):
            f=tk.Frame(parent,bg='white'); f.pack(fill='x',padx=self.s(16),pady=self.s(10))
            text=tk.Frame(f,bg='white'); text.pack(side='left',fill='x',expand=True)
            self.label(text,title,10,True).pack(anchor='w'); self.label(text,detail,9,color=COLORS['muted']).pack(anchor='w',pady=(self.s(5),0))
            for label,func in reversed(actions): self.button(f,label,func).pack(side='right',padx=(self.s(8),0))
        def show_page(self,key):
            for p in self.pages.values(): p.pack_forget()
            self.pages[key].pack(fill='both',expand=True); self.current_page=key
            for k,b in self.nav.items():
                color=COLORS['blue'] if k==key else COLORS['muted']; bg='#DAE7FD' if k==key else COLORS['sidebar']
                kind={'rules':'list','add':'plus','settings':'settings'}[k]
                image=ImageTk.PhotoImage(glyph(kind,color,self.s(20)))
                b.configure(bg=bg,fg=COLORS['blue'] if k==key else COLORS['ink'],image=image,highlightbackground=bg); b.image=image
            if key=='rules': self.render_rules()
            if key=='add': self.render_processes()
        def active_list(self): return {'rules':self.rule_list,'add':self.process_list,'settings':self.settings_list}[self.current_page]
        def focus_search(self):
            if self.current_page=='rules': self.rules_entry.focus_set()
            elif self.current_page=='add': self.add_entry.focus_set()
        def _wheel(self,event):
            widget=self.root.winfo_containing(event.x_root,event.y_root)
            while widget:
                if widget==self.active_list():
                    self.active_list().canvas.yview_scroll(-int(event.delta/120)*3,'units'); return 'break'
                widget=getattr(widget,'master',None)
        def app_icon(self,name,path=''):
            key=(name.lower(),path)
            if key in self.icons: return self.icons[key]
            size=self.s(38); im=None
            if path and os.path.isfile(path):
                try:
                    import win32gui, win32ui, win32con
                    large,small=win32gui.ExtractIconEx(path,0)
                    handle=(large or small)[0]
                    dc=win32ui.CreateDCFromHandle(win32gui.GetDC(0)); mem=dc.CreateCompatibleDC()
                    bitmap=win32ui.CreateBitmap(); bitmap.CreateCompatibleBitmap(dc,size,size); mem.SelectObject(bitmap)
                    mem.FillSolidRect((0,0,size,size),0xFFFFFF)
                    win32gui.DrawIconEx(mem.GetSafeHdc(),0,0,handle,size,size,0,None,win32con.DI_NORMAL)
                    im=Image.frombuffer('RGB',(size,size),bitmap.GetBitmapBits(True),'raw','BGRX',0,1).copy()
                    win32gui.DeleteObject(bitmap.GetHandle()); mem.DeleteDC()
                    win32gui.ReleaseDC(0,dc.GetSafeHdc())
                    for h in large+small: win32gui.DestroyIcon(h)
                except Exception: im=None
            if im is None:
                im=Image.new('RGBA',(size*3,size*3),'white'); d=ImageDraw.Draw(im)
                palette=['#326BE6','#5B76A8','#277C85','#7657A5','#A16D40']
                color=palette[sum(ord(x) for x in name)%len(palette)]
                d.rounded_rectangle((0,0,size*3-1,size*3-1),radius=size//2,fill=color)
                try: font=ImageFont.truetype(os.path.join(os.environ.get('WINDIR',r'C:\Windows'),'Fonts','segoeuib.ttf'),size*2)
                except Exception: font=ImageFont.load_default()
                letter=next((c.upper() for c in name if c.isascii() and c.isalnum()),'A')
                d.text((size*1.5,size*1.4),letter,font=font,fill='white',anchor='mm')
                im=im.resize((size,size),Image.Resampling.LANCZOS)
            photo=ImageTk.PhotoImage(im); self.icons[key]=photo; return photo
        def app_identity(self,parent,name,path='',titles=(),bg='white'):
            f=tk.Frame(parent,bg=bg)
            icon=self.app_icon(name,path); tk.Label(f,image=icon,bg=bg).pack(side='left',padx=(0,self.s(12)))
            text=tk.Frame(f,bg=bg); text.pack(side='left',fill='x',expand=True)
            title=self.label(text,display_name(name,titles),10,True,bg=bg,wraplength=self.s(230),justify='left',cursor='hand2')
            title.pack(anchor='w'); title.bind('<Button-1>',lambda e:self.show_details(name,path))
            title.bind('<Enter>',lambda e:title.configure(fg=COLORS['blue']))
            title.bind('<Leave>',lambda e:title.configure(fg=COLORS['ink']))
            self.label(text,name,9,color=COLORS['muted'],bg=bg,wraplength=self.s(230),justify='left').pack(anchor='w',pady=(self.s(3),0))
            return f
        def refresh_entries(self):
            try:
                candidate=core.ConfigDoc(core.CONFIG_PATH); rules=read_rules(core.CONFIG_PATH)
                self.doc=candidate; self.rules=rules
                self._config_stamp=os.stat(core.CONFIG_PATH).st_mtime_ns
                self.render_rules(); self.render_processes()
            except Exception as exc: self.toast('读取配置失败：'+str(exc),error=True)
        def render_rules(self):
            if not hasattr(self,'rule_list'): return
            self.rule_list.clear(); kw=self.rules_search.get().strip().lower(); count=0
            live={r['name'].lower():r for r in self.proc_rows}; duplicates={n.lower() for n in self.doc.duplicates()}
            for entry in self.doc.entries:
                name=entry.name; friendly=display_name(name)
                if kw and kw not in (name+' '+friendly).lower(): continue
                count+=1; row=tk.Frame(self.rule_list.body,bg='white'); row.pack(fill='x')
                self._rule_columns(row)
                proc=live.get(name.lower(),{}); identity=self.app_identity(row,name,proc.get('path',''))
                identity.grid(row=0,column=0,sticky='ew',padx=self.s(14),pady=self.s(14))
                rule,is_default=self.rules.get(name.lower(),({},False))
                foreground=tk.Frame(row,bg='white'); foreground.grid(row=0,column=1,sticky='w',padx=self.s(14))
                fg=rule.get('fg_volume'); text=volume_text(fg)
                self.label(foreground,text,10,color=COLORS['blue'] if fg=='auto' else COLORS['ink'],
                           bg=COLORS['selected'] if fg=='auto' else 'white',padx=self.s(6),pady=self.s(3)).pack(anchor='w')
                if is_default: self.label(foreground,'使用全局设置',8,color=COLORS['muted']).pack(anchor='w',pady=(self.s(3),0))
                self.label(row,volume_text(rule.get('bg_volume')),10,padx=self.s(14)).grid(row=0,column=2,sticky='w')
                actions=tk.Frame(row,bg='white'); actions.grid(row=0,column=3,sticky='w',padx=self.s(6))
                self.button(actions,'编辑',lambda n=name:self.edit_rule(n),quiet=True).pack(side='left')
                self.button(actions,'移除',lambda n=name:self.remove_rules([n]),danger=True,quiet=True).pack(side='left')
                if name.lower() in duplicates or (proc and proc['name']!=name):
                    self.label(row,'重复条目或大小写不一致，请到设置页检查配置。',9,color=COLORS['red']).grid(row=1,column=0,columnspan=4,sticky='w',padx=self.s(14),pady=(0,self.s(8)))
                tk.Frame(self.rule_list.body,bg=COLORS['border'],height=1).pack(fill='x')
            if not count:
                self.label(self.rule_list.body,'没有匹配的规则' if kw else '还没有静音规则',14,True).pack(anchor='w',padx=self.s(24),pady=(self.s(36),self.s(8)))
                self.label(self.rule_list.body,'试试其他关键词。' if kw else '点击“添加应用”，选择要在后台静音的应用。',10,color=COLORS['muted']).pack(anchor='w',padx=self.s(24))
            self.rule_count.configure(text=f'共 {len(self.doc.entries)} 条规则'+(f'，找到 {count} 条' if kw else ''))
        def visible_processes(self):
            kw=self.search_var.get().strip().lower(); mode=self.filter_mode.get(); result=[]
            names=self.doc.names_lower()
            for row in self.proc_rows:
                if mode=='window' and not row['has_window']: continue
                if mode=='game' and row['system']: continue
                hay=' '.join([row['name'],display_name(row['name']),*row['titles']]).lower()
                if kw and kw not in hay: continue
                result.append(row)
            result.sort(key=lambda r:(r['name'].lower() in names,not r['has_window'],display_name(r['name']).lower()))
            return result
        def render_processes(self):
            if not hasattr(self,'process_list'): return
            self.process_list.clear(); self.process_frames={}; names=self.doc.names_lower(); rows=self.visible_processes()
            self.selected.difference_update(names); self.process_vars={}
            for proc in rows:
                name=proc['name']; key=name.lower(); added=key in names
                bg=COLORS['soft'] if added else (COLORS['selected'] if key in self.selected else 'white')
                row=tk.Frame(self.process_list.body,bg=bg); row.pack(fill='x')
                self.process_frames[key]=row
                var=tk.BooleanVar(value=key in self.selected); self.process_vars[key]=var
                tk.Checkbutton(row,variable=var,state='disabled' if added else 'normal',bg=bg,activebackground=bg,
                    selectcolor='white',bd=0,command=lambda k=key,v=var:self.toggle_process(k,v.get())).pack(side='left',padx=self.s(12))
                self.app_identity(row,name,proc['path'],proc['titles'],bg).pack(side='left',fill='x',expand=True,pady=self.s(13))
                self.label(row,'已添加' if added else '未添加',9,color=COLORS['muted'],bg=bg).pack(side='right',padx=self.s(22))
                tk.Frame(self.process_list.body,bg=COLORS['border'],height=1).pack(fill='x')
            if not rows:
                self.label(self.process_list.body,'正在读取应用…' if self.refreshing else '没有匹配的应用',13,True).pack(anchor='w',padx=self.s(24),pady=(self.s(34),self.s(8)))
                self.label(self.process_list.body,'试试“全部进程”，或手动输入进程名。',10,color=COLORS['muted']).pack(anchor='w',padx=self.s(24))
            self.update_selection()
        def toggle_process(self,key,value):
            if value: self.selected.add(key)
            else: self.selected.discard(key)
            self.update_selection()
            row=getattr(self,'process_frames',{}).get(key)
            if row:
                bg=COLORS['selected'] if value else 'white'
                def paint(widget):
                    try: widget.configure(bg=bg)
                    except tk.TclError: pass
                    for child in widget.winfo_children(): paint(child)
                paint(row)
        def select_all_visible(self):
            available={r['name'].lower() for r in self.visible_processes()}-self.doc.names_lower()
            if self.select_all_var.get(): self.selected.update(available)
            else: self.selected.difference_update(available)
            self.render_processes()
        def update_selection(self):
            count=len(self.selected); self.selected_label.configure(text=f'已选择 {count} 个应用')
            self.add_button.configure(text=f'添加 {count} 个应用' if count else '添加应用',state='normal' if count else 'disabled')
            available={r['name'].lower() for r in self.visible_processes()}-self.doc.names_lower()
            self.select_all_var.set(bool(available) and available.issubset(self.selected))
        def refresh_processes(self):
            if self.refreshing: return
            self.refreshing=True; self.refresh_button.configure(text='读取中…',state='disabled')
            def job():
                try: self.messages.put(('processes',core.collect_processes()))
                except Exception as exc: self.messages.put(('process_error',str(exc)))
            threading.Thread(target=job,daemon=True,name='ManagerProcessScan').start()
        def _poll(self):
            if self.closed: return
            try:
                while True:
                    kind,data=self.messages.get_nowait()
                    if kind=='processes':
                        self.proc_rows=data; live={r['name'].lower() for r in data}
                        self.selected.intersection_update(live)
                        self.refreshing=False; self.refresh_button.configure(text='刷新',state='normal')
                        self.render_processes(); self.render_rules()
                    elif kind=='process_error':
                        self.refreshing=False; self.refresh_button.configure(text='刷新',state='normal'); self.toast('读取应用失败：'+data,error=True)
                    elif kind=='service':
                        self.restarting=False; self.toast(data); self._update_service()
                    elif kind=='service_error':
                        self.restarting=False; self.toast(data,error=True); self._update_service()
            except queue.Empty: pass
            self.root.after(120,self._poll)
        def toast(self,text,error=False):
            bg='#FFF2F2' if error else COLORS['success']; color=COLORS['red'] if error else COLORS['green']
            for label in (self.notice,self.add_notice,self.settings_notice): label.configure(text=text,bg=bg,fg=color)
        def _template(self): return dict(core.TEMPLATE_STANDARD if self.template_var.get()=='standard' else core.TEMPLATE_DEFAULT)
        def add_selected(self):
            names=[r['name'] for r in self.proc_rows if r['name'].lower() in self.selected]
            if names: self._add_names(names)
        def _add_names(self,names):
            try:
                self.doc=core.ConfigDoc(core.CONFIG_PATH); self.doc.backup(); added=[]
                for name in names:
                    if self.doc.add(name,self._template()): added.append(name)
                self.selected.difference_update(n.lower() for n in added)
                self.refresh_entries()
                self.toast(f'已添加 {len(added)} 个应用。'+self.apply_changes(bool(added)) if added else '这些应用已在规则中。')
            except Exception as exc: self.toast('添加失败：'+str(exc),error=True)
        def remove_rules(self,names,confirm=True):
            if confirm and not messagebox.askyesno('移除静音规则','移除后会恢复应用音量，并停止自动静音。\n\n'+ '\n'.join(names),parent=self.root): return
            try:
                self.doc=core.ConfigDoc(core.CONFIG_PATH); self.doc.backup(); count=self.doc.remove(names)
                self.refresh_entries(); self.toast(f'已移除 {count} 条规则。'+self.apply_changes(count>0))
            except Exception as exc: self.toast('移除失败：'+str(exc),error=True)
        def dialog(self,title,width=510):
            win=tk.Toplevel(self.root); win.title(title); win.configure(bg='white'); win.transient(self.root)
            win.resizable(False,False); win.bind('<Escape>',lambda e:win.destroy())
            win.body=tk.Frame(win,bg='white'); win.body.pack(fill='both',expand=True,padx=self.s(24),pady=self.s(22))
            win.after_idle(lambda:self._center_dialog(win,width))
            return win
        def _center_dialog(self,win,width):
            if not win.winfo_exists(): return
            win.update_idletasks(); w=self.s(width); h=win.winfo_reqheight()
            x=max(0,self.root.winfo_rootx()+(self.root.winfo_width()-w)//2)
            y=max(0,self.root.winfo_rooty()+(self.root.winfo_height()-h)//2)
            win.geometry(f'{w}x{h}+{x}+{y}'); win.grab_set()
        def manual_dialog(self):
            win=self.dialog('手动添加应用'); body=win.body
            self.label(body,'手动添加应用',16,True).pack(anchor='w')
            self.label(body,'应用没有运行时，也可以通过进程名添加规则。',9,color=COLORS['muted']).pack(anchor='w',pady=(self.s(8),self.s(20)))
            self.label(body,'进程名，例如 SomeGame.exe',10).pack(anchor='w')
            var=tk.StringVar(); entry=tk.Entry(body,textvariable=var,font=('Microsoft YaHei UI',11),relief='flat',
                  highlightthickness=1,highlightbackground=COLORS['border'],highlightcolor=COLORS['blue'])
            entry.pack(fill='x',ipady=self.s(10),pady=self.s(8)); entry.focus_set()
            error=self.label(body,'',9,color=COLORS['red']); error.pack(anchor='w')
            def save():
                name=var.get().strip()
                if not name or any(c in name for c in '\\/:*?"<>|\n\r') or name.startswith('#'):
                    error.configure(text='请填写有效的 exe 文件名，不要填写完整路径。'); return
                if not name.lower().endswith('.exe'): name+='.exe'
                self._add_names([name]); win.destroy()
            actions=tk.Frame(body,bg='white'); actions.pack(fill='x',pady=(self.s(12),0))
            self.button(actions,'添加应用',save,primary=True).pack(side='right')
            self.button(actions,'取消',win.destroy,quiet=True).pack(side='right',padx=self.s(8))
            entry.bind('<Return>',lambda e:save())
        def show_details(self,name,path):
            proc=next((r for r in self.proc_rows if r['name'].lower()==name.lower()),None)
            win=self.dialog('应用详情',560); body=win.body
            self.label(body,display_name(name),16,True).pack(anchor='w')
            self.label(body,name,9,color=COLORS['muted']).pack(anchor='w',pady=(self.s(6),self.s(18)))
            if proc:
                fields=[('进程 PID',', '.join(str(p) for p in proc['pids'])),('内存占用',core.fmt_mem(proc['mem'])),
                        ('窗口标题',' / '.join(proc['titles']) or '无可见窗口'),('程序路径',path or '无法读取')]
            else: fields=[('运行状态','当前未运行。规则会在应用启动后自动生效。')]
            for label,value in fields:
                self.label(body,label,9,color=COLORS['muted']).pack(anchor='w',pady=(self.s(10),self.s(4)))
                self.label(body,value,10,wraplength=self.s(500),justify='left').pack(anchor='w')
            footer=tk.Frame(body,bg='white'); footer.pack(fill='x',pady=(self.s(20),0))
            self.button(footer,'关闭',win.destroy).pack(side='right')
            if path:
                def copy_path():
                    self.root.clipboard_clear(); self.root.clipboard_append(path); self.toast('程序路径已复制。')
                self.button(footer,'复制程序路径',copy_path,quiet=True).pack(side='left')
        def save_rule(self,name,mode,fg,bg):
            if mode=='null': template=dict(core.TEMPLATE_DEFAULT)
            else:
                fg=fg.strip(); bg=bg.strip()
                if fg!='auto' and not 0<=float(fg)<=1: raise ValueError('前台音量请填写 auto 或 0～1。')
                if not 0<=float(bg)<=1: raise ValueError('后台音量请填写 0～1。')
                template=dict(mode='standard',fg_volume=fg,bg_volume=bg,easing='null')
            doc=core.ConfigDoc(core.CONFIG_PATH); doc.backup()
            if not doc.update(name,template): raise ValueError('这条规则已被移除，请刷新列表。')
            self.refresh_entries(); self.toast('规则已更新。'+self.apply_changes(True))
        def edit_rule(self,name):
            self.refresh_entries()
            rule,is_default=self.rules.get(name.lower(),({},False))
            win=self.dialog('编辑静音规则'); body=win.body
            self.label(body,display_name(name),16,True).pack(anchor='w')
            self.label(body,name,9,color=COLORS['muted']).pack(anchor='w',pady=(self.s(4),self.s(18)))
            mode=tk.StringVar(value='null' if is_default else 'standard')
            fg=tk.StringVar(value=str(rule.get('fg_volume','auto'))); bg=tk.StringVar(value=str(rule.get('bg_volume',0)))
            self.label(body,'音量规则',10,True).pack(anchor='w',pady=(0,self.s(8)))
            inputs=[]
            def sync():
                for e in inputs: e.configure(state='disabled' if mode.get()=='null' else 'normal')
            for val,text in [('standard','单独设置此应用'),('null','使用全局默认设置')]:
                tk.Radiobutton(body,text=text,value=val,variable=mode,bg='white',activebackground='white',command=sync).pack(anchor='w',pady=self.s(3))
            grid=tk.Frame(body,bg='white'); grid.pack(fill='x',pady=self.s(14)); grid.grid_columnconfigure(1,weight=1)
            for i,(label,var) in enumerate([('前台音量',fg),('后台音量',bg)]):
                self.label(grid,label,10).grid(row=i,column=0,sticky='w',padx=(0,self.s(20)),pady=self.s(8))
                e=tk.Entry(grid,textvariable=var,font=('Microsoft YaHei UI',11),relief='flat',highlightthickness=1,
                           highlightbackground=COLORS['border'],highlightcolor=COLORS['blue'])
                e.grid(row=i,column=1,sticky='ew',ipady=self.s(9)); inputs.append(e)
            self.label(body,'前台填 auto 可自动恢复原音量；数值范围为 0～1。\n后台填 0 表示完全静音。',9,color=COLORS['muted'],justify='left').pack(anchor='w')
            error=self.label(body,'',9,color=COLORS['red']); error.pack(anchor='w',pady=self.s(8))
            def save():
                try: self.save_rule(name,mode.get(),fg.get(),bg.get())
                except Exception as exc: error.configure(text='保存失败：'+str(exc)); return
                win.destroy()
            actions=tk.Frame(body,bg='white'); actions.pack(fill='x',pady=(self.s(8),0))
            self.button(actions,'保存更改',save,primary=True).pack(side='right')
            self.button(actions,'取消',win.destroy,quiet=True).pack(side='right',padx=self.s(8)); sync()
        def apply_changes(self,changed):
            if not changed: return '没有配置变化。'
            if core.is_running(): return '配置自动生效。'
            if self.restart_after_add.get(): self.restart_muter(silent=True); return '正在启动静音服务。'
            return '静音服务未运行，请到设置页启动。'
        def muter_running(self): return core.is_running()
        def _auto_ensure_muter(self):
            if self.var_auto_start.get() and not core.is_running(): self.restart_muter(silent=True)
        def restart_muter(self,silent=False):
            if self.restarting: return False
            exe=core.find_muter_exe()
            if not exe: self.toast('没有找到静音服务，请检查程序文件。',error=True); return False
            self.restarting=True; self.toast('正在启动 / 重启服务，等待音量恢复…')
            def job():
                try:
                    if core.is_running():
                        if not core.request_stop(): raise RuntimeError('无法请求安全退出，请从托盘退出后重试。')
                        deadline=time.monotonic()+8
                        while (core.is_running() or core.supervisor_running()) and time.monotonic()<deadline: time.sleep(.1)
                        if core.is_running() or core.supervisor_running(): raise RuntimeError('服务未完成音量恢复，重启已取消。')
                    subprocess.Popen([exe],cwd=core.APP_DIR,close_fds=True)
                    deadline=time.monotonic()+10
                    while not core.is_running() and time.monotonic()<deadline: time.sleep(.1)
                    if not core.is_running(): raise RuntimeError('服务没有就绪，请查看 logs 中的日志。')
                    self.messages.put(('service','静音服务已就绪，配置自动生效。'))
                except Exception as exc: self.messages.put(('service_error','启动失败：'+str(exc)))
            threading.Thread(target=job,daemon=True,name='ManagerServiceControl').start(); return True
        def _update_service(self):
            running=core.is_running(); color=COLORS['green'] if running else COLORS['muted']
            self.service_label.configure(text='静音服务运行中' if running else ('服务启动中' if self.restarting else '静音服务未运行'))
            self.service_dot.delete('all'); self.service_dot.create_oval(1,1,self.s(9),self.s(9),fill=color,outline=color)
        def _tick(self):
            if self.closed: return
            self._update_service()
            try:
                if os.stat(core.CONFIG_PATH).st_mtime_ns!=self._config_stamp: self.refresh_entries(); self.toast('配置已更新，自动生效。')
            except OSError: pass
            if self.auto_refresh.get() and time.monotonic()-getattr(self,'_last_refresh',0)>=5:
                self.refresh_processes(); self._last_refresh=time.monotonic()
            self.root.after(1500,self._tick)
        def _save_ui_settings(self):
            core.save_settings(dict(auto_start_muter=self.var_auto_start.get(),restart_after_add=self.restart_after_add.get(),
                                    template=self.template_var.get(),filter_mode=self.filter_mode.get(),auto_refresh=self.auto_refresh.get()))
        def toggle_boot(self):
            enabled=self.var_boot_autostart.get(); exe=core.find_muter_exe()
            if enabled and not exe: self.var_boot_autostart.set(False); self.toast('没有找到静音服务。',error=True); return
            if core.set_boot_autostart(exe if enabled else None): self.toast('已开启开机自动启动。' if enabled else '已关闭开机自动启动。')
            else: self.var_boot_autostart.set(not enabled); self.toast('开机启动设置失败，请重试。',error=True)
        def do_backup(self):
            self.doc=core.ConfigDoc(core.CONFIG_PATH)
            try:
                dst=self.doc.backup(); self.toast('备份已保存到 config_backups。' if dst else '配置文件不存在，无法备份。')
            except Exception as exc: self.toast('备份失败：'+str(exc),error=True)
        def restore_backup(self):
            pick=filedialog.askopenfilename(parent=self.root,title='选择要恢复的备份',initialdir=core.BACKUP_DIR,filetypes=[('YAML','*.yaml'),('所有文件','*.*')])
            if not pick: return
            try:
                read_rules(pick)
                if not messagebox.askyesno('恢复配置','恢复会覆盖当前规则。当前配置将先备份。',parent=self.root): return
                self.doc=core.ConfigDoc(core.CONFIG_PATH); self.doc.backup()
                temp=core.CONFIG_PATH+'.tmp'; shutil.copyfile(pick,temp); os.replace(temp,core.CONFIG_PATH)
                self.refresh_entries(); self.toast('配置已恢复。'+self.apply_changes(True))
            except Exception as exc: self.toast('恢复失败：'+str(exc),error=True)
        def open_config(self):
            try: os.startfile(core.CONFIG_PATH)
            except Exception as exc: self.toast('打开配置失败：'+str(exc),error=True)
        def health_check(self):
            self.refresh_entries(); live={r['name'].lower():r['name'] for r in self.proc_rows}
            mismatches=[(e.name,live[e.name.lower()]) for e in self.doc.entries if e.name.lower() in live and e.name!=live[e.name.lower()]]
            duplicates=self.doc.duplicates()
            if not mismatches and not duplicates: self.toast('未发现重复条目或大小写问题。'); return
            lines=['重复条目：'+', '.join(duplicates)] if duplicates else []
            lines += [f'{old} → {new}' for old,new in mismatches]
            if mismatches and messagebox.askyesno('配置检查','\n'.join(lines)+'\n\n修正以上大小写？',parent=self.root):
                self.doc.backup()
                for old,new in mismatches: self.doc.rename(old,new)
                self.refresh_entries(); self.toast('大小写已修正。'+self.apply_changes(True))
            elif duplicates: self.toast('发现重复条目，请在规则页移除重复规则。',error=True)
        def close(self):
            self.closed=True; self.root.destroy()
    return App
