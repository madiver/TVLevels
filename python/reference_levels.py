"""Explicit session and nearby reference levels; no discretionary pivot inference."""
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

MARKET_ZONE = ZoneInfo('America/New_York')
PREVIOUS_TYPES = frozenset(('previous_high','previous_low','previous_close','previous_open'))
TODAY_TYPES = frozenset(('day_high','day_low'))
REFERENCE_TYPES = PREVIOUS_TYPES


def date_at(timestamp):
    return datetime.fromtimestamp(timestamp,timezone.utc).astimezone(MARKET_ZONE).date()


def explicit_references(bars, price, enabled, now, reach=.25):
    """Previous regular-session references from completed daily candles."""
    if not math.isfinite(price) or price<=0:
        raise ValueError('Reference quote must be finite and positive')
    for i,b in enumerate(bars):
        if any(not math.isfinite(b[k]) for k in ('time','open','high','low','close')) or b['low']<=0 or b['low']>min(b['open'],b['close']) or b['high']<max(b['open'],b['close']):
            raise ValueError('Invalid reference daily OHLC bar')
        if i and b['time']<=bars[i-1]['time']:
            raise ValueError('Reference bars must be chronological')
    today = now.astimezone(MARKET_ZONE).date()
    result, availability = [], {}
    earlier = [b for b in bars if date_at(b['time']) < today]
    if enabled & PREVIOUS_TYPES:
        source = earlier[-1] if earlier else None
        for kind, field, name in (('previous_high','high','Prev high'),('previous_low','low','Prev low'),('previous_close','close','Prev close'),('previous_open','open','Prev open')):
            if kind not in enabled:
                continue
            if source is None:
                availability[kind] = 'No earlier regular daily session is loaded.'
            elif abs(source[field]-price)/price > reach:
                availability[kind] = 'The previous session value is outside the nearby display range.'
            else:
                result.append(dict(price=source[field],time=source['time'],kind=kind,description=name,session='regular'))
    return result,availability


def regular_day_levels(bars, now):
    today=now.astimezone(MARKET_ZONE)
    start=today.replace(hour=9,minute=30,second=0,microsecond=0).timestamp()
    end=today.replace(hour=16,minute=0,second=0,microsecond=0).timestamp()
    selected=[b for b in bars if start<=b['time']<end and b['time']<=today.timestamp()]
    if not selected:
        return []
    if any(not math.isfinite(b[k]) or b[k]<=0 for b in selected for k in ('high','low')) or any(b['low']>b['high'] for b in selected):
        raise ValueError('Invalid regular-session OHLC bar')
    high=max(selected,key=lambda b:b['high']);low=min(selected,key=lambda b:b['low'])
    return [dict(price=high['high'],time=high['time'],kind='day_high',description='Day high',session='regular'),
            dict(price=low['low'],time=low['time'],kind='day_low',description='Day low',session='regular')]
