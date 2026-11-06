# Security policy

## Reporting a vulnerability

Use this repository's **Security → Report a vulnerability** option when private
reporting is enabled. If that option is unavailable, open an issue requesting a
private reporting channel without including exploit details, account information,
or private chart data. Do not post credentials or a working exploit in a public
issue. Reports about the separate bridge should go to its own maintainer.

There is no guaranteed response time or formal support service. Include the
affected revision, prerequisites, impact, and a minimal reproduction through a
private channel. Retest against current source when practical.

## Connection and data boundaries

TVLevels starts a pinned local TradingView MCP process and uses it to inspect and
modify chart drawings. The bridge connects to TradingView Desktop's debugging
endpoint, normally `127.0.0.1:9222`. Treat access to this endpoint as access to
your signed-in Desktop session: keep it on the local machine and do not expose
it through network listeners, tunnels, or public proxies.

Setup downloads source from GitHub and locked dependencies from npm. The bridge
contains additional tools that may use TradingView endpoints; see its own
[security policy](https://github.com/madiver/TradingView-MCP/blob/main/SECURITY.md).
TradingView Desktop continues its normal account and market-data connections.

Local chart records can contain symbols, prices, timestamps, chart/layout URLs,
and drawing identifiers. Configuration and generated app files may contain local
paths. Review diagnostics and screenshots before sharing them. The standard
runtime paths are ignored by Git, but a forced add or a custom export location
can bypass those exclusions.

## Scope and maintenance

Relevant reports include unintended chart access, unowned drawing changes, code
execution through inputs, credential exposure, and installer/dependency integrity
issues. Do not place or cancel orders when investigating this project.

Only the current default-branch source is considered for fixes. There are no
separately maintained release branches or packaged binary releases at present.
TradingView, Python, Node, and third-party libraries have their own maintainers
and security policies; this project does not replace them.
