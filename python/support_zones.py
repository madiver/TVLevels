"""Confirmed intraday support holds after meaningful selloffs.

The thresholds mirror our rally detector; they are engineering choices, not a
Ross rule. Historical troughs are annotated only after later rebound evidence.
"""
import math
from reaction_volume import ReactionVolume, zone_volume, volume_priority
from failed_rallies import (completed_minutes, MIN_RISE, FADE_FRACTION,
                           CLUSTER_WIDTH, PADDING, PEAK_TIMEOUT, NEARBY_ZONES,
                           ADDITIONAL_STRONG_ZONES, STRONG_TESTS,
                           RETEST_MOVE, RETEST_TOLERANCE, rounded_reference)

MIN_TESTS = 2


def support_label(low, high, tests):
    """Show the actual floor; precise source lows and padding stay in Details."""
    title = 'Support hold' if tests == 1 else 'Support holds'
    count = '1 test' if tests == 1 else f'{tests} tests'
    return f'{title} · {count} · {rounded_reference(low,high)}'


def floor_retests(group, bars, participation, step):
    """Mirror ceiling retests using completed approaches from above and bounces.

    Two full selloff/rebound holds must establish the floor first. Later lower
    wicks cancel a local candidate without relabeling the historical holds.
    """
    qualified_at = group['holds'][MIN_TESTS-1]['confirmed_at']
    result, candidate, base, previous = [], None, None, None
    for bar in bars:
        if bar['time'] <= qualified_at:
            continue
        known = [h for h in group['holds'] if h['confirmed_at'] <= bar['time']]
        if previous is None and bar['time'] != qualified_at+60:
            break
        if previous is not None and bar['time']-previous['time'] != 60:
            break
        floor = min(h['trough'] for h in known)
        tolerance = max(RETEST_TOLERANCE*floor, step(floor))
        away = max(RETEST_MOVE*floor, 2*step(floor))
        lower, upper = floor-tolerance, floor+tolerance
        if any(h['confirmed_at'] == bar['time'] for h in known):
            candidate, base = None, None
        elif bar['low'] < lower-1e-12:
            candidate, base = None, None
        elif candidate is not None:
            if bar['low'] < candidate['trough']-1e-12:
                candidate.update(trough=bar['low'], trough_time=bar['time'])
            rebound = max(RETEST_MOVE*candidate['trough'],
                          2*max(step(candidate['trough']),step(bar['close'])))
            if bar['time']-candidate['trough_time'] >= PEAK_TIMEOUT:
                candidate, base = None, None
            elif (bar['time'] > candidate['trough_time'] and
                  bar['close']-candidate['trough'] >= rebound-1e-12):
                volume = participation.measure(candidate['trough_time'],bar['time'])
                if volume['eligible']:
                    impulse = candidate['base']-candidate['trough']
                    result.append(dict(candidate,confirmed_at=bar['time'],
                        confirmation_close=bar['close'],recovery=(bar['close']-candidate['trough'])/impulse,
                        segment=group['segment'],volume=volume,
                        evidence_type='floor_retest',retest_floor=floor,minimum_rebound=rebound))
                candidate, base = None, None
        elif (base is not None and previous is not None and previous['close'] > upper+1e-12
              and bar['low'] <= upper+1e-12):
            candidate = dict(base=base['high'],base_time=base['time'],
                             trough=bar['low'],trough_time=bar['time'])
        elif bar['low'] > upper+1e-12 and bar['close'] >= floor+away-1e-12:
            if base is None or bar['high'] > base['high']:
                base = bar
        previous = bar
    return result


