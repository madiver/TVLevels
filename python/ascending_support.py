"""Shared fixed-anchor five-minute trendlines and ascending-support entry point; bounded observational heuristics.

Two confirmed pullbacks create a provisional ray. Independent later reactions
strengthen it without moving the anchors. These are automation choices, not
John's verified proprietary rules or an instruction to trade. Positive direction
tracks falling pullbacks and rising support; negative direction tracks rising
rallies and falling resistance. Both sides use actual prices and volume.
"""
import json
import math
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from reaction_volume import ReactionVolume, zone_volume, volume_priority

NY = ZoneInfo('America/New_York')
INTERVAL = 300
MIN_DECLINE = .01
MIN_REBOUND = .01
MIN_ANCHOR_RISE = .005
TOUCH_FRACTION = .0025
MIN_ANCHOR_BARS = 2
TIMEOUT_BARS = 6


def completed_five_minutes(bars, now):
    market=now.astimezone(NY)
    start=market.replace(hour=4,minute=0,second=0,microsecond=0).timestamp()
    end=min(market.timestamp()//INTERVAL*INTERVAL,market.replace(hour=20,minute=0,second=0,microsecond=0).timestamp())
    selected=[];previous=None
    for b in bars:
        if any(not math.isfinite(b[k]) for k in ('time','open','high','low','close')):
            raise ValueError('Nonfinite five-minute candle')
        if b['time']%INTERVAL or b['low']<=0 or b['low']>min(b['open'],b['close']) or b['high']<max(b['open'],b['close']):
            raise ValueError('Invalid five-minute candle')
        if previous is not None and b['time']<=previous:raise ValueError('Five-minute candles must be chronological')
        previous=b['time']
        if start<=b['time'] and b['time']+INTERVAL<=end and b.get('complete',True):selected.append(b)
    return selected,end


def _confirmed_reactions(bars,tick,direction):
    extreme_field,base_field=('low','high') if direction==1 else ('high','low')
    participation=ReactionVolume(bars,bar_seconds=INTERVAL)
    holds=[];base=None;selloff=None;previous=None;recent=[];segment=0
    for index,b in enumerate(bars):
        if previous is None or b['time']-previous['time']!=INTERVAL:
            segment+=1;base=b;selloff=None;previous=b;recent=[b]
            continue
        if selloff and b['time']-selloff['time']>=TIMEOUT_BARS*INTERVAL:
            later=[x for x in recent if x['time']>selloff['time']]
            base=max(later or recent,key=lambda x:direction*x[base_field]);selloff=None
        if selloff is None:
            minimum=max(MIN_DECLINE*base[base_field],2*tick(b[extreme_field]),2*tick(base[base_field]))
            if direction*(previous['close']-b['close'])>0 and direction*(base[base_field]-b['close'])>=minimum-1e-12:
                selloff=dict(price=b[extreme_field],time=b['time'],index=index,base=base[base_field],base_time=base['time'])
            elif direction*(b[base_field]-base[base_field])>0:base=b
        else:
            if direction*(b[extreme_field]-selloff['price'])< -1e-12:selloff.update(price=b[extreme_field],time=b['time'],index=index)
            impulse=direction*(selloff['base']-selloff['price'])
            if b['time']>selloff['time'] and direction*(b['close']-selloff['price'])>=max(MIN_REBOUND*selloff['price'],2*tick(b[extreme_field]),2*tick(selloff['price']))-1e-12:
                volume=participation.measure(selloff['time'],b['time'])
                if volume['eligible']:
                    holds.append(dict(selloff,confirmed_at=b['time']+INTERVAL,confirmed_bar_time=b['time'],
                                      confirmation_index=index,confirmation_close=b['close'],segment=segment,
                                      recovery=direction*(b['close']-selloff['price'])/impulse,volume=volume))
                base=b;selloff=None
        previous=b;recent=(recent+[b])[-TIMEOUT_BARS:]
    return holds


def confirmed_pullbacks(bars,tick):
    return _confirmed_reactions(bars,tick,1)


def confirmed_rallies(bars,tick):
    return _confirmed_reactions(bars,tick,-1)


def ascending_support(bars,quote,now=None,tick=lambda p:.01):
    return directional_trendline(bars,quote,now,tick,1)


def directional_trendline(bars,quote,now,tick,direction):
    if direction not in (1,-1):raise ValueError('Invalid trendline direction')
    kind='ascending_support' if direction==1 else 'descending_resistance'
    title_name='ascending support' if direction==1 else 'descending resistance'
    if not math.isfinite(quote) or quote<=0:raise ValueError(f'Invalid {title_name} quote')
    selected,end=completed_five_minutes(bars,now or datetime.now(timezone.utc))
    def step(price):
        value=tick(price)
        if not math.isfinite(value) or value<=0:raise ValueError(f'Invalid {title_name} tick')
        return value
    for b in selected:step(b['low'] if direction==1 else b['high'])
    holds=(confirmed_pullbacks if direction==1 else confirmed_rallies)(selected,step)
    candidates=[]
    for a_index,a in enumerate(holds):
        for b in holds[a_index+1:a_index+2]:
            if a['segment']!=b['segment'] or b['index']-a['index']<MIN_ANCHOR_BARS or b['index']<=a['confirmation_index']:continue
            if direction*(b['price']-a['price'])<max(MIN_ANCHOR_RISE*a['price'],2*step(a['price']),2*step(b['price']))-1e-12:continue
            slope=(b['price']-a['price'])/(b['index']-a['index'])
            value=lambda index:a['price']+(index-a['index'])*slope
            tolerance=lambda price:max(TOUCH_FRACTION*price,2*step(price))
            # Reject substantial body penetration while the anchors were forming.
            below=0;previous=None;invalid=False
            for bar_index in range(a['index']+1,b['confirmation_index']+1):
                bar=selected[bar_index];projected=value(bar_index)
                if previous is not None and bar['time']-previous!=INTERVAL:below=0
                below=below+1 if direction*(bar['close']-projected)<-tolerance(projected)-1e-12 else 0
                previous=bar['time']
                if below>=2:invalid=True;break
            if invalid:continue
            evidence=[a,b];broken_at=None;broken_close=None;confirmed_at=None;below=0;previous=None
            remaining={h['confirmation_index']:h for h in holds if h['index']>b['index'] and h['segment']==a['segment']}
            for bar_index in range(b['confirmation_index']+1,len(selected)):
                bar=selected[bar_index];projected=value(bar_index)
                if previous is not None and bar['time']-previous!=INTERVAL:below=0
                previous=bar['time']
                below=below+1 if direction*(bar['close']-projected)<-tolerance(projected)-1e-12 else 0
                if below>=2:
                    broken_at=bar['time']+INTERVAL;broken_close=bar['close'];break
                hold=remaining.get(bar_index)
                if hold and abs(hold['price']-value(hold['index']))<=tolerance(value(hold['index']))+1e-12:
                    evidence.append(hold)
                    if confirmed_at is None:confirmed_at=hold['confirmed_at']
            # The source chart's bar spacing, not elapsed wall-clock gaps, sets
            # the slope. This price is a Draw snapshot at the next five-minute slot.
            projected=value(len(selected))
            if projected<=0 or abs(projected-quote)/quote>.25:continue
            state='broken' if broken_at else 'confirmed' if confirmed_at else 'provisional'
            title='Broken '+title_name if state=='broken' else title_name.capitalize()
            label=f'{title} · 5m · '+('2 anchors' if len(evidence)==2 else f'{len(evidence)} touches')
            if state=='provisional':label+=' · provisional'
            candidates.append(dict(kind=kind,price=projected,time=b['confirmed_at'],
                description='Fixed-anchor five-minute '+title_name,display_text=label,
                anchors=[a,b],touches=evidence,independent_tests=len(evidence),volume=zone_volume(evidence),
                state=state,qualified_at=b['confirmed_at'],confirmed_at=confirmed_at,broken_at=broken_at,broken_close=broken_close,
                slope_per_bar=slope,projection_time=end,source_timeframe='5',end_time=end,
                thresholds={('minimum_decline' if direction==1 else 'minimum_rise'):MIN_DECLINE,
                            ('minimum_rebound' if direction==1 else 'minimum_rejection'):MIN_REBOUND,
                            'touch_fraction':TOUCH_FRACTION,'minimum_anchor_bars':MIN_ANCHOR_BARS,
                            ('minimum_anchor_rise' if direction==1 else 'minimum_anchor_fall'):MIN_ANCHOR_RISE,
                            'break_closes':2,'minimum_ticks':2},
                method='fixed_five_minute_support_ray' if direction==1 else 'fixed_five_minute_resistance_ray'))
    def rank(line):
        distance=abs(line['price']-quote)/quote
        return (-min(5,line['independent_tests']),int((distance+1e-12)/.01),line['state']=='broken',
                tuple(-int(x) for x in volume_priority(line)),distance,-line['anchors'][1]['confirmed_at'],line['anchors'][0]['time'])
    return sorted(candidates,key=rank)[:1]


def trend_marks(level):
    return [dict(shape='trend_line',points=[dict(time=a['time'],price=a['price']) for a in level['anchors']],
                 text=level['label'],overrides=json.dumps(dict(linecolor=level['color'],textcolor=level['color'],
                 linewidth=1,linestyle=level['linestyle'],extendRight=True,extendLeft=False,showLabel=True,
                 showPrice=False,showAngle=False,showBarsRange=False,showDateTimeRange=False)))]
