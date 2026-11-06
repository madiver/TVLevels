# Daily chart levels

First run `python3 install.py` from the TVLevels root to prepare the pinned
TradingView MCP dependency and install the macOS apps. Then run from TVLevels
(Python 3.9+ with IANA timezone data):

```sh
python3 python/daily_levels.py --dry-run
python3 python/daily_levels.py
python3 -m unittest discover -s python -p 'test_*.py' -v
```

TradingView must already expose CDP; this tool never launches or restarts it.
`TV_CDP_HOST` and `TV_CDP_PORT` configure the MCP endpoint.
The MCP checkout defaults to the revision in `dependencies.lock.json`, installed
under `.local/dependencies/`. For development, set `mcp_root` in TVLevels' ignored
`tvlevels.json`, or override it with `TVLEVELS_MCP_ROOT`. Use
`python3 install.py --use-pinned` to back up and remove an old local override.
All relative dependency paths resolve from TVLevels. The panel, drawing ownership,
details and snapshots live in TVLevels, independently of the MCP checkout.

The tool captures the selected chart widget and its stable pane ID, remembers
its symbol/timeframe/session, reads enabled intraday session ranges on five-minute
bars and failed-rally zones on one-minute bars, switches only that pane to regular daily data when needed, and reads up to
300 loaded daily bars (500 maximum), draws levels, and restores the timeframe
and session in a finally block. It rejects synthetic chart styles. Do not interact with the
chart or run another drawing task during execution. If selection changes,
it stops new work, rolls back new drawings, and restores the captured pane
without changing the newly selected pane. If the original pane is removed or
its symbol changes, it stops with an error. The pane-local timeframe setter
bypasses interval synchronization; new drawings bypass drawing synchronization
and remain local. Other panes, including panes with the same symbol, are preserved.

Detection uses completed daily candles, excluding today's bar before 16:00 New
York time. Early-close sessions are conservatively omitted until 16:00. It does
not fetch unloaded daily history. Results are bounded by the available lookback.
Today's daily wick can update gap/window status before the close, but cannot
confirm a support/resistance role change or replace an established gap edge.

## Daily reaction areas and role changes

Support and resistance share a detector over all loaded completed daily bars.
A source is an actual daily high or low with a move away in the source/next three
closes. The minimum move is the greater of two instrument ticks, 0.5% of price,
and half the local typical move. The typical move uses the median close change
and half the median candle range over up to 20 candles. This is a scale filter,
not ATR. Nearby source edges form a zone anchored at a fixed actual boundary;
chains of neighboring prices cannot widen it indefinitely.

Two tests qualify an area only when a whole intervening daily candle moved away
from the boundary by at least two ticks or 0.5%. Consecutive wick touches are not
independent tests. Quiet repeated areas do not need 10% reactions. An individual
source can also qualify through a prominent local reversal (impulse and reaction
at least twice the typical move) or a large-range candle with a strong closing
reaction. The latter retains the earlier 20% range/10% closing-reaction rule as
one sufficient pattern, rather than the requirement for every area; a resistance
source must also reach the preceding high. The first loaded bar cannot qualify
as a standalone large-candle source without prior context.

A later wick through an area does not erase its significant reaction history.
Completed closes above the upper zone establish support; closes below the lower
zone establish resistance. Closes within the zone preserve its last role.
Original support with a confirmed closing break below becomes **Prior S**;
original resistance with a confirmed closing break above becomes **Prior R**.
A live quote crossing the original role before a completed closing break retains
**Retest S** or **Retest R**, with `state: crossed`; it does not claim a confirmed
role change. A live return across a confirmed Prior area retains **Prior S retest**
or **Prior R retest**. A completed reclaim restores the original category and
retains the break/reclaim history. A subsequent daily test and close away records
`retested`. States are reconstructed from loaded history each time Draw runs.

The existing Support/Resistance checkboxes own original and provisional retest
references; the independent Prior checkboxes own confirmed flipped sources.
Unbroken daily edges remain fallback candidates. There is no two-candles-on-each-side
rule. Minor superseded highs without significant reaction evidence stay excluded.
For example, VEEA's $7.49 daily peak can remain a provisional retest reference
after the live quote crosses it, and JAGX's $6.80 large-candle low remains eligible
for Prior support without being a neighboring-candle swing low.

Significance combines independent tests, relative reaction size, source volume
relative to the previous 20 available positive-volume candles, and recency.
Missing/invalid volume is neutral. Proximity ranks candidates with a bounded
preference for stronger evidence. There is no 60-day source cutoff. Selection
reserves the two nearest distinct eligible daily prices above the live quote and
two nearby references below, then fills the default five-line daily budget.
Each Prior family is capped at two candidates. Fewer genuine overhead references
are returned when history does not contain two; prices are never invented.