def support_zones(bars, quote, now=None, tick=lambda price: .01):
    if not math.isfinite(quote) or quote <= 0:
        raise ValueError('Invalid support-zone quote')
    selected, start, end = completed_minutes(bars, now)
    participation = ReactionVolume(selected)

    def step(price):
        value = tick(price)
        if not math.isfinite(value) or value <= 0:
            raise ValueError('Invalid support-zone price tick')
        return value

    holds, recent, previous, base, selloff = [], [], None, None, None
    segment = 0
    for bar in selected:
        step(bar['low'])
        if previous is None or bar['time'] - previous['time'] != 60:
            segment += 1
            base, selloff, previous, recent = bar, None, bar, [bar]
            continue
        if selloff is not None and bar['time'] - selloff['trough_time'] >= PEAK_TIMEOUT:
            consolidation = [b for b in recent[-10:] if b['time'] > selloff['trough_time']]
            selloff = None
            base = max(consolidation or recent[-10:], key=lambda b:b['high'])
        if selloff is None:
            minimum = max(MIN_RISE * base['high'], 2 * max(step(bar['low']), step(base['high'])))
            if bar['close'] < previous['close'] and base['high'] - bar['close'] >= minimum - 1e-12:
                selloff = dict(base=base['high'], base_time=base['time'],
                               trough=bar['low'], trough_time=bar['time'])
            elif bar['high'] > base['high']:
                base = bar
        else:
            if bar['low'] < selloff['trough'] - 1e-12:
                selloff.update(trough=bar['low'], trough_time=bar['time'])
            impulse = selloff['base'] - selloff['trough']
            rebound = max(FADE_FRACTION * impulse, 2 * max(step(bar['low']), step(selloff['trough'])))
            if bar['time'] > selloff['trough_time'] and bar['close'] - selloff['trough'] >= rebound - 1e-12:
                volume = participation.measure(selloff['trough_time'], bar['time'])
                if volume['eligible']:
                    holds.append(dict(selloff, confirmed_at=bar['time'], confirmation_close=bar['close'],
                                      recovery=(bar['close']-selloff['trough'])/impulse,
                                      segment=segment, volume=volume))
                base, selloff = bar, None
        previous = bar
        recent = (recent + [bar])[-10:]

    groups = []
    for hold in holds:
        price = hold['trough']
        candidates = [g for g in groups if g['segment'] == hold['segment']
                      and max(g['high'],price)-min(g['low'],price)
                      <= max(CLUSTER_WIDTH*g['anchor'],2*max(step(g['anchor']),step(price))) + 1e-12]
        if candidates:
            group = min(candidates,key=lambda g:abs(g['anchor']-price))
            group['high'],group['low'] = max(group['high'],price),min(group['low'],price)
            group['holds'].append(hold)
        else:
            groups.append(dict(anchor=price, low=price, high=price,
                               segment=hold['segment'], holds=[hold]))

    zones = []
    for group in groups:
        if len(group['holds']) < MIN_TESTS:
            continue
        # Keep the earliest confirmation once when both methods see one bounce.
        evidence = []
        for hold in sorted(group['holds']+floor_retests(group,selected,participation,step),
                           key=lambda h:h['confirmed_at']):
            if not any(hold['trough_time'] <= old['confirmed_at'] and
                       old['trough_time'] <= hold['confirmed_at'] for old in evidence):
                evidence.append(hold)
        group_low = min(h['trough'] for h in evidence)
        group_high = max(h['trough'] for h in evidence)
        width = max(CLUSTER_WIDTH*group['anchor'],
                    2*max(step(group['anchor']),step(group_low),step(group_high)))
        evidence = [h for h in evidence if
                    max(group['high'],h['trough'])-min(group['low'],h['trough']) <= width+1e-12]
        group_low = min(h['trough'] for h in evidence)
        group_high = max(h['trough'] for h in evidence)
        qualified_at = group['holds'][MIN_TESTS-1]['confirmed_at']
        padding = max(PADDING*group['anchor'], *(step(f['trough']) for f in evidence))
        low, high = max(step(group_low),group_low-padding),group_high+padding
        zones.append(dict(kind='support_zone',price=group_low,time=qualified_at,
                          description='Confirmed intraday support holds',
                          display_text=support_label(group_low,group_high,len(evidence)),
                          zone=dict(low=low,high=high),trough_bounds=dict(low=group_low,high=group_high),
                          retest_tests=sum(h.get('evidence_type')=='floor_retest' for h in evidence),
                          independent_tests=len(evidence),holds=evidence,volume=zone_volume(evidence),
                          qualified_at=qualified_at,display_start=start,last_hold=evidence[-1]['confirmed_at'],
                          end_time=max(qualified_at+60,end),method='completed_minute_support_holds',
                          thresholds=dict(minimum_tests=MIN_TESTS,minimum_decline=MIN_RISE,rebound_fraction=FADE_FRACTION,
                                          cluster_width=CLUSTER_WIDTH,padding=PADDING,minimum_ticks=2,
                                          trough_timeout_seconds=PEAK_TIMEOUT,
                                          retest_move=RETEST_MOVE,retest_tolerance=RETEST_TOLERANCE)))

    zones = [z for z in zones if abs(z['price']-quote)/quote <= .25]
    def rank(z):
        low,high = z['zone']['low'],z['zone']['high']
        side = 0 if low <= quote <= high else 1 if high < quote else 2
        distance=max(low-quote,quote-high,0)/quote
        return side,int((distance+1e-12)/.01),tuple(-int(v) for v in volume_priority(z)),-z['independent_tests'],distance,-z['last_hold']
    nearby = sorted(zones,key=rank)[:NEARBY_ZONES]
    for zone in nearby:
        zone['selection_reason'] = 'nearby'
    strong = [z for z in zones if z not in nearby and z['zone']['low'] <= quote and z['independent_tests'] >= STRONG_TESTS]
    strong.sort(key=lambda z:(-z['independent_tests'],tuple(-int(v) for v in volume_priority(z)),-z['last_hold'],max(quote-z['zone']['high'],0)/quote))
    retained = strong[:ADDITIONAL_STRONG_ZONES]
    for zone in retained:
        zone['selection_reason'] = 'repeated_tests'
    return sorted(nearby+retained,key=lambda z:z['price'])
