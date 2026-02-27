import os
import sys

if getattr(sys, 'frozen', False):
    base = sys._MEIPASS
    plugin_path = os.path.join(base, "PySide6", "plugins")
    if os.path.isdir(plugin_path):
        os.environ["QT_PLUGIN_PATH"] = plugin_path
    pyside6_path = os.path.join(base, "PySide6")
    if os.path.isdir(pyside6_path):
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = os.path.join(pyside6_path, "plugins", "platforms")
