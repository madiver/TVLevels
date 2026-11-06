"""Shared native-panel and CLI drawing-theme preference."""
import json
from pathlib import Path


def read_theme(root=None):
    path=(root or Path(__file__).resolve().parents[1])/'.local/panel/theme.json'
    theme=json.loads(path.read_text()).get('theme','dark') if path.exists() else 'dark'
    if theme not in ('dark','light'):
        raise ValueError('Unknown saved drawing theme')
    return theme