## Gaps, windows, and context

True gaps use non-overlapping adjacent daily wick ranges. Both upside and downside
fill references are supported. Later completed highs/lows move the remaining
entry to an actual candle edge. Metadata preserves the original gap boundaries,
remaining boundaries, direction, source date and lifecycle:

- `unfilled` / `partial`: completed candles leave all/some gap space.
- `partial_today`: today's daily wick entered the remaining corridor, with
  proven completed boundaries retained.
- `traversed_today`: today's wick reached the far boundary. Both original edges
  become historical **Filled gap low/high** references.
- `crossed_quote`: the quote is past the fill boundary without a confirming daily
  wick observation. Labels add **ref**; this is distinct from a measured daily fill.
- `filled_recent`: a completed candle filled the gap; original edges are historical
  references for up to 20 completed sessions, still subject to quote relevance.

An active far boundary is labeled **Gap fill target** (or **Gap fill target down**).
Measured fills use **Filled gap low** and **Filled gap high**, restoring the two
original boundaries and dates even if a narrow remnant existed before the fill.
A quote crossing without a measured daily fill uses **Gap fill ref** instead.
These labels do not claim that a filled gap is still open. The inspector lists both original wick
prices and dates, even when later candles have changed the remaining entry. If
the Draw quote is inside the corridor, it explains that entry has already been
crossed; it does not move the established daily edge to the live quote.

Ross's [wick-gap example at 4:47](https://www.youtube.com/watch?v=HpA3dWHPnkI&t=287s)
uses the actual empty space between candle ranges, rather than a previous-close
to next-open interval. Overlapping daily wicks do not qualify as this type of gap.

Original gap width must be at least the greater of **5% of its original upper
boundary price** and **two instrument ticks**, using the tick ladder at both
original edges. Tiny original gaps are omitted even with only Gaps selected.
There is no minimum percentage of the original gap that must remain. If later
completed candles leave less than the greater of 5% of the remaining upper edge
and two ticks at the remaining endpoints, Draw keeps only the **full-fill target**.
An upward fill keeps the original upper boundary; a downward fill keeps the
original lower boundary. A single target is ranked and checked for proximity
using its own price, even in a Gaps-only selection. Equality at either width
threshold qualifies. These are display rules, not numerical rules attributed to
Ross. Original prices/dates, partial-fill state, and historical **ref** labels
remain in the inspector, including when a target shares another level's line.
The same original-width rule applies whether the gap is open or filled; a fill
alone never disqualifies a significant original gap.

Historical gaps keep the existing 20-completed-session post-fill retention limit.
Within the surrounding/overhead/below selection buckets, proximity is discounted
by bounded bonuses for up to three later independent daily boundary reactions
(10% each) and recency (10% divided by one plus post-fill age divided by five).
A post-fill candle must touch an original boundary within the greater of two
endpoint ticks and 0.5% of the upper boundary; its following completed daily close
must be at least 1% of the touched boundary and two ticks away. An encounter
counts once, even if both boundaries are touched. Another completed candle must
leave the whole interval before a later encounter can count. Details retains the
reaction prices, source dates, confirmation dates and closes. Neither today's
forming candle nor the live quote can confirm a historical reaction. These
ranking choices are engineering heuristics, not John or Ross rules or evidence
that a future reaction is assured.

Selection keeps one gap pair (or one narrow-remnant fill target) and one independent window pair: surrounding the
quote first, otherwise nearest overhead, otherwise nearest below. Ordinary Draw
suppresses corridors farther from price than the larger of 25%, twice the median
relative daily range over 20 bars, and the latest daily relative range. This is
an operational relevance heuristic. A corridor-only checkbox selection can inspect
the nearest historical pair beyond that range. Displayed corridor boundaries and the premarket
range are additional to the soft daily budget. Minimum spacing can merge a nearby
corridor boundary with another reference while preserving both meanings.

Windows cover an exposed portion of a long red daily candle. Open/close recognizes
a large body, at least --body-multiple (default 2) times the median of up to 20 prior
nonzero bodies, with at least three samples. Lines use wick prices. The top is the
source high; entry is the greater of the source low and the highest later completed
daily high, with that newer candle's date when it sets entry. A partial revisit
therefore narrows the window to a real daily boundary. A revisit reaching the source
open leaves only an upper-wick interval and omits the window. A later high or live
quote reaching the top also omits it. Broken pivots preceding the source candle
cannot be resurrected inside the window. Only red-candle upside windows are implemented.

