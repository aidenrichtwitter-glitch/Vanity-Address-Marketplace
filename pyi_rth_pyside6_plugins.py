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

    search_dirs = [
        plugin_path,
        os.path.join(base, "plugins"),
        os.path.join(base, "qt6", "plugins"),
        base,
    ]

    resolved_plugin = None
    resolved_platforms = None
    for d in search_dirs:
        if os.path.isdir(d):
            if resolved_plugin is None:
                resolved_plugin = d
            pp = os.path.join(d, "platforms")
            if os.path.isdir(pp) and resolved_platforms is None:
                resolved_platforms = pp

    if resolved_plugin:
        os.environ["QT_PLUGIN_PATH"] = resolved_plugin
    if resolved_platforms:
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = resolved_platforms

    if sys.platform == "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "windows")
