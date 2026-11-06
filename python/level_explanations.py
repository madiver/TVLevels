"""Human-readable descriptions of the actual sources in each displayed line."""
from datetime import datetime
from zoneinfo import ZoneInfo
from level_catalog import CATALOG
from level_styles import drawing_style


def money(value):
    integer,fraction=f'{value:,.6f}'.split('.')
    fraction=fraction.rstrip('0')
    return '$'+integer+'.'+fraction.ljust(2,'0')


def source_date(timestamp):
    return datetime.fromtimestamp(timestamp,ZoneInfo('America/New_York')).strftime('%m/%d/%Y')


def explain_level(level,quote,sources,context=None):
    paragraphs=[]
    has_event=bool(level.get('events') or level.get('event'))
    definitions=[]
    for kind in dict.fromkeys(s['kind'] for s in sources):
        definitions.append(CATALOG[kind]['explanation'])
    if not has_event and level['kind'] != 'support_zone':paragraphs.extend(definitions)
    facts=[]
    for source in sources:
        price=source.get('price',level['price'])
        facts.append(f"{source['text']}: {money(price)}, from {source_date(source['time'])}.")
    paragraphs.append('\n'.join(dict.fromkeys(facts)))
    events=level.get('events',[])
    if not events and 'event' in level:
        events=[dict(level['event'],kind=level['kind'],price=level['price'],time=level['time'])]
    for event in events:
        title={'prior_premarket_high':'Historical premarket peak',
               'event_high':'Historical high-volume high',
               'event_close':'Historical high-volume close'}[event['kind']]
        paragraphs.append(f"{title}: {money(event['price'])} on {source_date(event['time'])}.")
        if event['kind']=='prior_premarket_high':
            paragraphs.append('This peak occurred before the regular open. The source is thirty-minute extended-hours candles from 04:00 through 09:29 New York time, so it can be absent from the regular-session daily candle.')
        elif event['kind']=='event_high':
            paragraphs.append(f"That regular session traded between {money(event['source_low'])} and {money(event['source_high'])}, closing at {money(event['source_close'])}, on {event['volume']:,.0f} shares. "
                              'This line retains its actual regular-session high from an unusually high-volume, large-range trading day. '
                              'Premarket and after-hours highs are excluded. Later price crossings do not erase this historical reference, '
                              'and its selection does not require the Resistance or High-volume closes checkboxes. '
                              'The date identifies the source session; we do not identify a news or corporate catalyst.')
        else:
            paragraphs.append(f"That regular session traded between {money(event['source_low'])} and {money(event['source_high'])}. Its closing price is retained as a reference from an unusually high-volume, large-range trading day, even after later price crossings. The date identifies that trading session; we do not identify a news or corporate catalyst.")
        state=event['intraday']['state']
        meanings={'resistance':'Price has not established a completed-minute reclaim today. This is a potential resistance reference when price approaches from below.',
                  'tested':'Today’s completed candles traded above this reference, but did not establish two consecutive closes above the one-tick buffer. It remains a tested reference and potential reclaim checkpoint, not a confirmed reclaim or support flip.',
                  'above_unconfirmed':'The Draw quote is above this reference, but the completed-minute evidence has not confirmed a sustained reclaim.',
                  'reclaimed':'Two consecutive completed one-minute closes established an intraday reclaim above this reference plus one tick.',
                  'retested':'After an intraday reclaim, a separate later completed candle touched the reference within one tick and closed back above the buffer. This is potential support on a retest.',
                  'lost':'Today established an intraday reclaim, then a later completed candle closed below this reference minus one tick. It is a lost level and a reclaim checkpoint on a subsequent bounce.'}
        paragraphs.append('Today’s context: '+meanings[state])
        paragraphs.append(f"Source volume was {event['volume_ratio']:.1f} times its preceding regular-session median; "
                          f"the relative range was {event['range_ratio']:.1f} times typical. "
                          f"{event['additional_tests']} later independent daily reactions contributed to its ranking.")
        intraday=event['intraday']
        last_event=intraday.get('retested_at') if state=='retested' else intraday.get('lost_at') if state=='lost' else intraday.get('qualified_at') if state=='reclaimed' else intraday.get('tested_at') if state=='tested' else None
        if last_event:
            paragraphs.append('Latest confirming candle: '+datetime.fromtimestamp(last_event,ZoneInfo('America/New_York')).strftime('%m/%d %H:%M ET')+'.')
        paragraphs.append(f"The current Draw quote is {intraday['quote_side']} the source price. "
                          'Quotes and single wicks cannot confirm a reclaim. Intraday context does not establish a daily support/resistance role change. '
                          'Selection uses both the Draw quote and today’s traded range, preserving nearby references beyond today’s high after a pullback. '
                          'These initial ranking and confirmation settings are our automation choices, not rules attributed to John or Ross. Refresh on Draw.')
    if has_event:paragraphs.extend(definitions)
    if level['kind'] in ('support_zone','failed_rally') and level.get('volume'):
        paragraphs.append(reaction_volume_explanation(level))
    if level['kind'] in ('ascending_support','descending_resistance'):
        paragraphs.append(ascending_explanation(level))
    if level['kind'] == 'support_zone':
        zone = level['zone']
        clock = lambda t:datetime.fromtimestamp(t,ZoneInfo('America/New_York')).strftime('%H:%M ET')
        session_date = source_date(level['holds'][0]['trough_time'])
        count=level['independent_tests']
        troughs=level.get('trough_bounds',zone)
        paragraphs.append(f"Actual hold lows: {money(troughs['low'])} to {money(troughs['high'])}. "
                          f"Padded drawing range: {money(zone['low'])} to {money(zone['high'])}. "
                          f"Support held on "
                          f"{count} confirmed test{'s' if count!=1 else ''}. "
                          f"These include {level.get('retest_tests',0)} later floor retests. "
                          f"The area qualified after its second confirmed rebound at {clock(level['qualified_at'])}.")
        paragraphs.append('\n'.join(f"{'Floor retest held' if h.get('evidence_type')=='floor_retest' else 'Support held'} "
                          f"at {money(h['trough'])} at {clock(h['trough_time'])}; "
                          f"a later candle confirmed the rebound at {clock(h['confirmed_at'])}, closing at {money(h['confirmation_close'])} "
                          + (f"after rising {money(h['confirmation_close']-h['trough'])} from the retest low."
                             if h.get('evidence_type')=='floor_retest' else
                             f"after recovering {h['recovery']:.0%} of the decline from {money(h['base'])}.")
                          for h in level['holds']))
        paragraphs.append('Each green oval marks the actual low where a meaningful drop stopped and price rebounded. '
                          'It spans two minutes on either side of that low, with one green label for nearby holds. '
                          'The mark becomes known only after the later completed rebound candle. '
                          'At least two independent drops with confirmed rebounds near the same price qualify an area. Adjacent touches during one drop count as one test; additional independent holds strengthen the evidence. '
                          'These are historical observations of where support held at that time. '
                          'A later breakdown does not rename or recolor an earlier successful hold, and this category does not draw failed-support or reclaim markers. '
                          'It does not assert that the area is still holding now. No horizontal line is drawn.')
        paragraphs.append('A selloff needs a falling close at least 1% and two ticks below an earlier observed high. '
                          'A later completed candle must recover at least 60% of that decline and two ticks to confirm the hold. '
                          'A candidate with no new low for ten minutes expires and restarts from recent consolidation highs. '
                          'Nearby lows must fit within the greater of 0.5% of the first low and two ticks, without chaining; '
                          'the area adds the greater of 0.1% of the first low and one tick on each side. '
                          'The chart label shows the lowest actual hold low rounded to cents at $1 or above, '
                          'with more precision below $1. The ~ marks an approximate floor; exact lows, padded bounds and oval positions are retained.')
        paragraphs.append('After two full selloff/rebound holds establish a floor, later independent local retests can add evidence. '
                          'A separate completed candle must stay above the touch area and close at least 1% and two ticks above the then-known floor before each new approach from above. '
                          'A touch is within the greater of one tick and 0.1% of that floor. '
                          'A later completed close must rebound at least 1% and two ticks above the actual retest low. '
                          'Adjacent touches count once, lower wicks outside the tolerance cancel the local candidate, '
                          'and missing minutes separate groups. Retests use the same volume requirements as full holds. '
                          'An overlapping full hold and retest count only once. The original second full-hold qualification time is retained.')
        paragraphs.append(f'Only the {session_date} session’s completed one-minute candles from 04:00 to 20:00 New York time qualify. '
                          'Missing minutes interrupt selloffs and prevent separate segments from counting as repeated tests of one group. '
                          'The three nearby areas plus up to two additional floors below the Draw quote with at least three holds are shown within 25% of that quote. '
                          'Additional repeated areas rank by hold count, elevated participation, latest rebound, then proximity. '
                          'This is intraday context, separate from daily Prior support. These thresholds are our detector choices, not rules attributed to Ross. '
                          'The source is TradingView; DAS candles can differ. Refresh on Draw.')
    if level['kind'] == 'failed_rally':
        zone = level['zone']
        session_date = source_date(level['failures'][0]['peak_time'])
        clock = lambda t:datetime.fromtimestamp(t,ZoneInfo('America/New_York')).strftime('%H:%M ET')
        peaks = level.get('peak_bounds', zone)
        paragraphs.append(f"Actual rejection peaks: {money(peaks['low'])} to {money(peaks['high'])}. "
                          f"Padded drawing range: {money(zone['low'])} to {money(zone['high'])}. "
                          f"{level['independent_tests']} independent rejections contributed, including "
                          f"{level.get('retest_tests',0)} later ceiling retests. "
                          f"The zone first qualified at {clock(level['qualified_at'])}.")
        paragraphs.append('Each lightly shaded oval is centered on an actual confirmed rally peak, spanning two minutes on either side '
                          'and a small price radius around its candle top. One label beside the latest peak identifies this ceiling; '
                          'no horizontal line is drawn. The peaks predate their later failure confirmations, so these are historical '
                          'annotations, not signals known at the peak. The qualification time above is unchanged. '
                          'The chart label shows the highest actual rejection peak rounded to cents at $1 or above, '
                          'with more precision below $1. The ~ marks an approximate ceiling. '
                          'Exact source prices, padded bounds and oval positions are retained here.')
        paragraphs.append('\n'.join(f"{'Ceiling retest' if f.get('evidence_type')=='ceiling_retest' else 'Peak'} "
            f"{money(f['peak'])} at {clock(f['peak_time'])}; "
            f"{'rejection' if f.get('evidence_type')=='ceiling_retest' else 'failure'} confirmed at "
            f"{clock(f['failed_at'])}, closing at {money(f['failure_close'])} "
            + (f"after falling {money(f['peak']-f['failure_close'])} from the retest peak."
               if f.get('evidence_type')=='ceiling_retest' else
               f"after giving back {f['retracement']:.0%} of the rise from {money(f['base'])}.")
            for f in level['failures']))
        paragraphs.append('Nearby peaks are clustered within the greater of 0.5% of the first peak and two ticks, '
                          'without chaining into a wider area. The band adds the greater of one tick and 0.1% of the first peak on each side. '
                          f'Only the {session_date} session’s completed one-minute candles from 04:00 to 20:00 New York time qualify; gaps interrupt a rally and prevent tests on opposite sides of a gap from being combined. '
                          'The three nearby zones plus up to two additional unreclaimed overhead ceilings with at least three failures '
                          'are shown independently of daily levels, within 25% of the Draw quote.')
        if level.get('selection_reason') == 'repeated_tests':
            paragraphs.append('This ceiling is retained for its repeated failures even though three other zones are nearer. '
                              'Additional strong ceilings rank by test count, then latest failure, then proximity.')
        paragraphs.append('A rally needs a rising close at least 1% and two ticks above an earlier observed low. '
                          'A subsequent completed candle must close at least 60% of that rise and two ticks below the peak to confirm failure. '
                          'A candidate with no new high for ten minutes expires; a later surge uses recent consolidation lows after that peak. '
                          'These thresholds are our initial detector choices, not rules attributed to Ross.')
        paragraphs.append('After two full rally failures establish a ceiling, later local rejections can add tests. '
                          'A separate completed candle must remain below the touch area and close at least 1% and two ticks below the ceiling before each new approach from below. '
                          'A touch is within the greater of one tick and 0.1% of the then-known ceiling. '
                          'A later completed candle must close at least 1% and two ticks below the actual retest peak. '
                          'Adjacent touches count once, higher wicks outside that tolerance cancel the local candidate, '
                          'and missing minutes separate groups. Retests use the same volume requirements as full failures. '
                          'An overlapping full failure and retest count only once. New retests do not backdate the original qualification.')
        if level['state'] == 'reclaimed':
            paragraphs.append('Two consecutive completed one-minute closes sustained above the band plus one tick. '
                              'The zone is marked Reclaimed and retained as historical context.')
        elif level['state'] == 'returned_below':
            paragraphs.append('Price previously reclaimed this band, then a completed one-minute close returned below it. '
                              'That return does not count as an additional failed rally.')
        else:
            paragraphs.append('Repeated rally failures established this ceiling. A live wick or quote above it does not confirm a reclaim.')
        paragraphs.append('This is an observational chart reference, not an entry instruction. '
                          'No Level 2, tape, MACD or VWAP condition is required. The source is TradingView; DAS candles can differ.')
    for area in level.get('reaction_areas', [level] if 'origin' in level else []):
        zone=area['zone']; tests=area.get('independent_tests')
        evidence=f"Daily reaction area: {money(zone['low'])} to {money(zone['high'])}."
        if tests is not None:
            evidence+=f" {tests} independent daily test{'s' if tests!=1 else ''} contributed."
        paragraphs.append(evidence)
        state=area['state']
        notes={'crossed':'The Draw quote crossed this original area, but the completed daily closes have not confirmed a role change.',
               'retest':'The Draw quote returned across this Prior area. Its last confirmed daily role remains in place until a completed close establishes a reclaim.',
               'reclaimed':'Completed daily closes broke this area and later returned it to its original role. Its history is retained.',
               'flipped':'A completed daily close crossed the area and changed its confirmed role.',
               'retested':'After a confirmed daily role change, a later daily candle touched the area and closed back on the new side.'}
        if state in notes:paragraphs.append(notes[state])
        if area.get('history'):
            event=area['history'][-1]
            paragraphs.append(f"Latest confirmed role: {event['role']}, following the {source_date(event['time'])} close at {money(event['close'])}.")
        ratio=area.get('volume_ratio')
        if ratio and ratio>1.01:
            paragraphs.append(f"The strongest source-volume reading was {ratio:.2f} times its preceding available daily median. Volume helps rank this reference; it does not change its source price.")
    corridors=level.get('corridors',[level['corridor']] if 'corridor' in level else [])
    for corridor in corridors:
        name='Window' if corridor['id'].startswith('window:') else 'Gap'
        text=f"{name} source range: {money(corridor['low'])} to {money(corridor['high'])}."
        text+=f" Completed-candle interval: {money(corridor['remaining_low'])} to {money(corridor.get('remaining_high',corridor['high']))}."
        states={'unfilled':'Completed daily candles have not entered the original interval.',
                'partial':'Later completed daily candles have reduced the original interval.',
                'partial_today':'Today’s daily wick entered the remaining interval. The established completed-candle edges are retained.',
                'traversed_today':'Today’s daily wick reached the far gap boundary. These lines are reference prices; they do not describe an open gap today.',
                'crossed_quote':'The Draw quote is beyond the gap boundary, without a matching daily-wick fill observation. These are reference prices.',
                'filled_recent':'A completed daily candle filled this gap. These are recent historical references.'}
        text+=' '+states.get(corridor['state'],'')
        paragraphs.append(text)
        if corridor.get('method') == 'ross_daily_gap':
            paragraphs.append('Using Ross’s daily-chart method, this gap is the empty space between adjacent candle wick extremes. Later candles reduce the remaining interval; a partial return does not move the original full-fill target.')
            dates=[corridor.get('original_low_time'),corridor.get('original_high_time')]
            if all(t is not None for t in dates):
                paragraphs.append(f"Original gap edges: {money(corridor['low'])} from {source_date(dates[0])}; {money(corridor['high'])} from {source_date(dates[1])}.")
            width=corridor.get('width_filter')
            if width:
                paragraphs.append(f"The original gap was {money(width['original_width'])} wide and meets our price/tick minimum of {money(width['original_minimum_width'])}. This is our display filter; it does not require a percentage of the original gap to remain.")
                if corridor.get('display_mode')=='fill_target_only':
                    paragraphs.append(f"Only the full-fill boundary is drawn because the remaining gap is {money(width['remaining_width'])} wide, below the {money(width['minimum_width'])} pair-display minimum. The closely spaced entry line is omitted; the actual target price and original source date are retained.")
            if corridor['state'] in ('filled_recent','traversed_today'):
                paragraphs.append('Filled gap low and Filled gap high mark the two original daily wick boundaries. '
                                  'The gap has been traded through; these are historical reference prices, not outstanding fill targets. '
                                  'Both boundaries remain eligible when the original gap passes the same width filter as an open gap. '
                                  'Nearby references can still share one line under the normal spacing rules.')
                if corridor.get('filled_at') is not None:
                    paragraphs.append('First measured fill: '+source_date(corridor['filled_at'])+'. '
                                      'Completed daily fills remain eligible for up to 20 subsequent sessions, subject to proximity and ranking.')
                evidence=corridor.get('historical_evidence')
                if evidence:
                    count=evidence['independent_tests']
                    paragraphs.append(f"Historical selection found {count} independent daily boundary reaction{'s' if count!=1 else ''} after the fill. "
                                      'A later completed daily close must move at least 1% of the touched boundary and two ticks away. '
                                      'Adjacent encounters count once; another completed candle must leave the whole gap area before a further reaction counts. '
                                      'Proximity anchors ranking, with bounded bonuses for up to three reactions and a more recent fill. '
                                      'These are our display heuristics; a historical boundary does not guarantee a future reaction.')
                    for reaction in evidence['reactions']:
                        paragraphs.append(f"Boundary reaction at {money(reaction['price'])} on {source_date(reaction['time'])}; "
                                          f"the {source_date(reaction['confirmed_at'])} close at {money(reaction['close'])} confirmed the move away.")
        elif corridor.get('method') == 'ross_large_candle_window':
            paragraphs.append('Using Ross’s large-candle window method, entry is the exposed lower edge of a long red daily candle and top is that candle’s high. A later daily high can raise entry and narrow the window; reaching the source high covers it.')
            size=corridor.get('size_filter')
            if size:
                paragraphs.append(f"Automatic candidate selection requires a red body at least {size['body_multiple']:g} times the median of {size['prior_samples']} preceding nonzero daily bodies. This size filter is our automation choice; Ross’s lesson does not specify this multiplier. It does not use ATR.")
            width=corridor.get('width_filter')
            if width:
                paragraphs.append(f"The remaining window is {money(width['remaining_width'])} wide, or {width['remaining_fraction']:.0%} of its original range. It meets our minimum remaining-range filter of {width['min_remaining_fraction']:.0%} and the price/tick minimum of {money(width['minimum_width'])}.")
        low,high=corridor['remaining_low'],corridor.get('remaining_high',corridor['high'])
        if low < quote < high and corridor['state'] not in ('filled_recent','traversed_today','crossed_quote'):
            paragraphs.append(f"At Draw, the {money(quote)} quote was already inside this completed-candle interval. Entry is a historical boundary already crossed at that quote, rather than a breakout still ahead. The live quote does not replace the completed daily source edge.")
        for obstruction in (context or {}).get('obstructions',[]):
            if obstruction['corridor_id']==corridor['id']:
                names=[f"{CATALOG[x['kind']]['title'] if x['kind'] in CATALOG else 'computed daily 200 SMA'} at {money(x['price'])}" for x in obstruction['references']]
                paragraphs.append('References inside this interval: '+', '.join(dict.fromkeys(names))+'. The interval is not automatically clear of other levels.')
    if len(sources)>1 or any(abs(s.get('price',level['price'])-level['price'])>1e-9 for s in sources):
        paragraphs.append(f"Nearby references share one line at {money(level['price'])} to keep the chart readable. Their individual source prices are listed above; the prices were not averaged.")
    style=drawing_style(level,quote,sources)
    family=style['style_family']
    if family in ('daily','prior','corridor','event'):
        side='below' if level['price']<quote else 'at or above'
        color='green' if side=='below' else 'orange'
        shade=('deeper ' if level.get('drawing_theme')=='light' else 'brighter ') if family=='prior' else ''
        paragraphs.append(f"At Draw, this line was {side} the {money(quote)} quote, so it is {shade}{color} and {style['line_style']}. The color shows its position relative to that quote; it does not guarantee a reaction.")
    elif family == 'rally':
        paragraphs.append('Each ceiling has a distinct high-contrast group color, shared by all its peak ovals and its label. '
                          'Reclaimed ceilings use a softer shade of the same color. '
                          'The group color ties the peaks together; its softer shade identifies a reclaimed ceiling, independently of the live quote’s position.')
    elif family in ('ascending_support','descending_resistance'):
        color='green' if (family=='ascending_support') != (level.get('state')=='broken') else 'orange'
        meaning='after a confirmed break' if level.get('state')=='broken' else 'after a third confirmed reaction' if level.get('state')=='confirmed' else 'while provisional'
        paragraphs.append(f'The ray is thin and {color} and {style["line_style"]} {meaning}. Color describes this structure’s recorded state, not the live quote’s side.')
    elif family == 'support_zone':
        paragraphs.append('Support holds stay green to identify successful historical rebounds, independently of the current quote. '
                          'The ovals, label and UI row share the same green.')
    else:
        appearance={'premarket':'fuchsia and solid to identify the premarket range',
                    'day_range':'cyan and solid to identify today’s regular-session range',
                    'previous_range':'cyan and dashed to identify the previous regular-session range',
                    'previous_close':'gray and dotted to identify the previous regular-session close',
                    'previous_open':'gray and dashed to identify the previous regular-session open'}[family]
        paragraphs.append('This line is '+appearance+'. Its color identifies its source rather than its position above or below the Draw quote.')
    if len(sources)>1:
        precedence={'premarket':'Premarket','prior':'Prior daily','daily':'Daily support/resistance',
                    'corridor':'Gap/window','day_range':'Today’s regular-session range',
                    'previous_range':'Previous-session range','previous_close':'Previous close',
                    'previous_open':'Previous open','event':'Historical event'}[family]
        paragraphs.append(precedence+' styling takes precedence on this shared line. All contributing references remain listed above.')
    paragraphs.append('Price, session extremes and classifications refresh when you click Draw. Drawing colors also follow the panel’s theme setting.')
    if level.get('drawing_theme'):
        paragraphs.append('Drawing palette: '+level['drawing_theme']+'. Theme changes preserve the original Draw prices and evidence.')
    return '\n\n'.join(paragraphs)


