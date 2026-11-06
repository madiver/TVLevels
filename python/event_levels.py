"""Rank historical event prices and describe completed-minute intraday context.

These are our initial display rules, not rules attributed to John or Ross.
"""
import math
from datetime import datetime
from statistics import median
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
EVENT_TYPES = frozenset(('event_close', 'event_high', 'prior_premarket_high'))
LOOKBACK = 120
BASELINE = 20
MAX_LEVELS = 4
MAX_OVERHEAD = 2


def day(timestamp):
    return datetime.fromtimestamp(timestamp, NY).date()


def validate(bars):
    previous = None
    for b in bars:
        if any(not math.isfinite(b[k]) for k in ('time','open','high','low','close','volume')):
            raise ValueError('Nonfinite event candle')
        if b['low'] <= 0 or b['low'] > min(b['open'],b['close']) or b['high'] < max(b['open'],b['close']) or b['volume'] < 0:
            raise ValueError('Invalid event candle')
        if previous is not None and b['time'] <= previous:
            raise ValueError('Event candles must be chronological')
        previous = b['time']


def minute_context(price, bars, quote, now, tick):
    """A wick cannot confirm a reclaim; a later clean retest needs its own bar."""
    market = now.astimezone(NY)
    start = market.replace(hour=4,minute=0,second=0,microsecond=0).timestamp()
    end = min(market.timestamp()//60*60,market.replace(hour=20,minute=0,second=0,microsecond=0).timestamp())
    selected = [b for b in bars if start <= b['time'] < end and b.get('complete',True)]
    buffer = tick(price)
    if not math.isfinite(buffer) or buffer<=0:
        raise ValueError('Invalid event tick')
    streak = 0; reclaimed = False; state = 'resistance' if quote <= price else 'above_unconfirmed'
    qualified_at = None; retested_at = None; lost_at = None; tested_at = None; previous = None
    for b in selected:
        if previous is not None and b['time']-previous != 60:
            streak = 0
        previous = b['time']
        if b['high']>=price+buffer-1e-12:
            tested_at=b['time']
        if b['close'] >= price+buffer-1e-12:
            if reclaimed and price-buffer <= b['low'] <= price+buffer:
                state='retested';retested_at=b['time']
            streak += 1
            if not reclaimed and streak >= 2:
                reclaimed=True;qualified_at=b['time'];state='reclaimed';retested_at=None
        else:
            streak=0
            if reclaimed and b['close'] <= price-buffer+1e-12:
                reclaimed=False;state='lost';lost_at=b['time'];retested_at=None
            elif not reclaimed and tested_at is not None and state!='lost':
                state='tested'
    # A forming candle or quote can disagree with the last confirmed state.
    return dict(state=state,qualified_at=qualified_at,retested_at=retested_at,lost_at=lost_at,tested_at=tested_at,
                quote_side='above' if quote>price else 'below' if quote<price else 'at',
                completed_bars=len(selected),tick_buffer=buffer)


def event_levels(daily, extended, minutes, quote, now, enabled, near, tick, today_range=None):
    """At most two nearby references beyond today's high and two day-range references."""
    if not math.isfinite(quote) or quote <= 0:
        raise ValueError('Invalid event quote')
    daily,extended,minutes=([dict(b,volume=b.get('volume',0)) for b in bars] for bars in (daily,extended,minutes))
    for bars in (daily,extended,minutes):validate(bars)
    today = now.astimezone(NY).date()
    history = [b for b in daily if day(b['time']) < today]
    recent = history[-LOOKBACK:]
    dates = {day(b['time']) for b in recent}
    candidates = []
    pm = {}
    for b in extended:
        t=datetime.fromtimestamp(b['time'],NY)
        # Loader guarantees thirty-minute candles, ending exactly at 09:30.
        if t.date() in dates and 4*60 <= t.hour*60+t.minute < 9*60+30:
            pm.setdefault(t.date(),[]).append(b)
    for i,b in enumerate(history):
        if day(b['time']) not in dates:continue
        prior=history[max(0,i-BASELINE):i]
        if len(prior)<5:continue
        volumes=[v['volume'] for v in prior if v['volume']>0]
        ranges=[(v['high']-v['low'])/v['close'] for v in prior if v['high']>v['low']]
        if not volumes or not ranges:continue
        usual_volume=median(volumes);usual_range=median(ranges)
        def add(kind,price,time,volume,range_ratio,rejection,extra):
            tests=[]
            tolerance=max(2*tick(price),price*.005)
            move=max(2*tick(price),price*usual_range/2)
            for j in range(i+1,len(history)-1):
                v,following=history[j:j+2]
                touched=v['low']-tolerance <= price <= v['high']+tolerance
                if touched and abs(following['close']-price)>=move and (not tests or j-tests[-1]>=3):tests.append(j)
            volume_ratio=volume/usual_volume
            score=(min(4,math.log2(1+volume_ratio))+min(4,math.log2(1+range_ratio))
                   +2*max(0,min(1,rejection))+.5*min(3,len(tests))+.5*(i+1)/len(history))
            candidates.append(dict(kind=kind,price=price,time=time,description=kind,
                event=dict(source_date=day(time).isoformat(),score=score,volume=volume,volume_ratio=volume_ratio,
                    range_ratio=range_ratio,rejection=rejection,additional_tests=len(tests),**extra)))
        if enabled & {'event_close', 'event_high'}:
            volume_ratio=b['volume']/usual_volume
            range_ratio=((b['high']-b['low'])/prior[-1]['close'])/usual_range
            # Independent volume spikes prevent drawing each follow-through
            # close after the same major event. All baselines precede the day.
            if volume_ratio>=2 and range_ratio>=1.5 and b['volume']>=max(v['volume'] for v in prior):
                rejection=(b['high']-b['close'])/max(b['high']-b['low'],tick(b['close']))
                for kind,edge in (('event_close','close'),('event_high','high')):
                    if kind in enabled:
                        add(kind,b[edge],b['time'],b['volume'],range_ratio,rejection,
                            dict(source_high=b['high'],source_low=b['low'],source_close=b['close'],
                                 previous_close=prior[-1]['close']))
        if 'prior_premarket_high' in enabled and day(b['time']) in pm:
            bars=pm[day(b['time'])];high=max(bars,key=lambda v:v['high']);low=min(v['low'] for v in bars)
            volume=sum(v['volume'] for v in bars);previous_close=prior[-1]['close']
            rise=high['high']-previous_close
            if volume>0 and rise>=max(2*tick(high['high']),previous_close*usual_range):
                rejection=max(0,(high['high']-bars[-1]['close'])/max(high['high']-low,tick(high['high'])))
                add('prior_premarket_high',high['high'],high['time'],volume,
                    ((high['high']-low)/previous_close)/usual_range,rejection,
                    dict(premarket_low=low,premarket_close=bars[-1]['close'],previous_close=previous_close))
    market=now.astimezone(NY)
    start=market.replace(hour=4,minute=0,second=0,microsecond=0).timestamp()
    available=[b for b in minutes if start <= b['time'] <= now.timestamp() and day(b['time'])==today]
    lows=[quote]+[b['low'] for b in available];highs=[quote]+[b['high'] for b in available]
    if today_range:
        lows.append(today_range['low']);highs.append(today_range['high'])
    low,high=min(lows),max(highs)
    # Today's range anchors the search so a pullback cannot hide the next
    # overhead reference. Do not extend this into unbounded distant targets.
    candidates=[c for c in candidates if low*.75 <= c['price'] <= high*1.25]
    ranked=sorted(candidates,key=lambda c:(-c['event']['score'],-c['time']))
    distinct=[]
    for candidate in ranked:
        group=next((g for g in distinct if near(candidate['price'],g[0]['price'])),None)
        if group is None:distinct.append([candidate])
        else:group.append(candidate)
    displayed_price=lambda group:max(v['price'] for v in group)
    above=sorted((g for g in distinct if displayed_price(g)>high),key=lambda g:(displayed_price(g)-high,-g[0]['event']['score']))[:MAX_OVERHEAD]
    inside=sorted((g for g in distinct if low<=displayed_price(g)<=high),key=lambda g:(-g[0]['event']['score'],-g[0]['time']))[:2]
    selected=inside+above
    for group in distinct:
        if len(inside)>=2 or len(selected)>=MAX_LEVELS:break
        if displayed_price(group)<low and group not in selected:
            selected.append(group);inside.append(group)
    result=[]
    for group in selected:
        for level in group:
            level['event']['intraday']=minute_context(level['price'],minutes,quote,now,tick)
            level['event']['selection']='above_today_high' if level['price']>high else 'today_range' if level['price']>=low else 'nearby_below'
            level['event']['today_range']=dict(low=low,high=high)
            result.append(level)
    return result
