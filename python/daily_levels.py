#!/usr/bin/env python3
"""Draw daily levels and today's US equity premarket range through TradingView MCP."""
import argparse
import json
import math
import subprocess
import sys
import time
from statistics import median
from datetime import datetime, timezone, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
from mcp_transport import StdioRPC
from reaction_levels import reaction_levels, selection_rank, corridor_reach, daily_context, gap_corridors
from window_policy import window_width_filter
from gap_policy import gap_width_filter, historical_gap_evidence, historical_gap_rank
from failed_rallies import failed_rally_zones
from support_zones import support_zones
from ascending_support import ascending_support, trend_marks
from descending_resistance import descending_resistance
from rally_marks import rally_marks, support_marks
from event_levels import EVENT_TYPES, LOOKBACK, event_levels

PREFIX = '[DailyLevels] '
from level_catalog import LEVEL_TYPES, LEVEL_NAMES, GROUPS
from reference_levels import (PREVIOUS_TYPES, TODAY_TYPES, REFERENCE_TYPES,
                              explicit_references, regular_day_levels)
PREMARKET_TYPES = frozenset(('premarket_high', 'premarket_low'))
STRUCTURE_TYPES = frozenset(('resistance','support','gap','window','former_support','former_resistance'))
DAILY_TYPES = STRUCTURE_TYPES | PREVIOUS_TYPES | EVENT_TYPES
SESSION_TYPES = PREMARKET_TYPES | TODAY_TYPES
from level_styles import drawing_style, STYLE_LEGEND, LIGHT_COLORS, assign_rally_colors


def selected_types(enabled_types=None):
    enabled = frozenset(LEVEL_TYPES if enabled_types is None else enabled_types)
    if not enabled or not enabled.issubset(LEVEL_TYPES):
        raise ValueError('Select at least one valid level type')
    return enabled

