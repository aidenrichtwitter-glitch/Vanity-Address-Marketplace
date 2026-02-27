import os
import sys

if getattr(sys, 'frozen', False):
    base = sys._MEIPASS

    search_paths = [
        os.path.join(base, "PySide6", "plugins"),
        os.path.join(base, "PySide6", "Qt", "plugins"),
        os.path.join(base, "PySide6", "Qt6", "plugins"),
        os.path.join(base, "plugins"),
        os.path.join(base, "qt6", "plugins"),
        os.path.join(base, "Qt", "plugins"),
    ]

    for sp in search_paths:
        platforms_dir = os.path.join(sp, "platforms")
        if os.path.isdir(platforms_dir):
            os.environ["QT_PLUGIN_PATH"] = sp
            os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = platforms_dir
            break

    pyside6_path = os.path.join(base, "PySide6")
    if os.path.isdir(pyside6_path):
        os.environ["PATH"] = pyside6_path + os.pathsep + base + os.pathsep + os.environ.get("PATH", "")
    else:
        os.environ["PATH"] = base + os.pathsep + os.environ.get("PATH", "")