def reaction_volume_explanation(level):
    evidence=level.get('holds',level.get('failures',[]))
    summary=level['volume']
    lines=[f"Volume evidence: {summary['elevated_tests']} of {len(evidence)} confirmed reactions had at least 1.5× expected local volume."]
    for index,test in enumerate(evidence,1):
        v=test['volume'];reaction=v['reaction'];away=v['reversal']
        when=datetime.fromtimestamp(v['from_time'],ZoneInfo('America/New_York')).strftime('%H:%M ET')
        relative=(f"{v['relative_volume']:.2f}× preceding same-phase median volume"
                  if v['relative_volume'] is not None else 'relative volume unavailable (insufficient comparable baseline or a session-phase crossing)')
        reversal=(f"{v['reversal_relative_volume']:.2f}×" if v['reversal_relative_volume'] is not None else 'unavailable')
        baseline=(f"Baseline: {v['baseline_median']:,.0f} shares per minute across {v['baseline_bars']} preceding {v['phase']} minutes."
                  if v['baseline_median'] is not None else f"Only {v['baseline_bars']} comparable preceding minutes were available; at least five are required.")
        lines.append(f"Test {index} at {when}: {relative}; reaction averaged {reaction['shares_per_minute']:,.0f} shares and ${reaction['dollars_per_minute']:,.0f} traded per minute. "
                     f"The subsequent reversal averaged {away['shares_per_minute']:,.0f} shares and ${away['dollars_per_minute']:,.0f} per minute; its relative volume was {reversal}. {baseline}")
    lines.append('Each counted test must average at least 100 shares and $500 traded per minute both across the reaction and across its reversal bars. '
                 'The reaction includes the extreme candle and up to three following completed minutes, ending no later than price confirmation. '
                 'Dollar activity is estimated from each candle’s volume and typical price; it is not measured volume at the exact level. '
                 'Expected local volume uses the median of up to 20 preceding consecutive completed minutes in the same premarket, regular or after-hours phase, with at least five required. '
                 'This is a local baseline, not historical same-clock-time relative volume. A missing or zero baseline gives no volume bonus; sufficient activity can still qualify. '
                 'Elevated volume improves selection within 1% proximity bands; it is not required on every test. '
                 'Missing volume cannot qualify a test. These initial thresholds are calibration choices, not Ross rules. '
                 'Volume measures participation, not who traded or whether they intended to defend the level.')
    return '\n'.join(lines)


