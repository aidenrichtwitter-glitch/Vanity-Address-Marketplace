# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_dynamic_libs
from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.hooks import copy_metadata

datas = [('core/opencl/kernel.cl', 'core/opencl'), ('wordlist_3000.txt', '.'), ('core/marketplace/lit_action.js', 'core/marketplace'), ('C:\\Users\\Aiden\\AppData\\Local\\Packages\\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\\LocalCache\\local-packages\\Python312\\site-packages\\PySide6\\plugins', 'PySide6/plugins')]
binaries = []
hiddenimports = ['cffi', '_cffi_backend', 'pyopencl', 'nacl', 'nacl.signing', 'nacl.bindings', 'nacl.bindings.crypto_aead', 'nacl.bindings.crypto_box', 'nacl.bindings.crypto_generichash', 'nacl.bindings.crypto_hash', 'nacl.bindings.crypto_pwhash', 'nacl.bindings.crypto_scalarmult', 'nacl.bindings.crypto_secretbox', 'nacl.bindings.crypto_secretstream', 'nacl.bindings.crypto_shorthash', 'nacl.bindings.crypto_sign', 'nacl.bindings.randombytes', 'nacl.bindings.utils', 'base58', 'click', 'pynvml', 'solders', 'solana', 'solana.rpc', 'solana.rpc.api', 'requests', 'PySide6', 'PySide6.QtWidgets', 'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtNetwork', 'shiboken6']
datas += copy_metadata('PySide6')
datas += copy_metadata('shiboken6')
binaries += collect_dynamic_libs('PySide6')
binaries += collect_dynamic_libs('shiboken6')
tmp_ret = collect_all('pyopencl')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('nacl')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('cffi')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('solders')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('solana')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('requests')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['C:\\Users\\Aiden\\Desktop\\Gpu-Vanity-Miner\\pyi_rth_pyside6_plugins.py'],
    excludes=['PySide6.Qt3DAnimation', 'PySide6.Qt3DCore', 'PySide6.Qt3DExtras', 'PySide6.Qt3DInput', 'PySide6.Qt3DLogic', 'PySide6.Qt3DRender', 'PySide6.QtBluetooth', 'PySide6.QtCharts', 'PySide6.QtConcurrent', 'PySide6.QtDBus', 'PySide6.QtDataVisualization', 'PySide6.QtDesigner', 'PySide6.QtGraphs', 'PySide6.QtGraphsWidgets', 'PySide6.QtHelp', 'PySide6.QtHttpServer', 'PySide6.QtLocation', 'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets', 'PySide6.QtNetworkAuth', 'PySide6.QtNfc', 'PySide6.QtPdf', 'PySide6.QtPdfWidgets', 'PySide6.QtPositioning', 'PySide6.QtQuick', 'PySide6.QtQuick3D', 'PySide6.QtQuickControls2', 'PySide6.QtQuickTest', 'PySide6.QtQuickWidgets', 'PySide6.QtRemoteObjects', 'PySide6.QtScxml', 'PySide6.QtSensors', 'PySide6.QtSerialBus', 'PySide6.QtSerialPort', 'PySide6.QtSpatialAudio', 'PySide6.QtSql', 'PySide6.QtStateMachine', 'PySide6.QtSvg', 'PySide6.QtSvgWidgets', 'PySide6.QtTest', 'PySide6.QtTextToSpeech', 'PySide6.QtUiTools', 'PySide6.QtWebChannel', 'PySide6.QtWebEngineCore', 'PySide6.QtWebEngineQuick', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebSockets', 'PySide6.QtWebView', 'PySide6.QtXml', 'PySide6.QtQml', 'PySide6.QtOpenGL', 'PySide6.QtOpenGLWidgets', 'PySide6.QtPrintSupport', 'PySide6.QtAsyncio'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='solvanity',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
