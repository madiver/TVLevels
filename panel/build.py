#!/usr/bin/env python3
"""Build the local native floating panel; no additional dependencies."""
import json
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'python'))
from runtime_config import resolve_mcp_root
mcp_root = resolve_mcp_root(root)
app = root / '.local/Daily Levels.app'
contents = app / 'Contents'
exe = contents / 'MacOS/DailyLevels'
resources = contents / 'Resources'
exe.parent.mkdir(parents=True, exist_ok=True)
resources.mkdir(parents=True, exist_ok=True)
python = sys.executable
node = shutil.which('node')
if not python or not node:
    raise SystemExit('Python 3 and Node are required.')
(resources / 'runtime.json').write_text(json.dumps(dict(root=str(root), python=python, nodeDirectory=str(Path(node).parent), mcpRoot=str(mcp_root))))
(contents / 'Info.plist').write_bytes(plistlib.dumps(dict(CFBundleExecutable='DailyLevels', CFBundleIdentifier='local.tradingview.dailylevels', CFBundleName='Daily Levels', CFBundleDisplayName='Daily Levels', CFBundlePackageType='APPL', CFBundleVersion='3', CFBundleShortVersionString='1.2', CFBundleIconFile='DailyLevels.icns', LSUIElement=True, NSHighResolutionCapable=True)))
catalog = subprocess.check_output([python,str(root / 'python/daily_levels.py'),'--catalog'])
(resources / 'categories.json').write_bytes(catalog)
source = root / 'panel/main.swift'
if not exe.exists() or source.stat().st_mtime > exe.stat().st_mtime:
    subprocess.run(['swiftc', '-swift-version', '5', '-O', str(source), '-o', str(exe)], check=True)
icon_source = root / 'panel/assets/DailyLevels.png'
icon = resources / 'DailyLevels.icns'
if not icon.exists() or icon_source.stat().st_mtime > icon.stat().st_mtime:
    with tempfile.TemporaryDirectory(dir=root / '.local') as temporary:
        iconset = Path(temporary) / 'DailyLevels.iconset'
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                name = f'icon_{size}x{size}' + ('@2x' if scale == 2 else '') + '.png'
                subprocess.run(['sips', '-z', str(size * scale), str(size * scale), str(icon_source),
                                '--out', str(iconset / name)], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(icon)], check=True)
subprocess.run(['codesign', '--force', '--sign', '-', str(app)], check=True, capture_output=True)
print(app)