def ascending_explanation(level):
    if level['kind']=='descending_resistance':return descending_explanation(level)
    clock=lambda t:datetime.fromtimestamp(t,ZoneInfo('America/New_York')).strftime('%m/%d %H:%M ET')
    lines=['Five-minute ascending support: '+level['state']+'.']
    for i,a in enumerate(level['anchors'],1):
        lines.append(f"Anchor {i}: actual wick low {money(a['price'])} on the {clock(a['time'])} five-minute candle; its rebound became confirmed at {clock(a['confirmed_at'])}.")
    lines.append(f"The line became available at {clock(level['qualified_at'])}, after the second rebound’s confirming candle closed. The original two anchors stay fixed. "
                 f"{level['independent_tests']} independent confirmed reactions respect this ray. Its five-minute projection at Draw was {money(level['price'])}; this is a moving diagonal reference, not a horizontal price level.")
    for h in level['touches'][2:]:
        lines.append(f"Additional touch: {money(h['price'])} on the {clock(h['time'])} candle; rebound confirmed at {clock(h['confirmed_at'])}.")
    if level['broken_at']:
        lines.append(f"Broken ascending support: two consecutive completed five-minute candles closed below the ray’s tolerance. The second closed at {money(level['broken_close'])} at {clock(level['broken_at'])}. "
                     'The ray is retained as a reference to the broken structure; this does not establish that a resistance retest has occurred or that resistance will hold. Later rallies do not erase the recorded break.')
    else:
        lines.append('Two anchors make this provisional. A third independent touch and confirmed rebound strengthen it. A single wick or isolated close below the ray does not confirm a break.')
    v=level['volume']
    lines.append(f"Volume evidence: {v['elevated_tests']} of {len(level['touches'])} reactions had at least 1.5× local expected volume.")
    for i,h in enumerate(level['touches'],1):
        volume=h['volume'];ratio=volume['relative_volume']
        relative=f"{ratio:.2f}× preceding same-phase median" if ratio is not None else 'unavailable comparable baseline'
        lines.append(f"Reaction {i}: {relative}; {volume['reaction']['shares_per_minute']:,.0f} shares/min and ${volume['reaction']['dollars_per_minute']:,.0f}/min in the reaction, "
                     f"with {volume['reversal']['shares_per_minute']:,.0f} shares/min and ${volume['reversal']['dollars_per_minute']:,.0f}/min in its rebound. "
                     f"The baseline used {volume['baseline_bars']} preceding five-minute candles in the same session phase.")
    lines.append('Uses only completed five-minute candles from the latest available US 04:00–20:00 New York session. A pullback must decline at least 1% and two ticks from its observed base; a later completed candle must rebound at least 1% and two ticks from the wick low. '
                 'The anchors use successive independent pullbacks, at least two five-minute bars apart, and a rise of at least 0.5% and two ticks to avoid nearly horizontal noise. A candidate with no new low for 30 minutes expires. '
                 'Touch and break tolerance is the greater of 0.25% of the projected price and two ticks. Candidates crossing two consecutive closes below that tolerance during formation are rejected. '
                 'Missing five-minute bars separate anchor sequences and reset consecutive-close counting. The slope uses native five-minute chart bar spacing; its displayed projection can differ on another interval or price scale. '
                 'Each reaction and its rebound must average at least 100 shares and $500 estimated traded value per minute. Elevated volume helps ranking but quiet retests can qualify. '
                 'Activity covers the wick candle and up to three subsequent completed candles, never beyond rebound confirmation; the baseline is up to 20 preceding same-phase five-minute candles, with at least five required. '
                 'Missing volume cannot qualify a reaction. This is local relative volume, not historical same-clock-time RVOL, and does not prove trader identity or intent. '
                 'Only one nearby ray is selected within 25% of the Draw quote, ranked by confirmed reaction count (capped at five), 1% proximity bands, intact state, volume and proximity. '
                 'This can retain a well-tested broken ray ahead of a weaker new candidate. A later Draw may select a stronger line; it does not refit an existing candidate’s anchors. '
                 'These thresholds are our explicit approximation, not John’s verified rules. Refresh on Draw.')
    return '\n\n'.join(lines)


