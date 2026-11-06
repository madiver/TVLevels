# Contributing

Contributions are welcome for level detection, explanations, the native macOS
panel, installation, documentation, and regression coverage. Please discuss large
changes in an issue before starting them.

## Development setup

Use the requirements in [README.md](README.md). Prepare the pinned bridge without
installing applications or changing the Dock:

```sh
python3 install.py --dependency-only
python3 -m unittest discover -s python -p 'test_*.py' -q
python3 panel/build.py
```

Tests run with synthetic candles, fake clients, and a local chart fixture. They
do not require a TradingView account or a live chart. The build requires macOS
and Swift. Use `Daily Levels.command` to open the built panel after setup.

The macOS CI workflow runs the same unit suite, prepares the pinned dependency,
and builds the panel. It does not install shortcuts, launch TradingView, or
exercise a signed-in chart. A green build is not live UI qualification.

## Preserve chart and user state

Bind each operation to the selected pane. Preserve other panes and unowned
drawings, and restore the original timeframe and session on success and failure.
Do not introduce broker orders or cancellations. Run UI verification on macOS.

Keep the app bundle identifier stable so category choices, theme, and panel
geometry survive updates. Preserve drawing ownership and archived snapshots.
Never commit local configuration, captured chart data, generated bundles, or
personal diagnostics; `.gitignore` covers the standard local paths.

When a change needs manual chart verification, use a disposable layout and record
the macOS and TradingView Desktop versions, selected pane, symbol, timeframe,
session, and actions tested. Source tests, a successful build, an installed UI,
and a chart drawing check are different levels of evidence; report each accurately.

## Updating TradingView MCP

The dependency is maintained at [madiver/TradingView-MCP](https://github.com/madiver/TradingView-MCP).
Update its full commit SHA in `dependencies.lock.json`, review its changes and
license notices, and rerun installation. Verify the MCP stdio handshake and the
tools TVLevels uses, then repeat the relevant macOS checks. Do not replace the
pin with a branch name or copy a developer checkout's private state.

## Pull requests

Explain the problem, resulting behavior, and checks performed. Add focused
regression tests for behavior changes. For detection changes, include a small
synthetic candle example and the expected levels rather than private chart exports.
Preserve license and attribution notices. Contributions are provided under this
repository's [MIT License](LICENSE).

For vulnerabilities, use [SECURITY.md](SECURITY.md). Community expectations are in
[CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
