"""Keep TVLevels' code and private state separate from its MCP dependency."""
import json
import os
from pathlib import Path

from mcp_dependency import dependency_lock, dependency_ready, managed_mcp_root


def local_settings(root):
    path = Path(root) / 'tvlevels.json'
    if not path.exists():
        return {}
    try:
        config = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f'Cannot read TVLevels settings at {path}: {error}') from error
    if not isinstance(config, dict):
        raise ValueError('tvlevels.json must contain a JSON object')
    return config


def resolve_mcp_root(root, environ=None):
    root = Path(root).resolve()
    environ = os.environ if environ is None else environ
    configured = environ.get('TVLEVELS_MCP_ROOT')
    if configured is None:
        config = local_settings(root)
        if 'mcp_root' not in config:
            spec = dependency_lock(root)
            dependency = managed_mcp_root(root, spec)
            if not dependency_ready(dependency, spec):
                raise RuntimeError('The pinned TradingView MCP dependency is not installed. '
                                   'Run python3 install.py from TVLevels first.')
            return dependency
        configured = config['mcp_root']
    if not isinstance(configured, str) or not configured.strip():
        raise ValueError('TVLEVELS_MCP_ROOT or tvlevels.json mcp_root must be a nonempty path')
    dependency = Path(configured).expanduser()
    if not dependency.is_absolute():
        dependency = root / dependency
    dependency = dependency.resolve()
    if not (dependency / 'src/server.js').is_file() or not (dependency / 'package.json').is_file():
        raise RuntimeError(f'TradingView MCP was not found at {dependency}. '
                           'Run python3 install.py --use-pinned, or set TVLEVELS_MCP_ROOT '
                           'or mcp_root in TVLevels/tvlevels.json to a developer checkout.')
    return dependency