def descending_explanation(level):
    clock=lambda t:datetime.fromtimestamp(t,ZoneInfo('America/New_York')).strftime('%m/%d %H:%M ET')
    lines=['Five-minute descending resistance: '+level['state']+'.']
    for i,a in enumerate(level['anchors'],1):
        lines.append(f"Anchor {i}: actual wick high {money(a['price'])} on the {clock(a['time'])} five-minute candle; its rejection became confirmed at {clock(a['confirmed_at'])}.")
    lines.append(f"The line became available at {clock(level['qualified_at'])}, after the second rejection’s confirming candle closed. Its two anchors stay fixed. "
                 f"{level['independent_tests']} independent confirmed rejections respect this ray. Its five-minute projection at Draw was {money(level['price'])}; this is a moving diagonal reference, not a horizontal level.")
    for h in level['touches'][2:]:
        lines.append(f"Additional touch: {money(h['price'])} on the {clock(h['time'])} candle; rejection confirmed at {clock(h['confirmed_at'])}.")
    if level['broken_at']:
        lines.append(f"Broken descending resistance: two consecutive completed five-minute candles closed above the ray’s tolerance. The second closed at {money(level['broken_close'])} at {clock(level['broken_at'])}. "
                     'The ray is retained as a reference to the broken structure; this does not establish that a support retest has occurred or that support will hold. Later declines do not erase the recorded break.')
    else:
        lines.append('Two anchors make this provisional. A third independent touch and confirmed rejection strengthen it. A single wick or isolated close above the ray does not confirm a break.')
    lines.append(f"Volume evidence: {level['volume']['elevated_tests']} of {len(level['touches'])} rejections had at least 1.5× local expected volume.")
    for i,h in enumerate(level['touches'],1):
        v=h['volume'];ratio=v['relative_volume']
        relative=f"{ratio:.2f}× preceding same-phase median" if ratio is not None else 'unavailable comparable baseline'
        lines.append(f"Rejection {i}: {relative}; {v['reaction']['shares_per_minute']:,.0f} shares/min and ${v['reaction']['dollars_per_minute']:,.0f}/min in the reaction, "
                     f"with {v['reversal']['shares_per_minute']:,.0f} shares/min and ${v['reversal']['dollars_per_minute']:,.0f}/min in its reversal. "
                     f"The baseline used {v['baseline_bars']} preceding five-minute candles in the same session phase.")
    lines.append('Uses completed five-minute candles from the latest actual US 04:00–20:00 New York session. A rally needs a rising close at least 1% and two ticks above its observed base low; a later candle must close at least 1% and two ticks below its actual wick high. '
                 'Two successive independent rallies can anchor a ray when at least two bars apart and the second high falls by at least 0.5% and two ticks. A candidate with no new high for 30 minutes expires. '
                 'Touch and break tolerance is max(0.25% of the projection, two ticks). A formation cutting through two consecutive closes above that tolerance is rejected. Missing bars separate anchor sequences and reset consecutive-close counting. '
                 'The ray uses native five-minute bar spacing; projection can differ on another interval or price scale while source anchor prices and times stay fixed. '
                 'Each reaction and reversal must average at least 100 shares and $500 estimated traded value per minute. The reaction includes the wick candle and up to three following completed candles, never beyond rejection confirmation. '
                 'Relative volume compares with up to 20 preceding same-phase five-minute candles, with at least five and a positive median required. It is local relative volume, not historical same-clock-time RVOL. Missing volume cannot qualify a reaction, but insufficient baseline only removes its ranking bonus. '
                 'Higher volume improves ranking and quieter rejections can still count. Volume does not identify traders or prove intent. '
                 'At most one nearby ray is selected for each trendline category within 25% of the Draw quote, ranked by reaction count capped at five, 1% proximity bands, intact state, volume, proximity and recency. A strong broken ray can outrank a weaker new candidate. '
                 'These thresholds mirror our ascending-support policy and are our automation choices, not John’s verified rules. Refresh on Draw.')
    return '\n\n'.join(lines)
