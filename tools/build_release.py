"""Build a Windows distribution without private configuration or temporary unpacking."""
from pathlib import Path
from importlib import metadata
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def licenses(package):
    target=package/'licenses'; target.mkdir(exist_ok=True)
    components=('injector','psutil','pycaw','pystray','pywin32','PyYAML','Pillow','comtypes',
                'typing_extensions','six','PyInstaller','pyinstaller-hooks-contrib','altgraph','packaging','setuptools','pefile')
    index=['Third-party notices', '', 'MuteFlow is distributed under the MIT license in LICENSE.',
           'Dependencies retain their respective licenses.', '']
    for name in components:
        try: dist=metadata.distribution(name)
        except metadata.PackageNotFoundError: continue
        index.append(f'{dist.metadata["Name"]} {dist.version}')
        license_text=dist.metadata.get('License-Expression') or dist.metadata.get('License') or 'See component license files.'
        index.append(license_text)
        for item in dist.files or []:
            if 'license' not in item.name.lower() and 'copying' not in item.name.lower() and 'notice' not in item.name.lower(): continue
            source=Path(dist.locate_file(item))
            if not source.is_file() or source.suffix.lower() in ('.py','.pyc','.dll','.pyd'): continue
            dest=target/name; dest.mkdir(exist_ok=True)
            shutil.copy2(source,dest/item.name)
            index.append(f'  licenses/{name}/{item.name}')
        index.append('')
    python_license=Path(sys.base_prefix)/'LICENSE.txt'
    if python_license.is_file(): shutil.copy2(python_license,target/'Python-LICENSE.txt')
    (package/'THIRD_PARTY_NOTICES.txt').write_text('\n'.join(index),encoding='utf-8')

def build():
    if os.name!='nt' or struct.calcsize('P')!=8:
        raise SystemExit('Build on Windows with 64-bit Python.')
    version=(ROOT/'VERSION').read_text().strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[A-Za-z0-9.]+)?',version): raise SystemExit('Invalid VERSION.')
    work=ROOT/'build'; dist=ROOT/'dist'; work.mkdir(exist_ok=True); dist.mkdir(exist_ok=True)
    generated=work/'programs'
    common=['--noconfirm','--onedir','--windowed','--icon',str(ROOT/'resource/mute.ico'),
            '--distpath',str(generated),'--specpath',str(work),
            '--exclude-module','numpy','--exclude-module','scipy','--exclude-module','matplotlib',
            '--exclude-module','IPython','--exclude-module','pytest']
    for entry,name,runtime,extra in [
        ('main.py','background_muter','muter_runtime',['--add-data',f'{ROOT / "resource"};resource']),
        ('muter_gui.py','后台静音助手','manager_runtime',['--hidden-import','win32com.client',
            '--hidden-import','win32gui','--hidden-import','win32con','--hidden-import','win32ui'])]:
        command=[sys.executable,'-m','PyInstaller',*common,'--workpath',str(work/name),
                 '--name',name,'--contents-directory',runtime,*extra,str(ROOT/entry)]
        subprocess.run(command,cwd=ROOT,check=True)
    package=work/'release'/f'MuteFlow-v{version}'
    package.mkdir(parents=True,exist_ok=True)
    for name in ('background_muter','后台静音助手'):
        shutil.copytree(generated/name,package,dirs_exist_ok=True)
    # Always distribute clean sample rules, never the maintainer's config.yaml.
    shutil.copy2(ROOT/'config.example.yaml',package/'config.yaml')
    for name in ('LICENSE','README.md','CHANGELOG.md','VERSION'):
        shutil.copy2(ROOT/name,package/name)
    (package/'开始使用.txt').write_text(
        '后台静音助手 · MuteFlow\n\n完整解压后，双击“后台静音助手.exe”。\n'
        '通过“添加应用”设置规则，在“设置与备份”开启开机启动。\n'
        '请保留 manager_runtime 和 muter_runtime 配套目录。\n'
        '关闭管理器后服务继续运行；托盘“退出”才会停止服务。\n'
        '原项目：lingkai5wu/AutoMuteBG，MIT License，详见 LICENSE。\n',encoding='utf-8-sig')
    shutil.copytree(ROOT/'docs',package/'docs',dirs_exist_ok=True)
    licenses(package)
    archive=dist/f'MuteFlow-v{version}-windows-x64.zip'
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in sorted(package.rglob('*')):
            if path.is_file(): z.write(path,path.relative_to(package.parent))
    digest=hashlib.sha256(archive.read_bytes()).hexdigest()
    checksum=dist/'SHA256SUMS.txt'; checksum.write_text(f'{digest}  {archive.name}\n',encoding='utf-8')
    print(f'Release: {archive}\nSHA256: {digest}')

if __name__=='__main__': build()
