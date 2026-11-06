"""Install an isolated, immutable MCP revision without touching developer checkouts."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tempfile

READY_FILE = '.tvlevels-ready.json'


def dependency_lock(root):
    try:
        spec = json.loads((Path(root) / 'dependencies.lock.json').read_text())['tradingview_mcp']
        if (not isinstance(spec['repository'], str) or
                not spec['repository'].startswith('https://github.com/') or
                not re.fullmatch(r'[0-9a-f]{40}', spec['commit'])):
            raise ValueError('Expected a GitHub HTTPS repository and a full commit SHA')
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f'Cannot read the TradingView MCP dependency pin: {error}') from error
    return {'repository': spec['repository'], 'commit': spec['commit']}


def managed_mcp_root(root, spec=None):
    spec = dependency_lock(root) if spec is None else spec
    return Path(root).resolve() / '.local/dependencies' / ('tradingview-mcp-' + spec['commit'])


def installation_record(path, spec):
    return dict(spec, package_lock_sha256=hashlib.sha256((path / 'package-lock.json').read_bytes()).hexdigest())


def dependency_ready(path, spec):
    try:
        return ((path / 'src/server.js').is_file() and
                (path / 'node_modules/.package-lock.json').is_file() and
                json.loads((path / READY_FILE).read_text()) == installation_record(path, spec))
    except (OSError, ValueError):
        return False


def verify_node_dependencies(path):
    # Import the runtime dependencies only; never connect to TradingView.
    subprocess.run(['node', '--input-type=module', '-e',
                    "await import('@modelcontextprotocol/sdk/server/mcp.js'); "
                    "await import('chrome-remote-interface'); await import('zod');"],
                   cwd=path, check=True, timeout=30)


def verify_checkout(path, spec):
    head = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
    changes = subprocess.check_output(['git', '-C', str(path), 'status', '--porcelain',
                                       '--untracked-files=no'], text=True).strip()
    if head != spec['commit'] or changes:
        raise RuntimeError(f'Managed MCP source has changed at {path}. '
                           'Move that directory aside and rerun python3 install.py; it will not be overwritten.')


def ensure_dependency(root):
    spec = dependency_lock(root)
    destination = managed_mcp_root(root, spec)
    if destination.exists():
        if not dependency_ready(destination, spec):
            raise RuntimeError(f'Managed MCP installation is incomplete at {destination}. '
                               'Move that directory aside and rerun python3 install.py.')
        verify_checkout(destination, spec)
        verify_node_dependencies(destination)
        print(f'Using TradingView MCP {spec["commit"][:12]} (already installed).', flush=True)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Publish only after both Git and npm succeed. A failed attempt leaves no
    # half-installed dependency at the path used by the panel.
    with tempfile.TemporaryDirectory(prefix='.mcp-install-', dir=destination.parent) as temporary:
        checkout = Path(temporary) / 'checkout'
        checkout.mkdir()
        print(f'Downloading TradingView MCP {spec["commit"][:12]}…', flush=True)
        subprocess.run(['git', 'init', '--quiet', str(checkout)], check=True, timeout=30)
        subprocess.run(['git', '-C', str(checkout), 'remote', 'add', 'origin', spec['repository']],
                       check=True, timeout=30)
        subprocess.run(['git', '-C', str(checkout), 'fetch', '--quiet', '--depth=1', 'origin', spec['commit']],
                       check=True, timeout=180)
        subprocess.run(['git', '-C', str(checkout), 'checkout', '--quiet', '--detach', 'FETCH_HEAD'],
                       check=True, timeout=30)
        verify_checkout(checkout, spec)
        subprocess.run(['npm', 'ci', '--ignore-scripts', '--no-audit', '--no-fund', '--include=dev'],
                       cwd=checkout, check=True, timeout=300)
        verify_checkout(checkout, spec)
        verify_node_dependencies(checkout)
        if not (checkout / 'node_modules/.package-lock.json').is_file():
            raise RuntimeError('npm did not create a complete dependency installation; rerun python3 install.py.')
        (checkout / READY_FILE).write_text(json.dumps(installation_record(checkout, spec), indent=2) + '\n')
        checkout.rename(destination)
    return destination
