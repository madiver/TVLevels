# TVLevels instructions

- This is the macOS-only Daily Levels app. Run UI verification only on macOS.
- TradingView MCP is an external checkout. Resolve it through
  `python/runtime_config.py`; never assume `src/server.js` belongs to this repo.
  The default is the published revision in `dependencies.lock.json`, prepared by
  `install.py` in `.local/dependencies/`. Preserve explicit developer overrides;
  use `install.py --use-pinned` when intentionally migrating local settings.
- Preserve saved checkboxes, theme, panel geometry, drawing ownership and archived
  snapshots. Keep private runtime state out of Git.
- Bind chart operations to the selected pane. Preserve other panes, unowned
  drawings, and the original timeframe/session, including on failures.
- Use MCP `chart_get_state`, `data_get_study_values`, and `quote_get` before live
  chart inspection. Use a chart screenshot when visual confirmation matters.
- Keep all verification free of broker orders and cancellations.
- Validate with `python3 -m unittest discover -s python -p 'test_*.py' -q` and
  `python3 panel/build.py`. Tests alone do not verify the installed launcher or UI.
- Retain unrelated changes in the separate MCP repository.

## Subagent context policy

- Explicitly set `fork_turns` when spawning a subagent.
- Prefer `none` for independent, well-defined tasks and give a self-contained handoff.
- Use `all` only when broader conversation history is necessary.
- Request concise findings and file references rather than raw logs.
