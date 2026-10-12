import os
import sys


def resource_path(relative_path: str) -> str:
    """定位打包进程序的资源文件（resource 目录下的内容）。

    - 打包后（PyInstaller onefile）：资源被解包到 sys._MEIPASS
    - 源码运行：相对项目根目录

    原来用的是 pkg_resources.resource_filename，但 pkg_resources 属于 setuptools、
    已被官方标记为弃用，而且 PyInstaller 默认不会把它打进去（会报
    ModuleNotFoundError: No module named 'pkg_resources'）。这里改成直接算路径，
    不依赖 setuptools。
    """
    if getattr(sys, 'frozen', False):
        base = getattr(sys, '_MEIPASS', None) or os.path.dirname(os.path.abspath(sys.executable))
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative_path)
