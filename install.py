#!/usr/bin/env python3
"""Prepare the pinned bridge and install the macOS apps without starting a chart."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'python'))
from mcp_dependency import ensure_dependency, verify_node_dependencies
from runtime_config import local_settings, resolve_mcp_root


def preflight(dependency_only=False, skip_launcher=False):
    if sys.platform != 'darwin':
        raise RuntimeError('TVLevels is a macOS app. Run this installer on your Mac.')
    if sys.version_info < (3, 9):
        raise RuntimeError('Python 3.9 or later is required.')
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    try:
        ZoneInfo('America/New_York')
    except ZoneInfoNotFoundError as error:
        raise RuntimeError('Python needs IANA time-zone data (install the tzdata package).') from error
    for program in ('git', 'node', 'npm'):
        if not shutil.which(program):
            raise RuntimeError(f'{program} was not found. Install Git/Xcode Command Line Tools '
                               'and Node.js 22, 24, or 26, then reopen Terminal.')
    version = subprocess.check_output(['node', '--version'], text=True).strip()
    if int(version.lstrip('v').split('.')[0]) not in (22, 24, 26):
        raise RuntimeError(f'Node.js {version} is not supported by the pinned MCP. Use Node 22, 24, or 26.')
    if dependency_only:
        return
    if not shutil.which('swiftc'):
        raise RuntimeError('Install Apple Command Line Tools with xcode-select --install, then rerun this installer.')
    subprocess.run(['xcrun', '--find', 'swiftc'], check=True, stdout=subprocess.DEVNULL)
    if not skip_launcher:
        if os.environ.get('TV_CDP_PORT', '9222') != '9222':
            raise RuntimeError('The supplied TradingView Debug launcher uses port 9222. '
                               'Use --skip-tradingview-launcher to retain your custom launcher/port.')
        if not any((path / 'Contents/MacOS/TradingView').is_file() for path in
                   (Path('/Applications/TradingView.app'), Path.home() / 'Applications/TradingView.app')):
            raise RuntimeError('Install TradingView Desktop in Applications first, then rerun this installer.')


@contextmanager
def pinned_settings(root, enabled):
    """Switch only the dependency setting, backing up bytes and rolling back on failure."""
    if not enabled:
        yield
        return
    if 'TVLEVELS_MCP_ROOT' in os.environ:
        raise RuntimeError('Unset TVLEVELS_MCP_ROOT before using --use-pinned.')
    path = root / 'tvlevels.json'
    settings = local_settings(root)
    if 'mcp_root' not in settings:
        yield
        return
    original = path.read_bytes()
    backups = root / '.local/settings-backups'
    backups.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='tvlevels-', suffix='.json', dir=backups, delete=False) as backup:
        backup.write(original)
        backup_path = Path(backup.name)
    del settings['mcp_root']
    replacement = (json.dumps(settings, indent=2) + '\n').encode()
    path.write_bytes(replacement)
    print(f'Previous local settings saved to {backup_path}', flush=True)
    try:
        yield
    except BaseException:
        # Do not overwrite a concurrent settings edit made while installing.
        if path.is_file() and path.read_bytes() == replacement:
            path.write_bytes(original)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dependency-only', action='store_true', help='prepare MCP without installing either app')
    parser.add_argument('--use-pinned', action='store_true', help='back up and remove a local mcp_root override')
    parser.add_argument('--skip-tradingview-launcher', action='store_true', help='keep your existing TradingView launch setup')
    args = parser.parse_args(argv)
    try:
        # Reject bad settings before downloads or changes to installed apps.
        local_settings(ROOT)
        if args.use_pinned and 'TVLEVELS_MCP_ROOT' in os.environ:
            raise RuntimeError('Unset TVLEVELS_MCP_ROOT before using --use-pinned.')
        preflight(args.dependency_only, args.skip_tradingview_launcher)
        managed = ensure_dependency(ROOT)
        with pinned_settings(ROOT, args.use_pinned):
            selected = resolve_mcp_root(ROOT)
            if selected != managed:
                print(f'Keeping your developer MCP override: {selected}', flush=True)
                verify_node_dependencies(selected)
            if args.dependency_only:
                print(f'MCP ready: {selected}', flush=True)
                return 0
            subprocess.run([sys.executable, str(ROOT / 'panel/install.py')], check=True)
            if not args.skip_tradingview_launcher:
                subprocess.run([sys.executable, str(managed / 'launcher/install.py')], check=True)
        launch = 'your configured TradingView launcher' if args.skip_tradingview_launcher else 'TradingView Debug'
        print(f'\nTVLevels installed. Open {launch}, sign in, and select a chart.\n'
              'Then open Daily Levels from Applications or the Dock.\n'
              'Keep this TVLevels folder: the installed app links to it.', flush=True)
        return 0
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'Installation stopped: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
