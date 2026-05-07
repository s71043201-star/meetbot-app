# -*- mode: python ; coding: utf-8 -*-
# 核銷文件產生器 v39 — pywebview 版打包設定（onefile）

block_cipher = None

a = Analysis(
    ['app_webview.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('web_ui', 'web_ui'),
        ('word_templates', 'word_templates'),
    ],
    hiddenimports=[
        'webview',
        'webview.platforms.edgechromium',
        'webview.platforms.winforms',
        'clr_loader',
        'pythonnet',
        'docx',
        'docx2pdf',
        'openpyxl',
        'pypdf',
        'PIL',
        'win32com',
        'win32com.client',
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'customtkinter', 'matplotlib', 'numpy', 'pandas'],
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
    name='核銷文件產生器_v39',
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
    icon=None,
)
