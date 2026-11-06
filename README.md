# TVLevels

A native macOS floating panel that finds chart levels, draws them on the selected
TradingView pane, and explains where each level came from.

TVLevels runs locally through [TradingView MCP](https://github.com/madiver/TradingView-MCP).
You do not need an AI assistant, an MCP client, or a second source checkout.

## Platform support

**TVLevels currently supports macOS only.** Its native panel uses Apple's AppKit,
and its installer requires macOS and Apple's command-line tools. There is no
Windows version of the TVLevels panel or installer at present.

The separate **TradingView MCP** project supports Windows. Windows users can
follow its [setup guide](https://github.com/madiver/TradingView-MCP/blob/main/SETUP_GUIDE.md)
and [Windows launcher instructions](https://github.com/madiver/TradingView-MCP/blob/main/launcher/windows/README.txt)
to use that bridge with TradingView Desktop. Installing the bridge does not
install the TVLevels panel. Supporting TVLevels on Windows would require a
Windows-compatible UI and installer.

## What it does

- Daily support, resistance, gaps, candle windows, and prior support/resistance.
- Previous-session and premarket references, current-session highs and lows,
  historical high-volume levels, failed-rally zones, and support holds.
- Five-minute ascending-support and descending-resistance trendlines.
- A level inspector with source dates, prices, and explanations.
- Saved category selections, light/dark themes, and panel position.

Draw and Clear affect the captured chart pane and TVLevels-owned drawings. Manual
drawings and other panes are preserved. The app restores the original timeframe
and session after a drawing operation. TVLevels does not place or cancel orders.

## Requirements

- **macOS**, with [TradingView Desktop](https://www.tradingview.com/desktop/)
  installed in Applications and an account with the required chart/data access.
- **Python 3.9+**, including IANA time-zone data.
- **Node.js 22, 24, or 26**, including npm ([download](https://nodejs.org/)).
- **Apple Command Line Tools**, which supply Git and Swift:

  ```sh
  xcode-select --install
  ```

This is a source installation. There is currently no self-contained, notarized
app download. The first setup needs access to GitHub and the npm registry.

Local unit tests, source builds, and the offline MCP handshake have been checked
on **macOS 26.4 / Apple Silicon**, **Python 3.14.7**, and **Node 22.22.0**.
CI uses Python 3.14 and Node 24 on a hosted Mac. The broader Python/Node ranges
above describe code requirements; this publication checkout has not been
qualified on Intel Macs or older macOS versions. CI does not exercise a live chart.

## Install

Clone or download the repository into a folder you intend to keep, then run:

```sh
git clone https://github.com/madiver/TVLevels.git
cd TVLevels
python3 install.py
```

If you downloaded a ZIP, open Terminal in the extracted folder and run
`python3 install.py`, or double-click **Install TVLevels.command**.

The installer:

1. Checks the required tools.
2. Downloads the exact TradingView MCP commit in
   [dependencies.lock.json](dependencies.lock.json) and installs its locked Node
   dependencies with `npm ci --ignore-scripts`.
3. Builds Daily Levels, installs its Applications link, and adds its Dock shortcut.
4. Installs the TradingView Debug launcher. An existing TradingView Dock shortcut
   may be retargeted to this launcher.

Installation does not start or restart TradingView or draw on a chart. Repeating
it reuses the prepared dependency and maintains existing app links. Unrelated
applications are not replaced.

Keep the source folder in place: the installed Daily Levels app links to it.
If you move the entire folder, including its hidden `.local` directory, rerun
the installer from the new location. Its local installation receipt lets it
repair the old shortcut safely. For older installations without a receipt, see
[Troubleshooting](#troubleshooting).

## Use

1. Open **TradingView Debug** from Applications or the Dock. It starts TradingView
   with its local connection enabled. If TradingView is already running normally,
   the launcher requests a graceful restart and respects save prompts.
2. Sign in, open your chart, and select the intended pane.
3. Open **Daily Levels** from Applications or the Dock.
4. Choose categories and click **Draw levels**. Select a level to read its
   explanation. **Clear levels** removes owned drawings from that pane.

Keep the selected chart stable while an operation runs. Ambiguous chart selection,
unavailable history, and unsupported chart styles can prevent a draw. The app uses
TradingView's available chart history and internal APIs, so Desktop updates can
affect compatibility. Detected levels are observational chart references; no
profitability claim is made.

Detailed detection rules and limitations are in [python/README.md](python/README.md).

## Updates and configuration

Pull a TVLevels update and rerun `python3 install.py`. Saved categories, theme,
panel geometry, ownership, and archived snapshots are retained. This command does
not follow a moving MCP branch: each TVLevels revision selects a full commit SHA.
Old managed dependency directories are retained when the pin changes.

For an older local installation with a dependency override, run:

```sh
python3 install.py --use-pinned
```

Unset `TVLEVELS_MCP_ROOT` first if it is set. The installer backs up local
`tvlevels.json` under `.local/settings-backups/`, removes only `mcp_root`, and
preserves other settings. It restores that setting on failure unless the file was
edited concurrently.

For a developer checkout, set `TVLEVELS_MCP_ROOT`, or copy
`tvlevels.example.json` to the ignored `tvlevels.json` and edit `mcp_root`.
Relative paths resolve from the TVLevels source folder. Prepare that checkout's
Node dependencies separately; the installer does not reset or install into it.
Rerun installation after changing the selection so Finder and Dock launches use
the same resolved dependency.

```sh
python3 install.py --dependency-only
python3 install.py --skip-tradingview-launcher
```

The first command prepares MCP without installing apps. The second keeps your
existing TradingView launch setup. Terminal commands accept `TV_CDP_HOST` and
`TV_CDP_PORT`; the supplied Debug launcher uses `127.0.0.1:9222`. Custom ports
require a matching launcher. Finder apps do not inherit terminal-only environment
settings. Keep the debugging endpoint local.

## Local data and privacy

The following files stay on your computer and are excluded from Git:

- `tvlevels.json`: optional machine-specific configuration.
- `python/.daily-levels-owned.json`: drawing ownership for selective Clear.
- `.local/panel/level-details.json`: current chart explanations.
- `.local/panel/level-snapshots/`: immutable records of completed Draw/Clear actions.
- `.local/panel/theme.json`: drawing appearance preferences.
- `.local/dependencies/`: downloaded MCP source and Node dependencies.
- Generated apps, Dock backups, settings backups, logs, and screenshots.

Saved panel preferences also use macOS UserDefaults. Chart records can contain
symbols, prices, source times, chart identifiers, and layout URLs. Review any
diagnostics before sharing them. TVLevels has no bundled analytics or telemetry;
setup downloads dependencies, and the bridge communicates with your local
TradingView Desktop. See [SECURITY.md](SECURITY.md) for the connection boundary.

Do not delete `.local` wholesale when troubleshooting; it contains saved themes
and archived evidence. If an install reports a modified or incomplete managed
dependency, move only the named dependency directory aside and rerun setup.

## Troubleshooting

- **A required tool is missing:** install the requirements above, reopen Terminal,
  and check `python3 --version`, `node --version`, and `xcrun --find swiftc`.
  If Python reports missing time-zone data, install it for that interpreter with
  `python3 -m pip install tzdata`.
- **The panel cannot connect:** open TradingView Debug, finish any save/restart
  prompt, sign in, and make the intended chart visible. With multiple chart
  windows open, select the intended window before drawing.
- **An MCP request times out:** startup responses have a 15-second deadline and
  later requests a 30-second deadline. Timed-out actions are not retried automatically.
  The client requests cancellation and attempts restoration through the existing
  pane binding; cancellation is best effort. Recovery can require additional
  bounded requests. If restoration cannot be verified, check the original pane's
  timeframe/session and drawings before retrying. An unresponsive bridge or a
  late operation means automatic restoration cannot be guaranteed. Close and
  reopen Daily Levels once the chart is stable.
- **Reinstalling after a folder move refuses an old broken shortcut:** a missing
  receipt cannot establish who created that link. In Finder, inspect
  `~/Applications/Daily Levels.app`; if it is the broken link to your old TVLevels
  folder, move only that link to Trash, then rerun `python3 install.py` from the
  new source folder. Keep the moved `.local` data intact. Unrelated app entries
  are deliberately left untouched.
- **macOS blocks opening a downloaded command file:** use Terminal to run
  `python3 install.py` from the source folder. This project does not require
  disabling Gatekeeper or other macOS security protections.

## Uninstall

Close Daily Levels. Remove its Dock shortcut and the **Daily Levels** link from
`~/Applications`. If you also want to stop using the supplied Debug launcher,
remove **TradingView Debug** from that folder and the Dock, then open and pin the
original TradingView Desktop app normally.

These steps retain saved panel preferences and the source folder's local
ownership, theme, and archived snapshots. Back up records you want to keep before
removing the source folder. Never remove TradingView Desktop as part of removing
TVLevels. No background login item or service is installed by this project.

## Development and support

```sh
python3 -m unittest discover -s python -p 'test_*.py' -q
python3 panel/build.py
```

Tests use synthetic fixtures and do not require a running chart. Building does
not verify the installed launcher or UI. See [CONTRIBUTING.md](CONTRIBUTING.md)
for development and chart-verification requirements, and
[CHANGELOG.md](CHANGELOG.md) for changes. After setup, **Daily Levels.command**
rebuilds and opens the panel.

Use a repository issue for reproducible bugs or feature requests. Include macOS,
TradingView Desktop, Python, and Node versions; remove account details and private
chart data. Report vulnerabilities through the process in [SECURITY.md](SECURITY.md).

## License and attribution

TVLevels is distributed under the [MIT License](LICENSE). Original copyright
and additional notices are retained; see [PROVENANCE.md](PROVENANCE.md) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

This is an unofficial project, not affiliated with or endorsed by TradingView.
Its license does not grant rights to TradingView software, trademarks, or market
data. TradingView account, subscription, and exchange-data permissions still apply.
