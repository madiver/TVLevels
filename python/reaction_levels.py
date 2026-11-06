"""Daily reaction areas, reconstructed from completed candles on every Draw.

Operational heuristics, not a claimed reproduction of Ross's discretionary rules.
No intraday pivots or ATR are used. Source prices always remain actual daily edges.
"""
import math
from statistics import median


def reaction_levels(bars, current_price, near, tick):
    """Return significant areas with independent tests and closing-role history."""
    sources = []
    for i, candle in enumerate(bars[:-1]):
        previous = bars[max(0, i-1)]
        following = bars[i+1]
        history = bars[max(0, i-20):i+1]
        moves = [abs(b['close']-a['close']) for a, b in zip(history, history[1:])]
        typical = max(median(moves) if moves else abs(candle['close']-candle['open']),
                      .5*median([b['high']-b['low'] for b in history]))
        volumes = [b.get('volume', 0) for b in bars[max(0, i-20):i]
                   if isinstance(b.get('volume', 0), (int,float)) and math.isfinite(b.get('volume', 0)) and b.get('volume', 0)>0]
        volume = candle.get('volume', 0)
        volume_ratio = (volume / median(volumes) if len(volumes) >= 3 and
                        isinstance(volume, (int,float)) and math.isfinite(volume) and volume>0 else 1.0)
        for edge, origin in (('low', 'support'), ('high', 'resistance')):
            price = candle[edge]
            if price <= 0:
                continue
            floor = max(2*tick(price), .005*price)
            closes = [b['close'] for b in bars[i:min(i+4, len(bars))]]
            reaction = max(closes)-price if edge == 'low' else price-min(closes)
            if reaction < max(floor, typical*.5):
                continue
            local = (i > 0 and (price < min(previous[edge], following[edge]) if edge == 'low'
                               else price > max(previous[edge], following[edge])))
            impulse = previous['close']-price if edge == 'low' else price-previous['close']
            close_reaction = candle['close']-price if edge == 'low' else price-candle['close']
            large = (i > 0 and candle['high']-candle['low'] >= .20*previous['close'] and
                     close_reaction >= .10*price and (edge == 'low' or price >= previous['high']))
            prominent = large or (local and impulse >= max(floor, 2*typical) and
                                  reaction >= max(2*floor, 2*typical))
            sources.append(dict(price=price, time=candle['time'], index=i, origin=origin,
                                reaction=reaction, typical=max(typical, floor),
                                prominent=prominent, volume_ratio=volume_ratio))

    groups = []
    # A fixed actual boundary prevents chains of small differences spanning a wide zone.
    for source in sorted(sources, key=lambda s:(s['origin'], s['price'], s['time']), reverse=True):
        candidates = [g for g in groups if g[0]['origin'] == source['origin'] and
                      near(g[0]['price'], source['price'])]
        if candidates:
            min(candidates, key=lambda g:abs(g[0]['price']-source['price'])).append(source)
        else:
            groups.append([source])

    result = []
    for group in groups:
        origin = group[0]['origin']
        tests = []
        for source in sorted(group, key=lambda s:s['index']):
            if not tests:
                tests.append(source)
                continue
            last = tests[-1]
            middle = bars[last['index']+1:source['index']]
            distance = max(2*tick(source['price']), .005*source['price'])
            # A whole intervening candle must leave the boundary. Adjacent touches
            # or a flat shelf of touching wicks are not independent tests.
            departed = any(b['high'] < min(last['price'], source['price'])-distance or
                           b['low'] > max(last['price'], source['price'])+distance
                           for b in middle)
            if departed:
                tests.append(source)
            elif (source['price'] >= last['price'] if origin == 'resistance' else source['price'] <= last['price']):
                # A continuous testing event contributes one actual extreme,
                # not its earliest, less precise edge. Equal edges use newest.
                tests[-1] = source
        strong = [s for s in group if s['prominent']]
        if len(tests) < 2 and not strong:
            continue
        evidence = tests if len(tests) >= 2 else strong
        representative = (max(evidence, key=lambda s:(s['price'], s['time'])) if origin == 'resistance'
                          else min(evidence, key=lambda s:(s['price'], -s['time'])))
        lower, upper = min(s['price'] for s in evidence), max(s['price'] for s in evidence)
        first = min(s['index'] for s in evidence)
        role, events = origin, []
        for candle in bars[first+1:]:
            new_role = ('support' if candle['close'] > upper else
                        'resistance' if candle['close'] < lower else role)
            if new_role != role:
                events.append(dict(time=candle['time'], role=new_role, close=candle['close']))
                role = new_role
        flipped = role != origin
        live_role = ('support' if current_price > upper else
                     'resistance' if current_price < lower else role)
        pending = live_role != role
        state = ('retest' if pending and flipped else 'crossed' if pending else
                 'flipped' if flipped else 'reclaimed' if events else 'active')
        if flipped and not pending:
            since = events[-1]['time']
            retests = [b for b in bars if b['time'] > since and b['low'] <= upper and b['high'] >= lower]
            if any(b['close'] > upper if role == 'support' else b['close'] < lower for b in retests):
                state = 'retested'
        kind = ('former_support' if origin == 'support' else 'former_resistance') if flipped else origin
        name = ('Prior S' if origin == 'support' else 'Prior R') if flipped else (
            'Support' if origin == 'support' else 'Resistance')
        if pending:
            name = name+' retest' if flipped else ('Retest S' if origin == 'support' else 'Retest R')
        strength = (2*min(len(tests), 4) + min(max(s['reaction']/s['typical'] for s in evidence), 3) +
                    min(math.log2(max(1, max(s['volume_ratio'] for s in evidence))), 2) +
                    1/(1+(len(bars)-1-max(s['index'] for s in evidence))/60))
        area = dict(price=representative['price'], time=representative['time'], kind=kind,
                    description='Daily reaction area', display_text=name, origin=origin,
                    confirmed_role=role, state=state, strength=round(strength, 3),
                    zone=dict(low=lower, high=upper), independent_tests=len(tests),
                    volume_ratio=round(max(s['volume_ratio'] for s in evidence), 3),
                    history=events,
                    # Preserve every actual contributing price outside compact chart labels.
                    source_prices=[dict(price=s['price'], time=s['time']) for s in evidence])
        if flipped:
            area['prior_times'] = {kind:representative['time']}
        result.append(area)
    return result