Draw also omits small window remnants. The completed-candle remaining width must
be at least **25% of the original source high-to-low range** and at least the
greater of **5% of the source high** and **two instrument ticks**, using the tick
ladder at both endpoints. Exact threshold equality qualifies. These display
filters apply even with only Windows selected, before ranking, so another eligible
window can take precedence. They do not move or average the actual daily edges,
and do not apply to true gaps. An omitted window's high remains independently
eligible under the existing Resistance rules when that category is enabled.
For example, NXTS's $1.79–$2.11 source narrowed to $2.0499–$2.11; only 19% of its
original range remained, so that pair is omitted. Width thresholds are our initial
automation choices, not numerical rules attributed to Ross. There is no ATR filter.
For a window topping at $2.00, at least $0.10 must remain, and the original-range
and two-tick minimums can raise that requirement further.

Ross's [GLBS daily example at 7:11](https://www.youtube.com/watch?v=HpA3dWHPnkI&t=431s)
shows an $8.77 later-high entry below a $19.50 source top. This visual example
supports retaining partially revisited windows; the size and relevance thresholds
remain our operational approximation, not a verified universal Ross algorithm.
The inspector explicitly identifies the body-size multiplier as our automation
filter. Metadata records the method, original source dates and size-filter inputs.

The JSON result includes reaction strength, contributing actual source prices,
zone bounds and closing-role history. `context.obstructions` reports significant
enabled reaction references inside selected corridors, including references outside
the line budget. With 200 completed daily bars it also checks a **computed daily
SMA200**. This is not a readback of a configured TradingView moving average, and
no SMA drawing or moving-average indicator is added. Insufficient history yields
null. Context and strength appear in the level inspector.

Selection uses the newest timestamped trade from the selected chart's quote
provider: regular, pre/postmarket, or overnight. Numeric strings are normalized.
It captures a quote before changing timeframe, retries transient loading, and
retains that snapshot if the daily switch resets quotes. It never substitutes the
prior daily close for a missing live quote. In an explicitly active pre/postmarket
session, a timestamped extended-session trade takes precedence over a regular
closing price whose quote timestamps were refreshed by the provider.

Nearby levels merge below the greater of two instrument ticks and 0.5% of the
higher price, honoring TradingView's variable tick-size ladder. Daily groups retain
the highest actual boundary; premarket boundaries take precedence. Prices are never
averaged. Merges preserve source prices, dates, zones, corridor identities and
reaction history. Overhead selection backfills the next distinct daily candidate
when a premarket merge moves a line below the quote. The default limit is soft:
five daily references plus complete corridor pairs and explicit session
references can produce more than five lines. Draw refreshes all classifications; there is no
background updater.

## Selected chart and tab

The panel's header and level list follow the selected pane in the visible
TradingView tab. The background inspector rechecks tab visibility each poll;
Draw/Clear capture that same visible tab before starting. Hidden tabs with the
same layout URL cannot supply an old symbol or level list. A captured drawing
operation stays on its original tab; switching tabs stops new writes and allows
cleanup/restoration on the original pane. The footer identifies the last Draw
or Clear action, which can differ from the currently selected chart. With
multiple visible TradingView windows, select the intended window to resolve
ambiguity. No chart tab is activated automatically.

## Historical event references and Previous open

**Historical events** has three independently selectable controls, on by default:
**Historical high-volume highs**, **High-volume closes** and **Prior PM highs**.
High-volume highs retain the actual regular-session high of the same qualifying
sessions as High-volume closes, even after later price crossings. They work
without enabling ordinary Resistance or High-volume closes. The chart label is
**High-volume high MM/DD**; Details includes the exact high, low, close and volume.
**Previous open** is also on by default
under Session references. It uses the most recent completed regular session's
actual opening price, with the same proximity, MM/DD dates, merging and Clear
ownership as the other previous-session references. Gray dashed identifies the
open; gray dotted continues to identify the close.

Historical events scan the last 120 completed provider daily sessions. High-volume
highs and closes require at least five earlier baseline sessions, volume at least twice
the preceding 20-session nonzero-volume median, relative range at least 1.5
times its typical range, and volume at least as high as that preceding baseline's
maximum. This isolates independent volume events rather than labeling all the
follow-through closes from one spike. The label date identifies the source
trading session; the detector does not identify a news or corporate catalyst. Historical premarket highs require a rise
above the prior regular close at least as large as the preceding typical daily
range and two ticks. Thirty-minute extended-hours data includes exactly
04:00–09:29 New York time, excluding overnight and the regular open.

