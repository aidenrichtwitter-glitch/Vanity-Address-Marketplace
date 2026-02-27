import os
import sys

if getattr(sys, 'frozen', False):
    base = sys._MEIPASS

    pyside6_path = os.path.join(base, "PySide6")
    plugin_path = os.path.join(pyside6_path, "plugins")
    platforms_path = os.path.join(plugin_path, "platforms")

    path_env = os.environ.get("PATH", "")
    extra_paths = [base, pyside6_path]
    for p in extra_paths:
        if os.path.isdir(p) and p not in path_env:
            path_env = p + os.pathsep + path_env
    os.environ["PATH"] = path_env

    if sys.platform == "win32":
        if hasattr(os, "add_dll_directory"):
            for p in extra_paths:
                if os.path.isdir(p):
                    os.add_dll_directory(p)

    if os.path.isdir(plugin_path):
        os.environ["QT_PLUGIN_PATH"] = plugin_path

    if os.path.isdir(platforms_path):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = platforms_path
    elif os.path.isdir(plugin_path):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugin_path

    os.environ["QT_QPA_PLATFORM"] = "windows" if sys.platform == "win32" else "xcb"