def selection_rank(level, current_price):
    """Proximity with a bounded preference for better daily reaction evidence."""
    distance = abs(math.log(level['price']/current_price))
    return (distance/(1+.10*min(level.get('strength', 0), 10)),
            -level.get('strength', 0), -level['time'])


def corridor_reach(bars):
    """Operational relevance range; expanding sessions widen it without ATR."""
    ranges = [(b['high']-b['low'])/b['close'] for b in bars[-20:] if b['close'] > 0]
    return max(.25, 2*median(ranges), ranges[-1]) if ranges else .25


def daily_context(bars, levels, reference_levels=None):
    """Computed daily context only; never invent a drawing or claim it is a TV study."""
    sma = sum(b['close'] for b in bars[-200:])/200 if len(bars) >= 200 else None
    obstructions = []
    reference_levels = levels if reference_levels is None else reference_levels
    corridors = {c['id']:c for level in levels for c in
                 level.get('corridors', [level['corridor']] if 'corridor' in level else [])}
    for corridor in corridors.values():
        low, high = corridor['remaining_low'], corridor.get('remaining_high', corridor['high'])
        references = [dict(price=x['price'], kind=x['kind'], time=x['time']) for x in reference_levels
                      if x['kind'] not in ('gap', 'window') and low < x['price'] < high]
        if sma is not None and low < sma < high:
            references.append(dict(price=sma, kind='computed_daily_sma200'))
        if references:
            obstructions.append(dict(corridor_id=corridor['id'], references=references))
    return dict(computed_daily_sma200=sma, available_daily_bars=len(bars), obstructions=obstructions)


def gap_corridors(bars, current_day=None):
    """True wick gaps; completed candles determine edges, today's wick sets status.

    Filled gaps are historical references for at most 20 completed sessions.
    Relevance and pair selection are applied separately by the drawing selector.
    """
    result = []
    for i in range(1, len(bars)):
        previous, source = bars[i-1:i+1]
        if source['high'] < previous['low']:
            direction, low, high = 'up', source['high'], previous['low']
            lower_time, upper_time = source['time'], previous['time']
        elif source['low'] > previous['high']:
            direction, low, high = 'down', previous['high'], source['low']
            lower_time, upper_time = previous['time'], source['time']
        else:
            continue
        later = [b for b in bars[i+1:] if not current_day or b['time'] != current_day['time']]
        fills = [b for b in later if b['high'] >= high] if direction == 'up' else [b for b in later if b['low'] <= low]
        state = 'unfilled'
        remaining_low, remaining_high = low, high
        if fills:
            age = len(bars)-1-next(j for j,b in enumerate(bars) if b is fills[0])
            if age > 20:
                continue
            state = 'filled_recent'
        elif direction == 'up':
            edge = max(reversed([source]+later), key=lambda b:b['high'])
            remaining_low, lower_time = edge['high'], edge['time']
            if remaining_low > low:
                state = 'partial'
        else:
            edge = min(reversed([source]+later), key=lambda b:b['low'])
            remaining_high, upper_time = edge['low'], edge['time']
            if remaining_high < high:
                state = 'partial'
        # Live candles affect lifecycle only. A forming wick never silently
        # replaces the proven daily boundaries used to draw the pair.
        if current_day and not fills:
            filled_today = current_day['high'] >= high if direction == 'up' else current_day['low'] <= low
            partial_today = current_day['high'] > remaining_low if direction == 'up' else current_day['low'] < remaining_high
            if filled_today:
                state = 'traversed_today'
            elif partial_today:
                state = 'partial_today'
        corridor = dict(id=f"gap:{source['time']}:{direction}", low=low, high=high,
                        remaining_low=remaining_low, remaining_high=remaining_high,
                        source_time=source['time'], state=state, direction=direction,
                        method='ross_daily_gap',
                        original_low_time=source['time'] if direction == 'up' else previous['time'],
                        original_high_time=previous['time'] if direction == 'up' else source['time'])
        historical = state in ('filled_recent', 'traversed_today')
        low_name, high_name = ('Gap entry', 'Gap fill') if direction == 'up' else ('Gap fill down', 'Gap entry down')
        if historical:
            # A measured fill ends the open corridor. Restore its two known
            # original edges, including after today's wick crosses a remnant.
            remaining_low, remaining_high = low, high
            lower_time, upper_time = corridor['original_low_time'], corridor['original_high_time']
            corridor.update(remaining_low=low, remaining_high=high,
                            filled_at=fills[0]['time'] if fills else current_day['time'],
                            fill_age_sessions=age if fills else 0)
        low_display, high_display = (('Filled gap low', 'Filled gap high') if historical else
                                    (low_name.replace('Gap fill', 'Gap fill target'),
                                     high_name.replace('Gap fill', 'Gap fill target')))
        result.append((dict(price=remaining_low, time=lower_time, kind='gap', description=low_name,
                            display_text=low_display, corridor=corridor),
                       dict(price=remaining_high, time=upper_time, kind='gap', description=high_name,
                            display_text=high_display, corridor=corridor)))
    return result
