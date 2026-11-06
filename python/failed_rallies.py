"""Causal, completed-minute rally failures and bounded intraday resistance bands.

These are observational choices, not a Ross rule or an execution signal. A peak
is provisional until a later completed candle closes through its fade threshold.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import math
from reaction_volume import ReactionVolume, zone_volume, volume_priority

MIN_RISE = .01
FADE_FRACTION = .60
CLUSTER_WIDTH = .005
PADDING = .001
NEARBY_ZONES = 3
ADDITIONAL_STRONG_ZONES = 2
STRONG_TESTS = 3
PEAK_TIMEOUT = 10 * 60
RETEST_MOVE = .01
RETEST_TOLERANCE = .001
NY = ZoneInfo('America/New_York')


def rounded_reference(price, other):
    """Shared actual-price label precision for intraday ceilings and floors."""
    digits = 2 if price >= 1 else 3
    while digits < 6 and (round(price, digits) == 0 or
                         (price < 1 and other != price and round(other,digits) == round(price,digits))):
        digits += 1
    return f'~${price:.{digits}f}'


def band_label(low, high, tests, state):
    """Label the actual ceiling, not the artificial padded drawing bounds."""
    title = 'Reclaimed rally zone' if state == 'reclaimed' else 'Failed rallies'
    return f'{title} · {tests} tests · {rounded_reference(high,low)}'


def ceiling_retests(group, bars, participation, tick):
    """Confirm local rejections only after two full failures establish a ceiling.

    Require a separate completed candle away before each approach from below.
    A higher wick outside the touch tolerance cancels this candidate, preserving
    distinct higher ceilings. All decisions use evidence known at that minute.
    """
    qualified_at = group['failures'][1]['failed_at']
    result, candidate, base, previous = [], None, None, None
    for bar in bars:
        if bar['time'] <= qualified_at:
            continue
        known = [f for f in group['failures'] if f['failed_at'] <= bar['time']]
        # Missing minutes separate groups, including already established ones.
        if previous is None and bar['time'] != qualified_at+60:
            break
        if previous is not None and bar['time']-previous['time'] != 60:
            break
        ceiling = max(f['peak'] for f in known)
        tolerance = max(RETEST_TOLERANCE*ceiling, tick(ceiling))
        away = max(RETEST_MOVE*ceiling, 2*tick(ceiling))
        lower, upper = ceiling-tolerance, ceiling+tolerance
        if any(f['failed_at'] == bar['time'] for f in known):
            candidate, base = None, None
        elif bar['high'] > upper+1e-12:
            candidate, base = None, None
        elif candidate is not None:
            if bar['high'] > candidate['peak']+1e-12:
                candidate.update(peak=bar['high'], peak_time=bar['time'])
            rejection = max(RETEST_MOVE*candidate['peak'],
                            2*max(tick(candidate['peak']),tick(bar['close'])))
            if bar['time']-candidate['peak_time'] >= PEAK_TIMEOUT:
                candidate, base = None, None
            elif (bar['time'] > candidate['peak_time'] and
                  candidate['peak']-bar['close'] >= rejection-1e-12):
                volume = participation.measure(candidate['peak_time'], bar['time'])
                if volume['eligible']:
                    impulse = candidate['peak']-candidate['base']
                    result.append(dict(candidate, failed_at=bar['time'],
                        failure_close=bar['close'], retracement=(candidate['peak']-bar['close'])/impulse,
                        segment=group['segment'], volume=volume,
                        evidence_type='ceiling_retest', retest_ceiling=ceiling,
                        minimum_rejection=rejection))
                candidate, base = None, None
        elif (base is not None and previous is not None and previous['close'] < lower-1e-12
              and bar['high'] >= lower-1e-12):
            candidate = dict(base=base['low'], base_time=base['time'],
                             peak=bar['high'], peak_time=bar['time'])
        elif bar['high'] < lower-1e-12 and bar['close'] <= ceiling-away+1e-12:
            if base is None or bar['low'] < base['low']:
                base = bar
        previous = bar
    return result


def completed_minutes(bars, now=None):
    """Validate ordered OHLC and isolate completed minutes in one NY session."""
    now = (now or datetime.now(timezone.utc)).astimezone(NY)
    start = now.replace(hour=4, minute=0, second=0, microsecond=0).timestamp()
    end = min(now.timestamp() // 60 * 60, now.replace(hour=20, minute=0, second=0, microsecond=0).timestamp())
    selected = []
    previous_time = None
    for bar in bars:
        if any(not math.isfinite(bar[k]) for k in ('time', 'open', 'high', 'low', 'close')):
            raise ValueError('Nonfinite one-minute candle')
        if (bar['time'] % 60 or bar['low'] <= 0 or bar['low'] > min(bar['open'], bar['close'])
                or bar['high'] < max(bar['open'], bar['close'])):
            raise ValueError('Invalid one-minute OHLC candle')
        if previous_time is not None and bar['time'] <= previous_time:
            raise ValueError('One-minute candles must be strictly chronological')
        previous_time = bar['time']
        # No forming/future candle can confirm a peak, failure or reclaim.
        if start <= bar['time'] < end and bar.get('complete', True):
            selected.append(bar)
    return selected, start, end


def failed_rally_zones(bars, quote, now=None, tick=lambda price: .01):
    if not math.isfinite(quote) or quote <= 0:
        raise ValueError('Invalid failed-rally quote')
    selected, start, end = completed_minutes(bars, now)
    participation = ReactionVolume(selected)
    failures, previous, base, rally, recent = [], None, None, None, []
    segment = 0
    for bar in selected:
        step = tick(bar['high'])
        if not math.isfinite(step) or step <= 0:
            raise ValueError('Invalid failed-rally price tick')
        if previous is None or bar['time'] - previous['time'] != 60:
            segment += 1
            base, rally, previous = bar, None, bar
            recent = [bar]
            continue
        if rally is not None and bar['time'] - rally['peak_time'] >= PEAK_TIMEOUT:
            # A prolonged plateau ends this impulse. A later surge starts from
            # the recent consolidation, not a much older session low.
            consolidation = [b for b in recent[-10:] if b['time'] > rally['peak_time']]
            rally = None
            base = min(consolidation or recent[-10:], key=lambda b:b['low'])
        if rally is None:
            minimum = max(MIN_RISE * base['low'], 2 * max(step, tick(base['low'])))
            if bar['close'] > previous['close'] and bar['close'] - base['low'] >= minimum - 1e-12:
                rally = dict(base=base['low'], base_time=base['time'], peak=bar['high'], peak_time=bar['time'])
            elif bar['low'] < base['low']:
                base = bar
        else:
            if bar['high'] > rally['peak'] + 1e-12:
                rally.update(peak=bar['high'], peak_time=bar['time'])
            impulse = rally['peak'] - rally['base']
            fade = max(FADE_FRACTION * impulse, 2 * max(step, tick(rally['peak'])))
            if bar['time'] > rally['peak_time'] and rally['peak'] - bar['close'] >= fade - 1e-12:
                volume = participation.measure(rally['peak_time'], bar['time'])
                if volume['eligible']:
                    failures.append(dict(rally, failed_at=bar['time'], failure_close=bar['close'],
                                         retracement=(rally['peak']-bar['close'])/impulse,
                                         segment=segment, volume=volume))
                # This candle can end a rally, never also start the next test.
                base, rally = bar, None
        previous = bar
        recent = (recent + [bar])[-10:]

    groups = []
    for failure in failures:
        price = failure['peak']
        candidates = []
        for group in groups:
            high, low = max(group['high'], price), min(group['low'], price)
            width = max(CLUSTER_WIDTH * group['anchor'], 2 * max(tick(group['anchor']), tick(price)))
            if group['segment'] == failure['segment'] and high-low <= width + 1e-12:
                candidates.append(group)
        if candidates:
            group = min(candidates, key=lambda g:abs(g['anchor']-price))
            group['high'], group['low'] = max(group['high'],price), min(group['low'],price)
            group['failures'].append(failure)
        else:
            groups.append(dict(anchor=price, low=price, high=price, segment=failure['segment'], failures=[failure]))

    zones = []
    for group in groups:
        if len(group['failures']) < 2:
            continue
        # A local retest and a full rally can describe the same rejection.
        # Retain its earliest confirmation once, without changing qualification.
        evidence = []
        for failure in sorted(group['failures']+ceiling_retests(group,selected,participation,tick),
                              key=lambda f:f['failed_at']):
            if not any(failure['peak_time'] <= old['failed_at'] and
                       old['peak_time'] <= failure['failed_at'] for old in evidence):
                evidence.append(failure)
        group_low = min(f['peak'] for f in evidence)
        group_high = max(f['peak'] for f in evidence)
        # Keep every test inside the original fixed-anchor clustering policy.
        width = max(CLUSTER_WIDTH*group['anchor'],
                    2*max(tick(group['anchor']),tick(group_high),tick(group_low)))
        evidence = [f for f in evidence if
                    max(group['high'],f['peak'])-min(group['low'],f['peak']) <= width+1e-12]
        group_low = min(f['peak'] for f in evidence)
        group_high = max(f['peak'] for f in evidence)
        padding = max(PADDING * group['anchor'], tick(group['low']), tick(group['high']))
        low, high = max(tick(group_low), group_low-padding), group_high+padding
        qualified_at = group['failures'][1]['failed_at']
        state, above, history, seen_evidence, last = 'active', 0, [], [], None
        failure_times = {f['failed_at'] for f in evidence[1:]}
        for bar in selected:
            if bar['time'] < qualified_at:
                continue
            if last is not None and bar['time']-last != 60:
                above = 0
            last = bar['time']
            seen_evidence = [f for f in evidence if f['failed_at']<=bar['time']]
            known_peaks = [f['peak'] for f in seen_evidence]
            known_padding = max(PADDING * group['anchor'], *(tick(p) for p in known_peaks))
            known_low = min(known_peaks)-known_padding
            known_high = max(known_peaks)+known_padding
            if bar['time'] in failure_times:
                state, above = 'active', 0
            elif bar['close'] > known_high + tick(known_high) + 1e-12:
                above += 1
                if above >= 2 and state != 'reclaimed':
                    state = 'reclaimed'
                    history.append(dict(time=bar['time'], state=state, close=bar['close']))
            else:
                above = 0
                if state == 'reclaimed' and bar['close'] < known_low - 1e-12:
                    state = 'returned_below'
                    history.append(dict(time=bar['time'], state=state, close=bar['close']))
        label = band_label(group_low, group_high, len(evidence), state)
        zones.append(dict(kind='failed_rally', price=group_high, time=qualified_at,
                          description='Repeated intraday rally failures', display_text=label,
                          zone=dict(low=low, high=high), peak_bounds=dict(low=group_low,high=group_high),
                          retest_tests=sum(f.get('evidence_type')=='ceiling_retest' for f in evidence),
                          independent_tests=len(evidence), failures=evidence, volume=zone_volume(evidence), state=state, history=history,
                          qualified_at=qualified_at, display_start=start, last_failure=evidence[-1]['failed_at'],
                          end_time=max(qualified_at+60, end), method='completed_minute_rally_failures',
                          thresholds=dict(minimum_rise=MIN_RISE, fade_fraction=FADE_FRACTION,
                                          cluster_width=CLUSTER_WIDTH, padding=PADDING, minimum_ticks=2,
                                          peak_timeout_seconds=PEAK_TIMEOUT,
                                          retest_move=RETEST_MOVE,retest_tolerance=RETEST_TOLERANCE)))

    # Preserve near-price context plus stronger overhead ceilings. A newer,
    # nearer two-test band must not displace a repeatedly tested ceiling.
    zones = [z for z in zones if abs(z['price']-quote)/quote <= .25]
    def rank(z):
        low, high = z['zone']['low'], z['zone']['high']
        side = 0 if low <= quote <= high else 1 if low > quote else 2
        distance = max(low-quote, quote-high, 0)/quote
        return (z['state']=='reclaimed', side, int((distance+1e-12)/.01),
                tuple(-int(v) for v in volume_priority(z)), -z['independent_tests'], distance, -z['last_failure'])
    nearby = sorted(zones, key=rank)[:NEARBY_ZONES]
    for zone in nearby:
        zone['selection_reason'] = 'nearby'
    strong = [z for z in zones if z not in nearby
              and z['state'] != 'reclaimed' and z['zone']['high'] >= quote
              and z['independent_tests'] >= STRONG_TESTS]
    strong.sort(key=lambda z:(-z['independent_tests'], tuple(-int(v) for v in volume_priority(z)), -z['last_failure'],
                              max(z['zone']['low']-quote, 0)/quote))
    retained = strong[:ADDITIONAL_STRONG_ZONES]
    for zone in retained:
        zone['selection_reason'] = 'repeated_tests'
    return sorted(nearby + retained, key=lambda z:z['price'])
