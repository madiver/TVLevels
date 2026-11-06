#!/usr/bin/env python3
"""Install a stable Applications link and add the Daily Levels panel to the Dock."""
import json
from pathlib import Path
import plistlib
import secrets
import subprocess
import sys
import uuid
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / '.local/Daily Levels.app'
DESTINATION = Path.home() / 'Applications/Daily Levels.app'
IDENTIFIER = 'local.tradingview.dailylevels'


def link_application(destination, application):
    """Retarget only our managed Applications link, preserving unrelated apps."""
    if destination.is_symlink():
        if destination.resolve() == application.resolve():
            return False
        info = destination.resolve() / 'Contents/Info.plist'
        if not info.is_file() or plistlib.loads(info.read_bytes()).get('CFBundleIdentifier') != IDENTIFIER:
            raise RuntimeError('Applications link does not point to Daily Levels; leaving it untouched')
    elif destination.exists():
        raise RuntimeError('Applications destination already exists; leaving it untouched')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temporary.symlink_to(application, target_is_directory=True)
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def matches(tile):
    data = tile.get('tile-data', {})
    if data.get('bundle-identifier') == IDENTIFIER:
        return True
    url = data.get('file-data', {}).get('_CFURLString', '')
    parsed = urlparse(url)
    return parsed.scheme == 'file' and Path(unquote(parsed.path)).resolve() == APP.resolve()


def points_to_path(data, destination):
    # Dock may normalize the trailing slash and percent-encode spaces.
    parsed = urlparse(data.get('file-data', {}).get('_CFURLString', ''))
    return parsed.scheme == 'file' and Path(unquote(parsed.path)) == destination


def install():
    subprocess.run([sys.executable, str(ROOT / 'panel/build.py')], check=True, stdout=subprocess.DEVNULL)
    link_updated = link_application(DESTINATION, APP)

    dock = plistlib.loads(subprocess.check_output(['defaults', 'export', 'com.apple.dock', '-']))
    tiles = dock.get('persistent-apps', [])
    matching = [tile for tile in tiles if matches(tile)]
    changed = False
    if not matching:
        guid = secrets.randbits(32)
        while any(tile.get('GUID') == guid for tile in tiles):
            guid = secrets.randbits(32)
        tile = {'GUID':guid, 'tile-type':'file-tile', 'tile-data':{
            'file-data':{'_CFURLString':DESTINATION.as_uri() + '/', '_CFURLStringType':15},
            'file-label':'Daily Levels', 'file-type':41, 'bundle-identifier':IDENTIFIER}}
        neighbors = [i for i, t in enumerate(tiles) if t.get('tile-data', {}).get('bundle-identifier')
                     in ('com.markbennett.tradingview-debug-launcher', 'com.tradingview.tradingviewapp')]
        tiles.insert(neighbors[-1] + 1 if neighbors else len(tiles), tile)
        changed = True
    else:
        for tile in matching:
            data = tile['tile-data']
            expected = {'_CFURLString':DESTINATION.as_uri() + '/', '_CFURLStringType':15}
            if link_updated or not points_to_path(data, DESTINATION) or data.get('file-label') != 'Daily Levels':
                data['file-data'] = expected
                data['file-label'] = 'Daily Levels'
                data['bundle-identifier'] = IDENTIFIER
                for key in ('book', 'file-mod-date', 'parent-mod-date'):
                    data.pop(key, None)
                changed = True
    if changed:
        backup = ROOT / '.local/panel/dock-before.plist'
        backup.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            # Preserve the actual original list, before inserting our tile.
            original = subprocess.check_output(['defaults', 'export', 'com.apple.dock', '-'])
            backup.write_bytes(original)
            backup.chmod(0o600)
        subprocess.run(['defaults', 'write', 'com.apple.dock', 'persistent-apps', '-array',
                        *(plistlib.dumps(tile).decode() for tile in tiles)], check=True)
        subprocess.run(['killall', 'Dock'], check=True)
    verified = plistlib.loads(subprocess.check_output(['defaults', 'export', 'com.apple.dock', '-']))
    if not any(matches(tile) for tile in verified.get('persistent-apps', [])):
        raise RuntimeError('Dock shortcut was not persisted')
    print(json.dumps({'application':str(DESTINATION), 'dock_updated':changed,
                      'dock_shortcuts':sum(matches(tile) for tile in verified.get('persistent-apps', []))}))


if __name__ == '__main__':
    install()