class MCP:
    def __init__(self, root, *, request_timeout=30.0, startup_timeout=15.0):
        from runtime_config import resolve_mcp_root
        root = Path(root).resolve()
        self.mcp_root = resolve_mcp_root(root)
        self.process = subprocess.Popen(['node', str(self.mcp_root / 'src/server.js')], cwd=self.mcp_root,
                                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.ownership_path = root / 'python/.daily-levels-owned.json'
        self.details_path = root / '.local/panel/level-details.json'
        try:
            self.rpc = StdioRPC(self.process, request_timeout)
            self.request('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                         'clientInfo': {'name': 'daily-levels-python', 'version': '1.0'}}, timeout=startup_timeout)
            self.send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        except BaseException:
            self.close()
            raise

    def send(self, message):
        self.rpc.send(message)

    def request(self, method, params, *, timeout=None):
        return self.rpc.request(method, params, timeout)

    def call(self, name, **arguments):
        result = self.request('tools/call', {'name': name, 'arguments': arguments})
        data = json.loads(next(c['text'] for c in result['content'] if c['type'] == 'text'))
        if result.get('isError') or data.get('success') is False:
            raise RuntimeError(str(data))
        return data

    def bind_selected(self):
        from pane_client import PaneClient
        self.call('tab_follow_visible')
        return PaneClient(self)

    def close(self):
        if self.process.poll() is None:
            try:
                self.process.terminate()
            except ProcessLookupError:
                pass
        try:
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=5)
        self.process.stdin.close()
        self.process.stdout.close()


def release_bound(client):
    if not hasattr(client, 'release'):
        return
    failed = sys.exc_info()[0] is not None
    try:
        client.release()
    except Exception:
        # A release failure must not hide the action/restoration error.
        if not failed:
            raise


def confirmed(bars, now=None):
    """Exclude today's daily bar before regular-session close, without inferring holiday calendars."""
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/New_York'))
    return [b for b in bars if datetime.fromtimestamp(b['time'], timezone.utc).astimezone(
        ZoneInfo('America/New_York')).date() < now.date() or
        (datetime.fromtimestamp(b['time'], timezone.utc).astimezone(ZoneInfo('America/New_York')).date()
         == now.date() and now.hour >= 16)]


def latest_quote(quote):
    """Newest trade, normalizing numeric strings and resolving extended-session ties."""
    def number(value):
        if isinstance(value, bool):
            return None
        try:
            result = float(value)
        except (TypeError, ValueError):
            return None
        return result if math.isfinite(result) and result > 0 else None
    candidates = []
    session = quote.get('session', '')
    for field, clock in [('last_price', 'lp_time'), ('rtc', 'rtc_time'), ('ntc', 'ntc_time')]:
        price, timestamp = number(quote.get(field)), number(quote.get(clock))
        # Some quote feeds refresh lp_time while last_price is still the regular
        # close. Its actual close timestamp is authoritative outside that session.
        if field == 'last_price' and session in ('pre_market', 'post_market') and number(quote.get('rtc')) is not None and number(quote.get('rtc_time')) is not None:
            # The provider can refresh BOTH close clocks during extended trading.
            # A timestamped trade in the explicitly active session is authoritative.
            continue
        if field == 'last_price' and session == 'out_of_session':
            timestamp = number(quote.get('regular_close_time')) or timestamp
        if price is not None and timestamp is not None:
            candidates.append(dict(price=price, time=timestamp, source=field))
    if not candidates:
        raise RuntimeError('Selected chart has no timestamped current quote; try again when quotes load')
    preferred = 'rtc' if session in ('pre_market', 'post_market') else 'ntc' if session == 'overnight' else 'last_price'
    result = max(candidates, key=lambda q: (q['time'], q['source'] == preferred))
    minimum, scale = number(quote.get('minmov')), number(quote.get('pricescale'))
    if minimum is not None and scale is not None:
        result['tick_size'] = minimum / scale
    if isinstance(quote.get('variable_tick_size'), str):
        result['variable_tick_size'] = quote['variable_tick_size']
    return result


def read_reference(client, timeout=4.0, fallback=None):
    """Wait for the selected pane's quote; keep a valid pre-switch snapshot on reload."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            current = latest_quote(client.call('quote_snapshot'))
            if fallback is not None:
                for key in ('tick_size', 'variable_tick_size'):
                    if key not in current and key in fallback:
                        current[key] = fallback[key]
            return current if fallback is None or current['time'] >= fallback['time'] else fallback
        except RuntimeError as error:
            # Selection/symbol/network failures must not be mistaken for loading.
            if not any(reason in str(error) for reason in ('no timestamped current quote', 'quotes have not loaded')):
                raise
            if time.monotonic() >= deadline:
                if fallback is not None:
                    return fallback
                raise RuntimeError('Chart quotes are still loading. Wait a moment, then click Draw levels.') from error
            time.sleep(.2)


def price_tick(price, tick_size=0.01, variable_tick_size=None):
    """TradingView variable ladder: tick, upper bound, tick, upper bound, ..., tick."""
    if variable_tick_size:
        try:
            ladder = [float(x) for x in variable_tick_size.split()]
            if len(ladder) % 2 != 1 or any(not math.isfinite(x) or x <= 0 for x in ladder):
                raise ValueError('Invalid tick ladder')
            for i in range(0, len(ladder)-1, 2):
                if price < ladder[i+1]:
                    return ladder[i]
            return ladder[-1]
        except (ValueError, AttributeError):
            pass
    return tick_size


def levels_near(a, b, tick_size=0.01, variable_tick_size=None):
    spacing = max(2 * max(price_tick(a, tick_size, variable_tick_size),
                          price_tick(b, tick_size, variable_tick_size)), .005 * max(a, b))
    return abs(a-b) < spacing - 1e-12


def spaced_levels(levels, tick_size=0.01, variable_tick_size=None):
    """Use exact PM boundaries first, then highest daily boundaries; no chain bridging."""
    groups = []
    for level in sorted(levels, key=lambda x:(3 if x['kind'] in PREMARKET_TYPES else 2,x['price']), reverse=True):
        nearby = [g for g in groups if levels_near(g[0]['price'], level['price'], tick_size, variable_tick_size)]
        if nearby:
            min(nearby, key=lambda g:abs(g[0]['price']-level['price'])).append(level)
        else:
            groups.append([level])
    result = []
    for group in groups:
        representative = dict(group[0])
        if representative['kind'] not in PREMARKET_TYPES:
            if any(x['kind']=='gap' for x in group):
                representative['kind'] = 'gap'
            elif any(x['kind']=='window' for x in group):
                representative['kind'] = 'window'
        # Keep the daily source date when a PM or nearby daily boundary wins
        # the displayed price. Carry it through subsequent spacing passes too.
        prior_times = {}
        for level in group:
            if level['kind'] in ('former_support', 'former_resistance'):
                prior_times.setdefault(level['kind'], level['time'])
            for kind, timestamp in level.get('prior_times', {}).items():
                prior_times.setdefault(kind, timestamp)
        if prior_times:
            representative['prior_times'] = prior_times
        if len(group) > 1:
            sources = []
            for level in group:
                for source in label_sources(level):
                    if source not in sources:
                        sources.append(source)
            representative['label_sources'] = sources
        areas = [dict(origin=x['origin'], zone=x['zone'], state=x['state'],
                      confirmed_role=x['confirmed_role'], strength=x['strength'],
                      source_prices=x['source_prices'], history=x['history'],
                      independent_tests=x.get('independent_tests'), volume_ratio=x.get('volume_ratio'),
                      time=x.get('time'), price=x.get('price'))
                 for x in group if 'origin' in x]
        areas += [a for x in group for a in x.get('reaction_areas', []) if a not in areas]
        if areas:
            representative['reaction_areas'] = areas
            representative['strength'] = max(a['strength'] for a in areas)
        corridors = [c for x in group for c in
                     x.get('corridors', [x['corridor']] if 'corridor' in x else [])]
        if corridors:
            representative['corridors'] = list({c['id']:c for c in corridors}.values())
        events = [dict(x['event'],kind=x['kind'],price=x['price'],time=x['time']) for x in group if 'event' in x and not x.get('events')]
        events += [e for x in group for e in x.get('events',[]) if e not in events]
        if events:
            representative['events'] = events
        if len(group) > 1:
            kinds = set(x['kind'] for x in group)
            if any('Window' in x['description'] for x in group):
                kinds.add('window')
            names = LEVEL_NAMES
            labels = set(names[k] for k in kinds)
            for x in group:
                labels.update(x.get('label', '').split(' / '))
            representative['label'] = ' / '.join(n for n in names.values() if n in labels)
        result.append(representative)
    return sorted(result, key=lambda x:x['price'])


def undated_label(level):
    if level.get('display_text'):
        return level['display_text']
    label = level.get('label') or (LEVEL_NAMES[level['kind']]
                                  if level['kind'] not in ('gap', 'window') else None)
    if label is None:
        label = (level['description'] if level['kind'] == 'window' or
                 level['description'] == 'Gap fill / Window entry' else
                 'Gap entry' if 'entry' in level['description'].lower() else 'Gap fill')
    return label


def label_sources(level):
    """Provenance of each reference, independent of a merged line's price/time."""
    if 'label_sources' in level:
        return level['label_sources']
    if level['kind'] in ('failed_rally','support_zone','ascending_support','descending_resistance'):
        # "Support hold" begins with the daily "Support" label, but its
        # evidence and category remain intraday.
        return [dict(kind=level['kind'],text=undated_label(level),
                     price=level['price'],time=level['time'])]
    sources = []
    for text in undated_label(level).split(' / '):
        kind = next((k for k, name in LEVEL_NAMES.items()
                     if text == name or text.startswith(name + ' ')), level['kind'])
        sources.append(dict(kind=kind, text=text, price=level['price'],
                            time=level.get('prior_times', {}).get(kind, level['time'])))
    return sources


def drawing_label(level, now=None):
    market_zone = ZoneInfo('America/New_York')
    today = (now or datetime.now(timezone.utc)).astimezone(market_zone).date()
    order = {kind:i for i,kind in enumerate(LEVEL_NAMES)}
    parts = []
    for source in sorted(label_sources(level), key=lambda x:(order[x['kind']], x['text'], -x['time'])):
        date = datetime.fromtimestamp(source['time'], market_zone).date()
        text = source['text'] if date == today else f"{source['text']} {date.strftime('%m/%d')}"
        if text not in parts:
            parts.append(text)
    return ' / '.join(parts)


def drawing_color(level, current_price):
    """Compatibility wrapper around the shared family/merged-source style policy."""
    return drawing_style(level,current_price,label_sources(level))['color']


def candle_windows(bars, body_multiple=2.0):
    """Ross's long-candle window boundaries; size filtering is an automation choice."""
    corridors = []
    for i, candle in enumerate(bars[:-1]):
        prior = bars[max(0, i-20):i]
        bodies = [abs(b['close']-b['open']) for b in prior if b['close'] != b['open']]
        if len(bodies) < 3 or candle['open'] <= candle['close']:
            continue
        if candle['open']-candle['close'] < body_multiple * median(bodies):
            continue
        later = bars[i+1:]
        # Ross's GLBS example at 7:11 has a later daily high ($8.77) as
        # entry below the large candle's $19.50 top. A partial revisit moves
        # the entry to an actual newer high, never to an interpolated price.
        entry = max(reversed(later), key=lambda b:b['high'])
        left, right = max(candle['low'], entry['high']), candle['high']
        left_time = entry['time'] if entry['high'] >= candle['low'] else candle['time']
        if left >= right or left >= candle['open'] or right <= candle['close']:
            continue
        corridor = dict(id=f"window:{candle['time']}", low=candle['low'], high=right,
                        remaining_low=left, source_time=candle['time'],
                        state='partial' if left > candle['low'] else 'unfilled',
                        method='ross_large_candle_window',
                        original_low_time=candle['time'], original_high_time=candle['time'],
                        size_filter=dict(body_multiple=body_multiple, median_body=median(bodies),
                                         prior_samples=len(bodies)))
        corridors.append((dict(price=left, kind='window', time=left_time, description='Window entry', corridor=corridor),
                          dict(price=right, kind='window', time=candle['time'], description='Window top', corridor=corridor)))
    return corridors


def historical_peaks(bars, lookback=60, min_rise=.10, min_pullback=.10):
    """Legacy review helper; Draw uses the shared reaction-area detector.

    This bounded price-excursion heuristic augments unbroken highs; it does not
    redefine shadowing for gap/window endpoints or require ATR/volume data.
    Only one completed candle on either side is needed for the reversal.
    """
    result = []
    for i in range(max(1, len(bars)-lookback), len(bars)-1):
        previous, candle, following = bars[i-1:i+2]
        high = candle['high']
        if (high <= max(previous['high'], following['high']) or
                high < previous['close'] * (1 + min_rise) or
                following['close'] > high * (1 - min_pullback)):
            continue
        # Already-unbroken highs are supplied by the existing rule. Equal
        # later highs retain their newer source rather than readding this one.
        if not any(b['high'] > high for b in bars[i+1:]):
            continue
        result.append(dict(price=high, kind='resistance', time=candle['time'],
                           description='Previous daily peak'))
    # Equal historical prices enter the spacing groups with the newest first.
    return list(reversed(result))


def role_reversal_levels(bars, current_price, lookback=60, min_reaction=.10,
                         tick_size=.01, variable_tick_size=None):
    """Legacy review helper; Draw uses the shared reaction-area detector.

    Prominence is our heuristic: a strong reaction at a large-range candle,
    a local reversal, or a repeated test. Wick-only breaks never confirm a flip.
    """
    result = []
    for i in range(max(1, len(bars)-lookback), len(bars)-1):
        previous, candle, following = bars[i-1:i+2]
        later = bars[i+1:]
        large_range = candle['high'] - candle['low'] >= 2 * min_reaction * previous['close']
        for edge, kind in (('low', 'former_support'), ('high', 'former_resistance')):
            price = candle[edge]
            if price <= 0:
                continue
            is_low = edge == 'low'
            def reacted(close):
                return close >= price * (1 + min_reaction) if is_low else close <= price * (1 - min_reaction)
            strong_candle = large_range and reacted(candle['close'])
            if is_low:
                local_reversal = (price < min(previous[edge], following[edge]) and
                                  price <= previous['close'] * (1 - min_reaction))
            else:
                local_reversal = (price > max(previous[edge], following[edge]) and
                                  price >= previous['close'] * (1 + min_reaction))
            local_reversal = local_reversal and reacted(following['close'])
            repeated = any(levels_near(price, b[edge], tick_size, variable_tick_size)
                           for b in bars[max(0, i-20):i-1]) and (
                               reacted(candle['close']) or reacted(following['close']))
            if not (strong_candle or local_reversal or repeated):
                continue
            # A source must finish on its original side. Final completed and
            # live prices must both remain on the flipped side; a reclaim retires it.
            if is_low:
                active = (candle['close'] > price and bars[-1]['close'] < price and
                          current_price < price and any(b['close'] < price for b in later))
            else:
                active = (candle['close'] < price and bars[-1]['close'] > price and
                          current_price > price and any(b['close'] > price for b in later))
            if active:
                result.append(dict(price=price, kind=kind, time=candle['time'],
                                   description='Prior support' if is_low else 'Prior resistance'))
    return list(reversed(result))


def analyze(bars, max_levels=5, body_multiple=2.0, current_price=None, tick_size=0.01, variable_tick_size=None, extra_levels=(), enabled_types=None, current_day=None):
    """Bounded daily references, preserving reaction areas across breaks/reclaims."""
    enabled = selected_types(enabled_types)
    if len(bars) < 2:
        raise ValueError('At least two completed daily bars are required')
    for i, b in enumerate(bars):
        if any(not math.isfinite(b[k]) for k in ('time', 'open', 'high', 'low', 'close')):
            raise ValueError('Nonfinite bar')
        if b['low'] <= 0 or b['low'] > min(b['open'], b['close']) or b['high'] < max(b['open'], b['close']):
            raise ValueError('Invalid OHLC bar')
        if i and b['time'] <= bars[i-1]['time']:
            raise ValueError('Bars must be strictly chronological')
    if current_day and (any(not math.isfinite(current_day[k]) for k in ('time','open','high','low','close')) or
                        current_day['low'] <= 0 or current_day['low'] > min(current_day['open'],current_day['close']) or
                        current_day['high'] < max(current_day['open'],current_day['close'])):
        raise ValueError('Invalid current daily OHLC bar')
    if not math.isfinite(tick_size) or tick_size <= 0:
        raise ValueError('Tick size must be finite and positive')
    if not math.isfinite(body_multiple) or body_multiple <= 0:
        raise ValueError('Body multiple must be finite and positive')
    price = bars[-1]['close'] if current_price is None else current_price
    if not math.isfinite(price) or price <= 0:
        raise ValueError('Current price must be finite and positive')
    near = lambda a,b:levels_near(a,b,tick_size,variable_tick_size)
    tick = lambda p:price_tick(p,tick_size,variable_tick_size)
    areas = reaction_levels(bars, price, near, tick)
    daily = [x for x in areas if x['kind'] in enabled]
    # Unbroken edges remain a fallback, including two actual overhead prices.
    # An area owns its zone's meaning: do not relabel a crossed source as an
    # ordinary high just because another candle happens to share its price.
    newer_high, newer_low = -math.inf, math.inf
    for candle in reversed(bars):
        for edge, kind, exposed in (('high','resistance',candle['high'] > newer_high),
                                    ('low','support',candle['low'] < newer_low)):
            p = candle[edge]
            proper_side = p >= price if kind == 'resistance' else p <= price
            if exposed and proper_side and kind in enabled and not any(near(p,x['price']) and x['origin']==kind for x in areas):
                daily.append(dict(price=p, time=candle['time'], kind=kind,
                                  description='Unbroken daily '+edge))
        newer_high, newer_low = max(newer_high,candle['high']), min(newer_low,candle['low'])
    # Bound each Prior family even when it is the only enabled checkbox.
    bounded = [x for x in daily if x['kind'] not in ('former_support','former_resistance')]
    for kind in ('former_support','former_resistance'):
        bounded += sorted((x for x in daily if x['kind']==kind),key=lambda x:selection_rank(x,price))[:2]
    candidates = spaced_levels(bounded,tick_size,variable_tick_size)
    overhead = sorted((x for x in candidates if x['price']>price),key=lambda x:x['price'])
    below = sorted((x for x in candidates if x['price']<=price),key=lambda x:selection_rank(x,price))
    selected = overhead[:2] + below[:2]
    for x in sorted(candidates,key=lambda x:selection_rank(x,price)):
        if len(selected) >= max_levels:
            break
        if x not in selected:
            selected.append(x)
    # Daily candle boundaries define corridors. Quote distance ranks what is
    # useful now. An explicit corridor-only request can inspect the nearest
    # historical pair; ordinary Draw suppresses remote corridors.
    reach = corridor_reach(bars)
    def displayed_pair(pair):
        corridor = pair[0]['corridor']
        if corridor.get('display_mode') == 'fill_target_only':
            return pair[1:] if corridor['direction']=='up' else pair[:1]
        return pair
    def rank(pair):
        shown = displayed_pair(pair)
        low, high = shown[0]['price'], shown[-1]['price']
        corridor = pair[0]['corridor']
        if 'historical_evidence' in corridor:
            location = 0 if low <= price <= high else 1 if low > price else 2
            return (location, *historical_gap_rank(corridor, price))
        if low <= price <= high:
            return (0,(high-low)/price,0,0,-corridor['source_time'])
        if low > price:
            return (1,(low-price)/price,0,0,-corridor['source_time'])
        return (2,(price-high)/price,0,0,-corridor['source_time'])
    for kind, pairs in (('gap', gap_corridors(bars,current_day)),
                        ('window', candle_windows(bars,body_multiple))):
        if kind not in enabled:
            continue
        relevant = []
        for pair in pairs:
            lo, hi = pair[0]['price'], pair[1]['price']
            if kind == 'window':
                width_filter = window_width_filter(pair[0]['corridor'], tick)
                if not width_filter['eligible']:
                    continue
                for endpoint in pair:
                    endpoint['corridor']['width_filter'] = width_filter
            else:
                width_filter = gap_width_filter(pair[0]['corridor'], tick)
                if not width_filter['eligible']:
                    continue
                for endpoint in pair:
                    endpoint['corridor']['width_filter'] = width_filter
                    endpoint['corridor']['display_mode'] = width_filter['display_mode']
                corridor = pair[0]['corridor']
                if corridor['state'] in ('filled_recent','traversed_today'):
                    corridor['historical_evidence'] = historical_gap_evidence(corridor, bars, tick)
            if kind == 'window' and price >= hi:
                continue
            if kind == 'window' and current_day:
                if current_day['high'] >= hi:
                    continue
                if current_day['high'] > lo:
                    for endpoint in pair:
                        endpoint['corridor']['state'] = 'partial_today'
            shown = displayed_pair(pair)
            display_low, display_high = shown[0]['price'], shown[-1]['price']
            distance = max(display_low-price, price-display_high, 0)/price
            explicit = enabled & DAILY_TYPES == {kind}
            # A single fill target must be relevant to the quote even when
            # Gaps alone is selected. Do not rank it as an open corridor.
            if ((explicit and len(shown)>1) or distance <= reach) and (len(shown)==1 or not near(lo,hi)):
                relevant.append(pair)
        chosen = min(relevant,key=rank,default=None)
        if chosen:
            corridor = chosen[0]['corridor']
            crossed_quote = (price >= chosen[1]['price'] if corridor.get('direction')=='up' else price <= chosen[0]['price'])
            if kind == 'gap' and crossed_quote and corridor['state'] not in ('filled_recent','traversed_today'):
                corridor['state'] = 'crossed_quote'
                for endpoint in chosen:
                    endpoint['display_text'] = endpoint['display_text'].replace('Gap fill target','Gap fill')+' ref'
            selected.extend(displayed_pair(chosen))
    selected = spaced_levels(selected+[x for x in extra_levels if x['kind'] in enabled],tick_size,variable_tick_size)
    # Exact PM boundaries can win a nearby merge and land below the quote.
    # Backfill from the remaining real daily candidates rather than inventing.
    for candidate in overhead:
        if sum(x['price']>price for x in selected) >= 2:
            break
        selected = spaced_levels(selected+[candidate],tick_size,variable_tick_size)
    return selected


def premarket_bounds(now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('America/New_York'))
    return now, now.replace(hour=4, minute=0, second=0, microsecond=0), now.replace(hour=9, minute=30, second=0, microsecond=0)


def premarket_levels(bars, now=None):
    """Today's US equity 04:00-09:30 wick extremes, including the forming PM bar."""
    now, start, end = premarket_bounds(now)
    selected = [b for b in bars if start.timestamp() <= b['time'] < end.timestamp()
                and b['time'] <= now.timestamp()]
    if not selected:
        return []
    for b in selected:
        if any(not math.isfinite(b[k]) or b[k] <= 0 for k in ('high', 'low')) or b['low'] > b['high']:
            raise ValueError('Invalid premarket OHLC bar')
    high = max(selected, key=lambda b:b['high'])
    low = min(selected, key=lambda b:b['low'])
    return [dict(price=high['high'], time=high['time'], kind='premarket_high', description='PM high'),
            dict(price=low['low'], time=low['time'], kind='premarket_low', description='PM low')]


def read_premarket(client, session, now=None):
    now, start, _ = premarket_bounds(now)
    if not session['premarket_supported']:
        return {'status':'unsupported', 'levels':[]}
    if now < start:
        return {'status':'not_started', 'levels':[]}
    # Five-minute bars align exactly with 04:00 and 09:30 and keep the full
    # session within 500 bars even after the regular session has ended.
    client.call('chart_set_timeframe', timeframe='5')
    if session['session'] not in ('extended', '24h'):
        client.call('chart_set_session', session='extended')
    client.call('data_ensure_history', start=start.timestamp())
    levels = premarket_levels(client.call('data_get_ohlcv', count=500, summary=False)['bars'], now)
    return {'status':'ok' if levels else 'no_trades', 'date':now.date().isoformat(), 'levels':levels}


def read_session_levels(client, session, now, enabled):
    """Read provider session data separately so early-close postmarket is excluded."""
    pm={'status':'disabled','levels':[]}; day={'status':'disabled','levels':[]}
    wants_pm, wants_day = bool(enabled & PREMARKET_TYPES), bool(enabled & TODAY_TYPES)
    if not wants_pm and not wants_day:
        return pm,day
    if not session['premarket_supported']:
        return ({'status':'unsupported','levels':[]} if wants_pm else pm,
                {'status':'unsupported','levels':[]} if wants_day else day)
    market, pm_start, regular_start = premarket_bounds(now)
    if wants_pm:
        pm={'status':'not_started' if market<pm_start else 'no_trades','date':market.date().isoformat(),'levels':[]}
    if wants_day:
        day={'status':'not_started' if market<regular_start else 'no_trades','date':market.date().isoformat(),'levels':[]}
    read_pm=wants_pm and market>=pm_start
    read_day=wants_day and market>=regular_start
    if not read_pm and not read_day:
        return pm,day
    client.call('chart_set_timeframe',timeframe='5')
    target_session='extended' if read_pm else 'regular'
    if session['session']!=target_session:
        client.call('chart_set_session',session=target_session)
    client.call('data_ensure_history',start=(pm_start if read_pm else regular_start).timestamp(),
                session_name='premarket' if read_pm else 'regular-session')
    bars=client.call('data_get_ohlcv',count=500,summary=False)['bars']
    if read_pm:
        pm['levels']=[x for x in premarket_levels(bars,market) if x['kind'] in enabled]
        if pm['levels']:pm['status']='ok'
    if read_day:
        if read_pm:
            client.call('chart_set_session',session='regular')
            client.call('data_ensure_history',start=regular_start.timestamp(),session_name='regular-session')
            bars=client.call('data_get_ohlcv',count=500,summary=False)['bars']
        day['levels']=[x for x in regular_day_levels(bars,market) if x['kind'] in enabled]
        if day['levels']:day['status']='ok'
    return pm,day


def read_intraday_zones(client, session, now, enabled, reference):
    kinds = enabled & {'failed_rally','support_zone'}
    def unavailable(status):
        return {k:dict(status=status if k in kinds else 'disabled',levels=[]) for k in ('failed_rally','support_zone')}
    if not kinds:
        return unavailable('disabled')
    market, start, _ = premarket_bounds(now)
    if not session['premarket_supported']:
        return unavailable('unsupported')
    if market < start:
        return unavailable('not_started')
    client.call('chart_set_timeframe',timeframe='1')
    client.call('chart_set_session',session='extended')
    latest = client.call('data_latest_intraday_time',end=market.timestamp())['time']
    historical = False
    if latest is not None:
        latest_day = datetime.fromtimestamp(latest,ZoneInfo('America/New_York')).date()
        historical = latest_day < market.date()
        if historical:
            # Close out the last actual provider session, including on weekends
            # and holidays. Do not mix its candles with the current session.
            market = datetime.combine(latest_day,datetime.min.time(),market.tzinfo).replace(hour=20)
            start = market.replace(hour=4)
    client.call('data_ensure_history',start=start.timestamp(),session_name='one-minute intraday')
    end = min(market.timestamp()//60*60, market.replace(hour=20,minute=0,second=0,microsecond=0).timestamp())
    bars = [b for b in client.call('data_get_intraday',start=start.timestamp(),end=end)['bars']
            if start.timestamp() <= b['time'] < end and b.get('complete',True)]
    result = unavailable('disabled')
    for kind, detector in (('failed_rally',failed_rally_zones),('support_zone',support_zones)):
        if kind not in kinds:
            continue
        levels = detector(bars,reference['price'],market,
            lambda p:price_tick(p,reference.get('tick_size',.01),reference.get('variable_tick_size')))
        for level in levels:
            level['session_date'] = market.date().isoformat()
        result[kind] = dict(status='ok' if levels else 'no_pattern' if bars else 'no_trades',
                    levels=levels,date=market.date().isoformat(),historical=historical,
                    completed_bars=len(bars),from_time=bars[0]['time'] if bars else None,
                    through_time=bars[-1]['time'] if bars else None)
    return result


def read_five_minute_trends(client, session, now, enabled, reference):
    kinds=enabled & {'ascending_support','descending_resistance'}
    def unavailable(status):
        return {k:dict(status=status if k in kinds else 'disabled',levels=[]) for k in ('ascending_support','descending_resistance')}
    if not kinds:return unavailable('disabled')
    if not session['premarket_supported']:return unavailable('unsupported')
    market,start,_=premarket_bounds(now)
    if market<start:return unavailable('not_started')
    client.call('chart_set_timeframe',timeframe='5')
    client.call('chart_set_session',session='extended')
    latest=client.call('data_latest_intraday_time',end=market.timestamp(),timeframe='5')['time']
    historical=False
    if latest is not None:
        latest_day=datetime.fromtimestamp(latest,ZoneInfo('America/New_York')).date()
        historical=latest_day<market.date()
        if historical:
            market=datetime.combine(latest_day,datetime.min.time(),market.tzinfo).replace(hour=20)
            start=market.replace(hour=4)
    client.call('data_ensure_history',start=start.timestamp(),session_name='five-minute trendlines')
    end=min(market.timestamp()//300*300,market.replace(hour=20,minute=0,second=0,microsecond=0).timestamp())
    bars=[b for b in client.call('data_get_intraday',start=start.timestamp(),end=end,timeframe='5')['bars']
          if start.timestamp()<=b['time'] and b['time']+300<=end and b.get('complete',True)]
    result=unavailable('disabled')
    for kind,detector in (('ascending_support',ascending_support),('descending_resistance',descending_resistance)):
        if kind not in kinds:continue
        levels=detector(bars,reference['price'],market,
            lambda p:price_tick(p,reference.get('tick_size',.01),reference.get('variable_tick_size')))
        for level in levels:level['session_date']=market.date().isoformat()
        result[kind]=dict(status='ok' if levels else 'no_pattern' if bars else 'no_trades',levels=levels,
                    date=market.date().isoformat(),historical=historical,completed_bars=len(bars),
                    from_time=bars[0]['time'] if bars else None,through_time=bars[-1]['time'] if bars else None)
    return result


def read_ascending_support(client, session, now, enabled, reference):
    return read_five_minute_trends(client,session,now,enabled & {'ascending_support'},reference)['ascending_support']


def read_failed_rallies(client, session, now, enabled, reference):
    return read_intraday_zones(client,session,now,enabled & {'failed_rally'},reference)['failed_rally']


def run(client, count=300, max_levels=5, dry_run=False, body_multiple=2.0, now=None, enabled_types=None, theme='dark'):
    if theme not in ('dark','light'):raise ValueError('Unknown drawing theme')
    enabled = selected_types(enabled_types)
    binder = getattr(client, 'bind_selected', None)
    if binder:
        client = binder()
    try:
        result = _run_bound(client, count, max_levels, dry_run, body_multiple, now, enabled, theme)
        # _run_bound's finally has verified restoration before publication.
        if not dry_run and getattr(client, 'details_path', None):
            from level_capture import preserve_completed
            preserve_completed(client, result, 'draw')
            save_details(client.details_path, result['scope'], result)
        return result
    finally:
        release_bound(client)


def _run_bound(client, count, max_levels, dry_run, body_multiple, now, enabled, theme):
    original = client.call('chart_get_state')
    symbol, resolution = original['symbol'], original['resolution']
    ownership_path = getattr(client, 'ownership_path', None)
    ownership = json.loads(ownership_path.read_text()) if ownership_path and ownership_path.exists() else {}
    scope = symbol
    owned_ids = ownership.get(scope, [])
    if ownership_path:
        location = client.call('ui_evaluate', expression='window.location.href')['result']
        legacy_scope = str(location) + '|' + symbol
        pane = getattr(client, 'info', None)
        scope = legacy_scope + ('|pane:' + pane['pane_id'] if pane else '')
        # IDs are adopted only if they actually exist in this pane below.
        owned_ids = ownership.get(legacy_scope, []) + ownership.get(scope, [])
    if original.get('chartType') not in (0, 1, 9):
        raise RuntimeError('Use standard OHLC bars/candles, not synthetic chart types')
    session = client.call('session_snapshot')
    context = {}
    now = now or datetime.now(timezone.utc)
    availability = {}
    try:
        reference = read_reference(client)
        premarket, today_session = read_session_levels(client,session,now,enabled)
        intraday = read_intraday_zones(client,session,now,enabled,reference)
        rallies,supports = intraday['failed_rally'],intraday['support_zone']
        trend_groups=read_five_minute_trends(client,session,now,enabled,reference)
        trends,descending=trend_groups['ascending_support'],trend_groups['descending_resistance']
        intraday.update(trend_groups)
        client.call('chart_set_session', session=session['session'])
        bars = []
        current_day = None
        if enabled & DAILY_TYPES:
            # Daily references use regular-session candles.
            if session['premarket_supported']:
                client.call('chart_set_session',session='regular')
            client.call('chart_set_timeframe', timeframe='1D')
            state = client.call('chart_get_state')
            if state['symbol'] != symbol or state['resolution'] not in ('D', '1D'):
                raise RuntimeError('Chart changed or daily timeframe not ready')
            if enabled & EVENT_TYPES and session['premarket_supported']:
                client.call('data_ensure_history',start=(now-timedelta(days=240)).timestamp(),session_name='event daily',max_requests=8)
            raw_bars = client.call('data_get_ohlcv', count=max(count,LOOKBACK+21) if enabled & EVENT_TYPES else count, summary=False)['bars']
            bars = confirmed(raw_bars, now)
            market_today = premarket_bounds(now)[0].date()
            current_day = next((b for b in reversed(raw_bars) if datetime.fromtimestamp(b['time'], timezone.utc).astimezone(ZoneInfo('America/New_York')).date() == market_today), None)
            reference = read_reference(client, timeout=1.0, fallback=reference)
        eligible_references = enabled & REFERENCE_TYPES
        if not session['premarket_supported']:
            for kind in eligible_references:
                availability[kind]='Regular-session references currently support US stocks and depositary receipts in New York time.'
            eligible_references = frozenset()
        extras, reference_availability = explicit_references(bars,reference['price'],eligible_references,now,
                                                             corridor_reach(bars) if bars else .25)
        availability.update(reference_availability)
        extras += premarket['levels'] + today_session['levels']
        event_info = {'status':'disabled','levels':[]}
        if enabled & EVENT_TYPES:
            if not session['premarket_supported']:
                for kind in enabled & EVENT_TYPES:availability[kind]='Historical events currently support US stocks and depositary receipts with New York sessions.'
                event_info['status']='unsupported'
            else:
                historical=[v for v in bars if datetime.fromtimestamp(v['time'],ZoneInfo('America/New_York')).date()<premarket_bounds(now)[0].date()][-LOOKBACK:]
                extended=[];minutes=[]
                if historical and 'prior_premarket_high' in enabled:
                    first=datetime.fromtimestamp(historical[0]['time'],ZoneInfo('America/New_York')).replace(hour=4,minute=0,second=0,microsecond=0)
                    client.call('chart_set_timeframe',timeframe='30');client.call('chart_set_session',session='extended')
                    client.call('data_ensure_history',start=first.timestamp(),session_name='historical premarket',max_requests=10)
                    extended=client.call('data_get_session_history',start=first.timestamp(),end=premarket_bounds(now)[1].timestamp())['bars']
                market,start,_=premarket_bounds(now)
                if market>=start:
                    client.call('chart_set_timeframe',timeframe='1');client.call('chart_set_session',session='extended')
                    client.call('data_ensure_history',start=start.timestamp(),session_name='event intraday')
                    end=min(market.timestamp(),market.replace(hour=20,minute=0,second=0,microsecond=0).timestamp())
                    minutes=client.call('data_get_intraday',start=start.timestamp(),end=end)['bars']
                selected_events=event_levels(bars,extended,minutes,reference['price'],now,enabled,
                    lambda a,b:levels_near(a,b,reference.get('tick_size',.01),reference.get('variable_tick_size')),
                    lambda p:price_tick(p,reference.get('tick_size',.01),reference.get('variable_tick_size')),current_day)
                extras += selected_events
                event_info=dict(status='ok' if selected_events else 'no_pattern',levels=selected_events,completed_sessions=len(historical))
                for kind in enabled & EVENT_TYPES:
                    if not any(v['kind']==kind for v in selected_events):availability[kind]='No qualifying historical event reference was selected near today’s range.'
        for info,kinds in ((premarket,PREMARKET_TYPES),(today_session,TODAY_TYPES)):
            if info['status'] not in ('ok','disabled'):
                reason={'not_started':'This session has not started today.','no_trades':'No trades were found for this session today.',
                        'unsupported':'This session reference currently supports US stocks and depositary receipts with New York extended-hours data.'}[info['status']]
                for kind in enabled & kinds:availability[kind]=reason
        if enabled & STRUCTURE_TYPES:
            levels = analyze(bars,max_levels,body_multiple,reference['price'],reference.get('tick_size',.01),
                             reference.get('variable_tick_size'),extras,enabled,current_day=current_day)
        else:
            levels = spaced_levels(extras,reference.get('tick_size',.01),reference.get('variable_tick_size'))
        # Intraday bands retain their own bounds and identity; line spacing must
        # not collapse them into daily references or other failure ceilings.
        levels = sorted(levels + rallies['levels'] + supports['levels'] + trends['levels'] + descending['levels'],key=lambda level:level['price'])
        for kind,info in intraday.items():
            if info['status'] in ('ok','disabled'):
                continue
            pattern_session = (f"the {datetime.fromisoformat(info['date']).strftime('%m/%d')} session"
                               if info.get('historical') else 'today’s session')
            if kind in ('ascending_support','descending_resistance'):
                name='Ascending support' if kind=='ascending_support' else 'Descending resistance'
                pattern='pullbacks with higher lows' if kind=='ascending_support' else 'rallies with lower highs'
                availability[kind]={'unsupported':f'{name} currently supports US stocks and depositary receipts with New York extended-hours data.',
                    'not_started':'Today’s extended session has not started.',
                    'no_trades':f'No completed five-minute candles were found for {pattern_session}.',
                    'no_pattern':f'No nearby {name.lower()} line had two independent, active {pattern} and a valid intervening fit in {pattern_session}.'}[info['status']]
                continue
            name = 'Failed-rally zones' if kind == 'failed_rally' else 'Support holds'
            pattern = 'ceiling had two separate qualifying rally failures' if kind == 'failed_rally' else 'floor had two independent confirmed support holds'
            availability[kind] = {
                'unsupported':f'{name} currently support US stocks and depositary receipts with New York extended-hours data.',
                'not_started':'Today’s extended session has not started.',
                'no_trades':f'No completed one-minute extended-hours candles were found for {pattern_session}.',
                'no_pattern':f'No nearby {pattern} meeting price and minimum-activity requirements in the completed one-minute candles from {pattern_session}. Missing volume cannot qualify a test.'}[info['status']]
        if 'window' in enabled and not any(s['kind']=='window' for level in levels for s in label_sources(level)):
            availability['window']='No exposed window met the remaining-width and proximity requirements. Windows need at least 25% of their original range, 5% of their top price, and two price ticks remaining.'
        if 'gap' in enabled and not any(s['kind']=='gap' for level in levels for s in label_sources(level)):
            availability['gap']='No recent gap met the original-width and proximity requirements. Original gaps need at least 5% of the upper boundary price and two price ticks of width. Significant filled gaps remain historical references; narrow open remnants retain only a nearby fill target.'
        if bars:
            context_refs = reaction_levels(bars, reference['price'],
                lambda a,b:levels_near(a,b,reference.get('tick_size',.01),reference.get('variable_tick_size')),
                lambda p:price_tick(p,reference.get('tick_size',.01),reference.get('variable_tick_size')))
            context = daily_context(bars,levels,[x for x in context_refs if x['kind'] in enabled]+levels)
        from level_explanations import explain_level
        assign_rally_colors(levels)
        for level in levels:
            level['label_sources']=label_sources(level)
            level['label']=drawing_label(level,now)
            level.update(drawing_style(level,reference['price'],label_sources(level),theme))
            level['explanation']=explain_level(level,reference['price'],label_sources(level),context)
        if not dry_run and (rallies['levels'] or supports['levels'] or trends['levels'] or descending['levels']):
            # Intraday peak marks must be placed on minute data. TradingView
            # otherwise rounds both times to a daily bar before restoration.
            client.call('chart_set_session', session='extended')
            client.call('chart_set_timeframe', timeframe='1')
        drawing_resolution = client.call('chart_get_state')['resolution']
        if not dry_run:
            active_drawing_resolution=drawing_resolution
            old = []
            for shape in client.call('draw_list')['shapes']:
                properties = client.call('draw_get_properties', entity_id=shape['id'])
                if (shape['id'] in owned_ids or
                        properties.get('properties', {}).get('text', '').startswith(PREFIX)):
                    old.append(shape['id'])
            created = []
            try:
                for label_index, level in enumerate(levels):
                    state = client.call('chart_get_state')
                    if state['symbol'] != symbol or state['resolution'] != active_drawing_resolution:
                        raise RuntimeError('Chart changed during drawing')
                    target_resolution='5' if level['kind'] in ('ascending_support','descending_resistance') else drawing_resolution
                    if target_resolution!=active_drawing_resolution:
                        client.call('chart_set_timeframe',timeframe=target_resolution)
                        active_drawing_resolution=target_resolution
                    color = level['color']
                    label = drawing_label(level, now)
                    if level['kind'] in ('failed_rally','support_zone','ascending_support','descending_resistance'):
                        specs = trend_marks(level) if level['kind'] in ('ascending_support','descending_resistance') else support_marks(level) if level['kind'] == 'support_zone' else rally_marks(level)
                        level['marks'] = []
                        level['entity_ids'] = []
                    else:
                        specs = [dict(shape='horizontal_line',
                            point={'price':level['price'], 'time':level['time']},text=label,
                            overrides=json.dumps({'linecolor':color, 'textcolor':color, 'linewidth':1,
                                                  'linestyle':level['linestyle'], 'showPrice':True,
                                                  'horzLabelsAlign':'left' if label_index % 2 == 0 else 'right'}))]
                    for spec in specs:
                        state = client.call('chart_get_state')
                        if state['symbol'] != symbol or state['resolution'] != active_drawing_resolution:
                            raise RuntimeError('Chart changed during drawing')
                        result = client.call('draw_shape', **spec)
                        if not result.get('entity_id'):
                            raise RuntimeError('Drawing creation returned no ID')
                        created.append(result['entity_id'])
                        level['entity_id'] = result['entity_id']
                        if level['kind'] in ('failed_rally','support_zone','ascending_support','descending_resistance'):
                            level['entity_ids'].append(result['entity_id'])
                            level['marks'].append(dict(spec, entity_id=result['entity_id']))
                        if ownership_path:
                            ownership[scope] = list(dict.fromkeys(old + created))
                            temporary = ownership_path.with_suffix('.tmp')
                            temporary.write_text(json.dumps(ownership, indent=2))
                            temporary.replace(ownership_path)
                for entity_id in old:
                    client.call('draw_remove_one', entity_id=entity_id)
                if ownership_path:
                    ownership[scope] = created
                    if scope != legacy_scope and legacy_scope in ownership:
                        ownership[legacy_scope] = [eid for eid in ownership.get(legacy_scope, []) if eid not in old]
                    temporary = ownership_path.with_suffix('.tmp')
                    temporary.write_text(json.dumps(ownership, indent=2))
                    temporary.replace(ownership_path)
            except Exception:
                if hasattr(client, 'allow_inactive'):
                    client.allow_inactive = True
                for entity_id in created:
                    client.call('draw_remove_one', entity_id=entity_id)
                raise
        result={'symbol':symbol,'scope':scope,'pane':getattr(client,'info',None),'levels':levels,
                'dry_run':dry_run,'drawing_theme':theme,'reference':reference,'premarket':premarket,'today_session':today_session,
                'context':context,'failed_rallies':rallies,'support_zones':supports,'ascending_support':trends,'descending_resistance':descending,'historical_events':event_info,'availability':availability,'drawn_at':now.timestamp(),
                'enabled_types':[kind for kind in LEVEL_TYPES if kind in enabled],
                'overhead_count':sum(x['price']>reference['price'] for x in levels)}
        return result

    finally:
        # Cleanup addresses the captured pane even if the user selected another.
        if hasattr(client, 'allow_inactive'):
            client.allow_inactive = True
        try:
            state = client.call('chart_get_state')
            if state['symbol'] != symbol:
                raise RuntimeError('Original pane symbol changed; timeframe was not restored')
            try:
                client.call('chart_set_session', session=session['session'])
            finally:
                client.call('chart_set_timeframe', timeframe=resolution)
            if client.call('chart_get_state')['resolution'] != resolution:
                raise RuntimeError('Original timeframe restoration failed')
            if client.call('session_snapshot')['session'] != session['session']:
                raise RuntimeError('Original session restoration failed')
        except Exception as error:
            raise RuntimeError('Original chart restoration could not be verified. '
                               'Check the original pane before trying again: ' + str(error)) from error


def save_details(path, scope, result):
    """Persist chart-specific explanations only after successful drawing replacement."""
    data=json.loads(path.read_text()) if path.exists() else {}
    if result is None:data.pop(scope,None)
    else:data[scope]=result
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,indent=2))
    temporary.replace(path)


def clear_levels(client):
    """Remove this tool's drawings from the selected pane without changing timeframe."""
    binder = getattr(client, 'bind_selected', None)
    if binder:
        client = binder()
    try:
        state = client.call('chart_get_state')
        path = getattr(client, 'ownership_path', None)
        ownership = json.loads(path.read_text()) if path and path.exists() else {}
        legacy = state['symbol']
        scope = legacy
        if path:
            url = client.call('ui_evaluate', expression='window.location.href')['result']
            legacy = str(url) + '|' + state['symbol']
            pane = getattr(client, 'info', None)
            scope = legacy + ('|pane:' + pane['pane_id'] if pane else '')
        owned = set(ownership.get(scope, []) + ownership.get(legacy, []))
        removed = 0
        for shape in client.call('draw_list')['shapes']:
            eid = shape['id']
            properties = client.call('draw_get_properties', entity_id=eid)
            if eid not in owned and not properties.get('properties', {}).get('text', '').startswith(PREFIX):
                continue
            result = client.call('draw_remove_one', entity_id=eid)
            if result.get('removed') is False:
                raise RuntimeError('Could not remove level ' + eid)
            removed += 1
            for key in (scope, legacy):
                if key in ownership:
                    ownership[key] = [i for i in ownership[key] if i != eid]
            if path:
                temporary = path.with_suffix('.tmp')
                temporary.write_text(json.dumps(ownership, indent=2))
                temporary.replace(path)
        if getattr(client,'details_path',None):
            save_details(client.details_path,scope,None)
        result = {'symbol':state['symbol'],'scope':scope,'pane':getattr(client,'info',None),'removed':removed,'levels':[]}
        if getattr(client, 'details_path', None):
            from level_capture import preserve_completed
            preserve_completed(client, result, 'clear')
        return result
    finally:
        release_bound(client)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--catalog',action='store_true',help='Print category help without connecting to TradingView')
    action.add_argument('--dry-run', action='store_true')
    action.add_argument('--clear', action='store_true', help='Clear this tool’s levels from the selected pane')
    parser.add_argument('--bars', type=int, default=300, choices=range(2,501), metavar='2..500')
    parser.add_argument('--max-levels', type=int, default=5, choices=range(5,31))
    parser.add_argument('--body-multiple', type=float, default=2.0, help='Long body versus median of previous 20 nonzero bodies (default 2)')
    parser.add_argument('--level-types', nargs='+', choices=LEVEL_TYPES,
                        help='Draw only these types; default: all categories. Clear ignores this selection.')
    parser.add_argument('--theme',choices=('dark','light'),help='Drawing colors; defaults to the panel’s saved theme')
    args = parser.parse_args()
    if args.catalog:
        print(json.dumps({'groups':GROUPS,'legend':STYLE_LEGEND,'lightColors':LIGHT_COLORS},ensure_ascii=False))
        return
    if not math.isfinite(args.body_multiple) or args.body_multiple <= 1:
        parser.error('--body-multiple must be finite and greater than 1')
    from theme_settings import read_theme
    theme=args.theme or read_theme()
    client = MCP(Path(__file__).resolve().parents[1])
    try:
        result = clear_levels(client) if args.clear else run(client, args.bars, args.max_levels, args.dry_run,
                                                           args.body_multiple, enabled_types=args.level_types,theme=theme)
        print(json.dumps(result, indent=2))
    finally:
        client.close()

if __name__ == '__main__':
    main()