Ranking combines capped logarithmic volume/range ratios, rejection, independent
later daily reactions separated by at least three sessions, and recency. Each
reaction must touch the source within the greater of two ticks and 0.5% and move
away on the following completed daily close by half the typical daily range or
two ticks. These are our initial display settings, not John or Ross rules.

Selection uses the Draw quote and today's entire traded range, including
premarket and a developing candle for range only. Sources must be within 25%
below/above that range. The three categories share a four-line cap: up to two
significant references in today's range (or nearby below), plus up to two nearest
qualifying references beyond its high. Existing minimum spacing merges nearby
references without averaging prices; Details preserves every event's source,
date, exact price, volume and context when merged with another family.

Completed one-minute extended-hours candles supply intraday context. Two
consecutive closes above the source plus one tick confirm an intraday reclaim;
a later separate candle touching within one tick and closing above the buffer
describes a potential support retest. A later close below the source minus one
tick marks it lost. Wicks/isolated crossings remain tests, not confirmed reclaims.
Missing minutes interrupt the two-close count; forming/future/prior-day candles
cannot confirm these states. Quote position is reported separately and never
changes the historical source or confirms a daily role reversal. State refreshes
on Draw. New historical lines use the existing thin green/orange dashed family.

Daily history includes the ranking warmup. Historical session reads request
complete coverage back to the earliest selected source day (up to ten 500-bar
requests, at most 5,000 returned bars). Unavailable full history aborts replacement
and preserves prior drawings. All reads and restoration stay pinned to the
captured pane/tab. Historical event controls use full-width rows in the scrolling
Categories area so the longer high-volume-high option remains readable.

## Support holds

The independently selectable **Support holds** category identifies where a
meaningful intraday drop stopped and rebounded. A falling completed one-minute
close must decline at least 1% and two instrument ticks from an observed high.
The actual candle low is the hold source. A later completed close must recover
at least 60% of that decline and two ticks to confirm the hold. At least two independent
drops with confirmed rebounds near the same price are required. Adjacent touches
during one drop count as one test. The group qualifies at the second rebound
confirmation; additional independent holds strengthen the evidence. A confirming candle cannot start the next test.

After two full selloff/rebound holds establish a floor, later local retests can
strengthen it without another 60% recovery of the entire selloff. Before each
approach from above, a separate completed candle must stay above the touch area
and close at least the greater of 1% and two ticks above the then-known floor.
The touch must reach within the greater of 0.1% and one tick of that floor; a
later completed close must rebound at least 1% and two ticks from the actual
retest low. Consecutive touches count once. A lower wick outside that tolerance
cancels the candidate, and missing minutes separate groups. Retests use the
same activity/volume policy as full holds. An overlapping full hold and local
retest count once, retaining the earliest confirmation. Original qualification
at the second full rebound is unchanged. A later breakdown never renames or
recolors these historical observations.

Ten minutes without a new low expires the candidate and restarts from recent
consolidation highs. Missing minutes interrupt candidates and separate groups.
The session fallback and complete-history guarantees match failed-rally zones;
both detectors share a single intraday history read when enabled together.

Clustering uses a fixed first-low anchor: the total span must fit within the
greater of 0.5% of that anchor and two ticks. Padding is the greater of 0.1%
of the first low and one tick. Source lows and rebound confirmation times remain
in Details. Draw retains three nearby groups, prioritizing containing/below-price
areas, plus up to two additional floors below the quote with at least three
holds, ranked by hold count, latest rebound, then proximity. All must be within
25% of the Draw quote. Intraday hold groups stay separate from daily lines.

Green ovals with two-pixel outlines mark the actual hold lows. One green label
below the latest source low gives the number of tests and approximate actual
floor, for example **Support holds · 4 tests · ~$2.00**. Labels use cents at $1
or above and at least three decimals below $1, with more precision as needed.
Artificial padding is excluded from the label; exact source lows, padded bounds,
full-hold/retest evidence and original qualification remain in Details;
older sessions include MM/DD. A mark is historical annotation made only after
its later rebound confirmation. It records where support held at that time,
not whether the level remains defended now. Later breakdowns do not rename or
recolor these successful holds. No failed-support, retest or reclaim markers
are drawn by this category. Clicking any oval or label shows the same group’s
source lows and rebound evidence. Draw refreshes the snapshot; Clear removes
every managed oval and label, including drawings from the previous failed-support
implementation. The internal `support_zone` category key stays unchanged to
preserve saved checkbox choices. These are our engineering choices, not rules
attributed to Ross or John, and remain separate from daily Prior support.

## Failed-rally detector

