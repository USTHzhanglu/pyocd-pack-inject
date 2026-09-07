# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for pyocd-pack-inject (windowed GUI exe).

Build:  pyinstaller packaging/pyocd_pack_inject.spec --noconfirm
"""

import os
import sys

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_entry_point,
)
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo,
    FixedFileInfo,
    StringFileInfo,
    StringTable,
    StringStruct,
    VarFileInfo,
    VarStruct,
)

# Root of the repository (packaging/..) and the package source dir.
SP = os.path.abspath(os.path.join(SPECPATH, '..'))

sys.path.insert(0, os.path.join(SP, 'src'))
from pyocd_pack_inject.version import __appname__, __version__, __copyright__


def _ver_tuple(s):
    parts = s.split('.') + ['0'] * 4
    return tuple(int(p) for p in parts[:4])


_ver = _ver_tuple(__version__)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=_ver, prodvers=_ver, mask=0x3f, flags=0x0,
                      OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable('040904b0', [
            StringStruct('CompanyName', __copyright__),
            StringStruct('FileDescription', __appname__),
            StringStruct('FileVersion', __version__),
            StringStruct('InternalName', __appname__),
            StringStruct('OriginalFilename', __appname__ + '.exe'),
            StringStruct('ProductName', __appname__),
            StringStruct('ProductVersion', __version__),
        ])]),
        VarFileInfo([VarStruct('Translation', [1033, 1200])]),
    ],
)

# pyOCD is intentionally NOT bundled: the tool only maintains the
# cmsis-pack-manager cache files, which any pyOCD install reads.

block_cipher = None

a = Analysis(
    [os.path.join(SP, 'packaging', 'gui_main.py')],
    pathex=[os.path.join(SP, 'src')],
    binaries=collect_dynamic_libs('cmsis_pack_manager'),
    datas=collect_data_files('cmsis_pack_manager'),
    hiddenimports=['cmsis_pack_manager', 'tksheet', 'windnd'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # No networking/crypto in this app: drop the ssl stack (~4 MB of dlls)
    # plus other unused stdlib pulled in by generic hooks.
    excludes=['ssl', '_ssl', 'hashlib', '_hashlib', 'socket', 'select',
              'urllib', 'http', 'email', 'unittest', 'pydoc', 'doctest',
              'tkinter.test', 'tkinter.ttk.test'],
    optimize=2,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=__appname__,
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=version_info,
)
