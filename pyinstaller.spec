# -*- mode: python ; coding: utf-8 -*-

# Run `pyinstaller pyinstaller.spec` to generate the binary.


block_cipher = None

open("_harbormaster_pyinstaller.py", "w").write("""
from docker_harbormaster.cli import cli

if __name__ == "__main__":
    cli()
""")

a = Analysis(['_harbormaster_pyinstaller.py'],
             pathex=['.'],
             binaries=[],
             datas=[],
             hiddenimports=[],
             hookspath=[],
             runtime_hooks=[],
             excludes=[],
             win_no_prefer_redirects=False,
             win_private_assemblies=False,
             cipher=block_cipher,
             noarchive=False)
pyz = PYZ(a.pure, a.zipped_data,
             cipher=block_cipher)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          [],
          name='harbormaster',
          debug=False,
          bootloader_ignore_signals=False,
          strip=False,
          upx=True,
          upx_exclude=[],
          runtime_tmpdir=None,
          console=True )

os.remove("_harbormaster_pyinstaller.py")