The independently selectable **Failed-rally zones** category uses the latest
available TradingView one-minute US-equity extended-hours session, from 04:00
to 20:00 Eastern. If no candles exist for today, Draw uses the most recent
provider session, including on weekends and holidays. Older labels include
MM/DD and Details identifies the actual source session. This is based on
available candles, not a guessed holiday calendar: an inactive symbol may also
show a dated prior session. Before 04:00 Draw still reports that today's session
has not started. A forming candle selects today's session without qualifying
any evidence; a quiet current session never combines tests with the prior day.
No completed candles and no qualifying pattern have separate status messages.
Only completed candles supply evidence. Draw requests loaded history
back to the selected session's 04:00 and reads up to 1,000 bars; incomplete history stops replacement
of the old drawings. The current developing candle cannot qualify a failure or
reclaim. Nothing is reconstructed from DAS or Time & Sales.

A rising close starts a rally after gaining at least the greater of **1%** and
**two instrument ticks** from its observed base low. The actual wick high is the
peak. A later completed close must give back at least **60%** of that impulse
and **two ticks** to confirm a failure. The failure candle cannot also start the
next test. Ten minutes without a new peak expires the impulse; a subsequent
rally uses the recent consolidation lows after that peak. Missing minutes reset
the active impulse, and tests on opposite sides of a gap cannot combine.

At least **two independent failures** near the same ceiling qualify a band.
Their total peak span cannot exceed the greater of **0.5%** of the first peak
and two ticks; a fixed anchor prevents chain merging. Bounds retain the actual
lowest/highest peaks, padded by the greater of **0.1%** and one tick. Different
ceilings remain separate from each other and from existing daily/session lines.
After two full failures establish a ceiling, later independent local retests can
strengthen it without requiring another full-impulse 60% retracement. A separate
completed candle must stay below the touch area and close at least the greater
of 1% and two ticks below the then-known ceiling. The next approach from below
must reach within the greater of 0.1% and one tick of that ceiling; a later
completed close must reject the actual retest peak by at least 1% and two ticks.
Adjacent touch candles count once. A higher wick outside the touch tolerance
cancels the local candidate, retaining higher wick clusters separately. Missing
minutes separate groups, and the same reaction/reversal volume policy applies.
Overlapping full failures and retests count once. Only later tests are added;
the original second full-failure qualification time is retained. These are
explicit automation choices, not verified Ross or John rules.

Draw keeps the three nearby zones, prioritizing unreclaimed, containing/overhead,
and nearer zones. It also retains up to two additional unreclaimed overhead
ceilings with at least three separate failures, ranked by test count, then latest
failure, then proximity. All must remain within 25% of the quote. This independent
five-ceiling maximum keeps stronger ceilings visible as newer, nearer zones form;
it does not add single-test areas or merge distinct ceilings.

Each selected ceiling draws a lightly shaded oval around each confirmed rally peak.
Ovals span two minutes either side of the peak (five candle timestamps) with a
price radius of the greater of 0.25% of that peak and the existing zone padding.
Each ceiling uses a different high-contrast color (coral, blue, violet, teal, or gold),
shared by its light fill, two-pixel outlines, bold 13-point label and Details color sample.
The fill is 84% transparent (16% opacity), so candle bodies remain visible.
Colors are assigned in first-peak time order, independently of the moving quote.
There is no horizontal
band or line. One label beside the latest peak identifies the whole ceiling:
**Failed rallies · N tests · ~$ceiling**.
Labels show the highest actual rejection peak, rounded to cents at $1 or above.
Below $1, at least three decimals are used with extra precision for small prices.
The approximate ceiling label excludes artificial padding. Exact bounds,
peak prices, peak times, evidence type (full failure or later retest), and qualification
time remain in Details. A peak's oval is historical annotation drawn only after
its failure is confirmed; it does not claim the failure was known at the peak.
Click any oval or its label to inspect the same ceiling. Draw/Clear own every
oval and label, including cleanup of older rectangular bands. Moving or deleting
a member shows an edit notice in Details without changing the recorded evidence.
Two consecutive
completed-minute closes above the then-known upper band plus one tick mark it
**Reclaimed rally zone · N tests · ~$ceiling**, in a softer, less saturated shade of its group color.
A completed close back below the lower band restores that group's original shade
without inventing another test. The inspector records
peak/failure times, actual prices, base lows, retracement, bounds and reclaim
history. These numeric thresholds are initial implementation choices, not rules
attributed to Ross. There are no Level 2, tape, MACD, VWAP or execution gates.

Click **Draw levels** to refresh; the category does not update drawings in the
background. Checking a box alone changes neither the chart nor trading behavior.

## Premarket levels

