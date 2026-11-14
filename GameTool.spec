# Build: python -m PyInstaller GameTool.spec  ->  dist\GameTool.exe
a = Analysis(
    ["main.py"],
    datas=[("data/fonts", "data/fonts"), ("assets/icon.ico", "assets")],
    excludes=["numpy"],
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="GameTool",
    icon="assets/icon.ico",
    console=False,
    # the hooks don't receive the keys of games running as administrator
    uac_admin=True,
    upx=False,
)