For US equities with extended-hours data in New York time, Draw also adds the
current calendar day's high and low from 04:00 inclusive to 09:30 exclusive.
Five-minute bars align with those boundaries; regular-session and overnight
trades are excluded. The forming premarket candle is included during premarket.
After 09:30 the range remains fixed. Clicking Draw refreshes the snapshot; there
is no background updating. Before 04:00 or on a day without premarket trades,
no previous day's range is substituted. Other instruments keep daily levels only.

Only the captured pane is temporarily switched to five minutes and, if needed,
extended hours. Its original session and timeframe are restored. Older intraday
history is requested until coverage reaches 04:00 or the provider confirms no
earlier history (for example a new listing). Incomplete coverage stops the run
before replacing existing drawings. The 500-bar read covers the current session
on five-minute bars even late in the day.

Premarket lines are fuchsia (#ff00ff), solid, one pixel, labeled **PM high** and **PM low**.
The existing minimum spacing also applies to these lines. A nearby daily level
shares a line at the exact premarket price with a combined label, such as
**PM high / Resistance**. A very narrow premarket range can share a single
**PM high / PM low** line at the actual high. Fixed group anchors prevent chain
merging, and overhead daily selection still backfills distinct lines when possible.
Premarket drawings use the same ownership tracking and Clear button as daily levels.

Horizontal lines remain one pixel; rally ovals use two-pixel outlines. Styling uses all source categories retained after
merging, independently of which actual price anchors the line:

| Reference | Color | Line style |
| --- | --- | --- |
| Daily support/resistance | Green #66bb6a below the Draw quote; orange #d18b32 at/above | Dashed |
| Prior support/resistance | Brighter green #00e676 / orange #ffb74d | Dashed |
| Gap/window boundaries | Standard green/orange relative to the Draw quote | Dotted |
| Previous-session high/low | Cyan #26c6da | Dashed |
| Today’s regular-session high/low | Cyan #26c6da | Solid |
| Previous close | Gray #b0bec5 | Dotted |
| Premarket high/low | Fuchsia #ff00ff | Solid |
| Failed-rally zones | Distinct bright color per ceiling; softer when reclaimed | Peak ovals and one matching label, no line |
| Support holds | Green for confirmed historical rebounds | Hold-low ovals and one group label, no line |

Merged-line styling precedence is premarket, Prior daily, daily support/resistance,
gap/window, today's range, previous range, previous close. Thus a gap entry sharing
its price with yesterday's high stays a dotted daily line; a daily resistance
sharing today's high stays dashed green/orange. Every source remains in the combined
label and explanation. Price anchoring, minimum spacing and level eligibility do
not change. Shade identifies a source family rather than strength. Green/orange
uses the captured Draw quote; cyan, gray and fuchsia identify session sources.
Colors and styles refresh on Draw. The panel's Legend, line samples and explanations
use the same shared style definitions as the chart drawings.

Adjacent labels alternate between the left and right edges to avoid overlap
when prices are close together. Labels include Resistance, Support, Retest R, Retest S, Gap entry,
Gap fill target (or Gap fill ref), Filled gap low/high, Window entry, Window top, Prior S and Prior R, with an MM/DD source
date on every reference from a previous day. Today's references, including
PM high/low, remain undated. Dates use New York trading time. A partially
filled gap's entry date belongs to the candle that set the remaining edge.
Merged references retain each source's own label and date, even if a premarket
line supplies the displayed price. Repeated labels from the same source day
are shown once. Drawing IDs are
tracked per chart URL, symbol, and stable pane ID in the ignored python/.daily-levels-owned.json
file. Older [DailyLevels] labels are migrated on the next run. Preserve this file
to keep ownership tracking across runs. Reruns create
the replacement set first, then remove old managed drawings. Manual drawings
remain untouched; existing manually marked examples are not auto-adopted.
A failed drawing creation rolls back new drawings and preserves the previous set.
If old-drawing deletion fails, a rerun reconciles surviving managed labels.
The tool creates chart drawings; it does not submit orders or alter indicators.

## Additional session and price references

Previous high/low/close come from the latest loaded regular daily candle dated
strictly before today, including after today’s close. Friday supplies Monday’s
previous session when it is the latest loaded trading day.
Previous high, low and close draw within the daily proximity range, which has
a minimum reach of 25% of the Draw quote. Missing history or distant prices
receive omission reasons in category help.

Today’s high/low use the provider’s regular-session five-minute bars starting
at 09:30 New York time. When premarket is also enabled, the tool reads extended
and regular sessions separately. The provider’s regular session excludes
postmarket on early-close days. The forming regular candle is included. No trades
today means no previous-session substitute. Explicit session references
require supported US equities and New York session data; existing daily structure
remains available for other instruments.

Session references use the colors and styles in the table above.
Premarket retains solid fuchsia. The panel does not add whole/half-dollar lines
or a Daily 200 SMA drawing; use TradingView’s price axis and existing indicator.

## Floating panel (macOS)

The levels panel is used and validated only on macOS.

Install once using `Install TVLevels.command` or `python3 install.py` at the root.
After setup, double-click `Daily Levels.command` at the repository root, or run it from a
terminal. It builds a small native always-on-top panel in the ignored `.local/`
folder and opens it. Requires Python 3, Node, and Apple's Swift command-line tools.
The generated `.local/Daily Levels.app` can also be opened directly afterward.

The top-level installer runs `panel/install.py` to add **Daily Levels** to `~/Applications` and
pin it beside TradingView in the Dock. It uses a link to the same built app,
so subsequent builds update the Dock launcher too. The installer preserves
other Dock items and does not add duplicate shortcuts on repeated runs.
The app icon source is `panel/assets/DailyLevels.png`; rebuilding packages it
into a macOS icon automatically.

Use the **Light / Dark** button beside **Legend** to switch the panel theme.
Dark remains the default; the selected theme is remembered across launches.
Categories, levels, explanations and popovers use the selected appearance.
Changing theme recolors managed drawings on the selected TradingView chart in
place. Prices, dates, labels, drawing IDs, styles and widths are preserved; levels
are not recalculated. Other charts adopt the saved palette when selected or
redrawn. Light mode uses deeper shades of the same green/orange, fuchsia, cyan
and rally-group hues. The panel’s color samples and legend use that palette too.
CLI Draw defaults to the shared saved theme; `--theme light` or `--theme dark`
provides an explicit override. The preference is stored in ignored
`.local/panel/theme.json`. `python3 python/level_theme.py --theme light` restyles
only existing owned drawings on the selected pane. A failed update restores
previous colors; an unsupported or changed chart reports the error in the panel.

Select a TradingView chart, then click **Draw levels** or **Clear levels**.
The **Categories** tab groups 18 independently selectable categories:

- **Price structure:** Resistance, Support, Gaps, Windows, Prior support,
  Prior resistance, Failed-rally zones, Support holds.
- **Session references:** Previous open, Previous high, Previous low, Previous close,
  Premarket high/low, Today’s high/low.
- **Historical events:** Historical high-volume highs, High-volume closes, Prior PM highs.

All categories are enabled on first launch; subsequent launches remember your
checkbox choices. Click **Legend** for colored line samples and the merge priority.
Click an information icon for a plain-English category definition, its appearance and, when applicable, the last Draw’s omission reason.
Click **Draw levels** to replace managed drawings with the selected types.
Changing a checkbox alone does not change the chart. Filtering happens before
nearby prices combine, so labels contain only enabled types. With everything
unchecked, Draw is disabled and Clear remains available. Clear removes all
managed types regardless of the checkboxes.

The **Levels** tab lists this tool’s drawings on the currently selected chart,
ordered by price. Click a row, or select its drawing directly in TradingView,
to see its explanation. Each explanation includes actual source prices and dates,
session definitions, gap/window state, daily role changes, available reaction
history, and why nearby references share one line. Merged references retain all
individual source prices. The observer reads chart selection; selecting a chart can apply the saved
palette to its existing owned drawings. It does not recalculate level prices or
create new drawings in the background. Manual drawings are excluded. Manually
moving or renaming an owned line shows an edit notice and preserves the original
source explanation until Draw recalculates. Older lines offer category help and
ask you to Draw once to obtain detailed provenance. Explanations are stored by
chart URL, symbol and pane ID in ignored `.local/panel/level-details.json`.

CLI example: `python3 python/daily_levels.py --level-types gap window previous_high`.
When all intraday types are off, intraday data is not requested. `--catalog` prints the help catalog without connecting.

The nonactivating panel preserves chart selection. Both buttons are disabled
while working; a short status reports success or an error. Clear removes only
managed levels on the selected pane, preserves manual drawings and other panes,
and does not change timeframe. CLI equivalent: `python3 python/daily_levels.py --clear`.
The panel uses the same CDP endpoint configuration as the existing tool.


### Intraday reaction volume

Failed-rally zones and Support holds still require two independent, price-confirmed
reactions. Each counted test now needs at least 100 shares and $500 estimated
traded value per minute, averaged separately over the short reaction and its
reversal candles. The window is the actual peak/trough plus up to three later
completed minutes, never later than confirmation. Missing volume excludes a test;
invalid negative or nonfinite volume stops the operation before drawing replacement.

Local relative volume compares this reaction with the median of up to 20 preceding
consecutive completed minutes in the same premarket/regular/after-hours phase.
At least five baseline candles and a positive median are required; a phase crossing
or unavailable baseline gives no bonus, but activity-qualified tests remain valid.
This is not historical same-clock-time RVOL. No additional chart history is fetched.
At least 1.5× local volume marks elevated participation. Within the same side and
1%-of-quote proximity band, volume-backed areas rank ahead of ordinary ones;
existing state, proximity, repeated-test and display caps remain bounded. Additional
strong areas prioritize test count, then volume evidence. Quiet retests can qualify
without elevated volume. Details shows per-test reaction/reversal activity, ratios,
and the baseline method. No new colors, thicknesses or chart label clutter.

The activity floors and 1.5× threshold are initial calibration choices. Candle dollar
activity uses typical price times shares, not tick-level volume at the exact level;
volume cannot identify traders or prove intent to defend a price. Refresh on Draw.


### Ascending support · 5m

A separate category, on by default for new and existing installations, draws at
most one nearby fixed-anchor rising ray in the selected pane. Other saved checkbox
choices are preserved. This uses native five-minute extended-hours candles from
the latest actual provider session (04:00–20:00 New York), independently of the
viewed interval. Only completed candles qualify; dates are attached to older
session labels. Draw restores the original pane’s interval and session.

A pullback needs a falling close at least 1% and two ticks below its observed
base. A later completed candle must rebound at least 1% and two ticks from the
actual wick low. A candidate with no new low for 30 minutes expires. Successive
independent pullbacks can anchor a ray when they are at least two bars apart and
the second low rises at least 0.5% and two ticks. This avoids nearly horizontal
noise; these thresholds are engineering choices, not John’s verified rules.

Two anchors make a provisional dotted green ray. Another independently confirmed
pullback within max(0.25% of the projected price, two ticks) strengthens it into a
solid green ray without moving the anchors. Candidates are rejected if they cut
through two consecutive closes below that tolerance while forming. After formation,
two consecutive completed five-minute closes below the tolerance mark it Broken:
orange and dashed, with its original points retained. A wick or isolated close
does not confirm a break, and later rallies do not erase a recorded break.

Missing five-minute bars separate anchor sequences and interrupt consecutive-close
counting. The slope and Draw projection use five-minute chart bar spacing. The
visible projection can differ when another interval or price scale is displayed;
anchor prices and times remain exact source points. A projection is a moving
diagonal reference, not a horizontal support level.

Activity and volume use the reaction-volume policy, normalized per minute for
five-minute candles: at least 100 shares and $500 per minute in both the reaction
and rebound, with elevated participation at 1.5× the preceding same-phase median.
No volume spike is mandatory on every touch. Ranking prioritizes reaction count
(capped at five), 1% proximity bands, intact state, elevated volume, proximity and
recency, within 25% of the Draw quote. A stronger broken ray can outrank a weaker
new provisional ray. A subsequent Draw can select a stronger distinct candidate;
it does not refit an existing candidate’s anchors.

The owned native trendline has right extension and one integrated label. Inspector
Details lists anchor and rebound-confirmation times, additional reactions, volume,
break evidence and the current projection. Selecting the line opens those Details;
editing its points produces an anchor-edit notice. Clear and theme changes respect
selected-pane ownership and preserve manual drawings. No background recalculation.


### Descending resistance · 5m

The mirrored category is on by default and shares one native five-minute data
read with Ascending support. Two successive independent rallies with lower actual
wick highs establish a provisional ray. A third confirmed rejection near its
projection strengthens it without moving either anchor. At most one nearby ray
is selected for each direction; no daily/other intraday categories are merged
into these moving diagonal references.

The shared policy uses completed candles, 1%/two-tick rally and rejection moves,
a minimum 0.5%/two-tick fall between anchor highs, separate tests at least two
bars apart, 30-minute candidate expiry, and tolerance max(0.25%, two ticks).
Two consecutive closes above tolerance invalidate a formation or mark an existing
ray Broken. A wick or isolated close cannot confirm a break. A broken resistance
ray stays available as historical context, without asserting a successful support
retest. Later declines do not erase the recorded break.

Intact resistance rays are orange: dotted with two anchors, solid after a third
rejection. Broken rays are green and dashed. All are one pixel wide and use the
existing Light/Dark palettes. The original support-side behavior is unchanged.
The two directions share activity/relative-volume filters and bounded ranking,
with per-minute normalization of five-minute volume. Quiet rejections can qualify.
The source interval, session fallback, source geometry, inspector/edit notices,
Clear ownership, and theme preservation follow the same selected-pane workflow.
The new checkbox preserves all previously saved category choices. These are our
explicit automation rules, not an exact reproduction of John’s discretion.
