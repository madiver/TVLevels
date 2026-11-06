import json
import unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

from event_levels import event_levels,minute_context,EVENT_TYPES
from daily_levels import run,levels_near,spaced_levels,label_sources,drawing_label
from level_explanations import explain_level
from test_daily_levels import Fake
from test_pane_client import Fixture
from pane_client import PaneClient
from level_styles import drawing_style
from level_catalog import CATALOG

NY=ZoneInfo('America/New_York')
START=datetime(2026,4,1,9,30,tzinfo=NY)
NOW=START+timedelta(days=140,minutes=60)

def candle(time,opened=2.4,high=2.5,low=2.3,close=2.4,volume=1000):
    return dict(time=time.timestamp(),open=opened,high=high,low=low,close=close,volume=volume)

def history():
    daily=[candle(START+timedelta(days=i)) for i in range(140)]
    daily[40]=candle(START+timedelta(days=40),2.39,10.71,2.39,5.35,40000000)
    pmday=(START+timedelta(days=120)).replace(hour=4,minute=0)
    pm=[candle(pmday,3.11,6.27,2.71,3.27,3200000),
        candle(pmday+timedelta(minutes=30),3.27,3.8,2.55,2.71,2000000)]
    return daily,pm

def high_history():
    """A high-volume $3.47 regular high beneath separate premarket highs."""
    daily,_=history()
    source=START+timedelta(days=40)
    daily[40]=candle(source,3.175,3.47,1.95,2.32,133012597)
    pm=[candle(source.replace(hour=4,minute=0),3.1,3.67,1.9,3.17,60000000),
        candle((START+timedelta(days=120)).replace(hour=4,minute=0),3,3.97,2.5,2.7,10000000)]
    return daily,pm

def select(daily=None,pm=None,minutes=(),enabled=EVENT_TYPES,quote=3.83,now=NOW,today_range=None):
    defaults=history()
    return event_levels(defaults[0] if daily is None else daily,defaults[1] if pm is None else pm,
        list(minutes),quote,now,enabled,levels_near,lambda p:.01,today_range or dict(low=2.87,high=5.94))

def minute(index,close,low=None,high=None):
    return candle(NOW.replace(hour=9,minute=30)+timedelta(minutes=index),close,
                  max(close,high if high is not None else close+.01),
                  min(close,low if low is not None else close-.01),close,1000)


class Events(unittest.TestCase):
    def test_spike_close_and_prior_premarket_high_survive_a_pullback(self):
        levels=select()
        self.assertEqual({(x['kind'],x['price']) for x in levels},
                         {('event_close',5.35),('prior_premarket_high',6.27)})
        high=next(x for x in levels if x['price']==6.27)
        self.assertEqual(high['event']['selection'],'above_today_high')
        self.assertGreater(6.27,3.83*1.25)
        self.assertEqual(high['event']['today_range']['high'],5.94)

    def test_regular_open_and_overnight_are_excluded_from_premarket(self):
        daily,pm=history();t=datetime.fromtimestamp(pm[0]['time'],NY)
        pm=[candle(t.replace(hour=3,minute=30),3,80,2,3,10000000)]+pm
        pm += [candle(t.replace(hour=9,minute=30),3,90,2,3,10000000)]
        self.assertEqual(next(x for x in select(daily,pm) if x['kind']=='prior_premarket_high')['price'],6.27)

    def test_nine_am_half_hour_is_included_without_regular_prices(self):
        daily,pm=history();t=datetime.fromtimestamp(pm[-1]['time'],NY)
        pm += [candle(t.replace(hour=9,minute=0),3,6.5,2,3,1000000)]
        self.assertEqual(next(x for x in select(daily,pm) if x['kind']=='prior_premarket_high')['price'],6.5)

    def test_today_cannot_be_a_historical_event(self):
        daily,pm=history()
        daily += [candle(NOW.replace(hour=9,minute=30),3,20,2,6.1,100000000)]
        pm += [candle(NOW.replace(hour=4,minute=0),3,6.4,2,3,100000000)]
        self.assertFalse(any(x['price'] in (6.1,6.4) for x in select(daily,pm)))

    def test_normal_closes_and_event_followthrough_do_not_proliferate(self):
        daily,pm=history()
        daily[41]=candle(START+timedelta(days=41),4.99,5.74,3.09,4.65,1000000)
        levels=select(daily,pm)
        self.assertEqual([x['price'] for x in levels if x['kind']=='event_close'],[5.35])

    def test_old_events_and_remote_levels_are_omitted(self):
        daily,pm=history();daily[5]=candle(START+timedelta(days=5),3,20,2,6.2,100000000)
        self.assertFalse(any(x['price']==6.2 for x in select(daily,pm)))
        pm[0]['high']=60
        self.assertFalse(any(x['kind']=='prior_premarket_high' for x in select(daily,pm)))

    def test_each_category_can_be_disabled_independently(self):
        for kind in EVENT_TYPES:
            self.assertEqual({x['kind'] for x in select(enabled={kind},today_range=dict(low=2.87,high=10.6))},{kind})
        self.assertFalse(select(enabled=set()))

    def test_display_cap_and_two_overhead_slots(self):
        daily,pm=history()
        for i,p in enumerate((6,6.1,6.2,6.3,6.4,6.5)):
            pm.append(candle((START+timedelta(days=121+i)).replace(hour=4,minute=0),3,p,2.5,3,1000000))
        levels=select(daily,pm)
        self.assertLessEqual(len(spaced_levels(levels)),4)
        self.assertEqual(sorted(x['price'] for x in levels if x['price']>5.94),[6,6.1])

    def test_merge_preserves_both_sources_and_event_context(self):
        event=next(x for x in select() if x['kind']=='event_close')
        base=dict(kind='former_support',price=5.36,time=START.timestamp(),description='Prior support')
        merged=spaced_levels([base,event])[0]
        sources=label_sources(merged)
        self.assertEqual({x['kind'] for x in sources},{'former_support','event_close'})
        self.assertEqual(merged['events'][0]['price'],5.35)
        self.assertIn('High-volume close',drawing_label(merged,NOW))
        self.assertIn('Historical high-volume close',explain_level(merged,3.83,sources))

    def test_bad_history_rejected(self):
        daily,pm=history();daily[40]['volume']=float('nan')
        with self.assertRaises(ValueError):select(daily,pm)
        daily,pm=history()
        with self.assertRaises(ValueError):select(daily,list(reversed(pm)))

    def test_repeated_merge_keeps_original_premarket_event_kind(self):
        event=next(x for x in select() if x['kind']=='prior_premarket_high')
        corridor=dict(kind='gap',price=6.26,time=START.timestamp(),description='Gap entry')
        merged=spaced_levels([event,corridor])[0]
        merged=spaced_levels([merged,dict(kind='previous_close',price=6.275,time=START.timestamp(),description='Prev close')])[0]
        self.assertEqual([e['kind'] for e in merged['events']],['prior_premarket_high'])
        self.assertIn('Historical premarket peak',explain_level(merged,3.83,label_sources(merged)))


class HighVolumeHighs(unittest.TestCase):
    def select(self,daily=None,pm=None,enabled=EVENT_TYPES,quote=2.71,today_range=None,**kwargs):
        defaults=high_history()
        return select(defaults[0] if daily is None else daily,defaults[1] if pm is None else pm,
                      enabled=enabled,quote=quote,today_range=today_range or dict(low=1.8,high=3.36),**kwargs)

    def test_regular_high_is_independent_of_close_and_premarket_categories(self):
        levels=self.select(enabled={'event_high'})
        self.assertEqual([(x['kind'],x['price']) for x in levels],[('event_high',3.47)])
        self.assertEqual(levels[0]['event']['source_close'],2.32)
        self.assertEqual(levels[0]['event']['volume'],133012597)

    def test_pullback_preserves_nearest_high_above_today_range_with_shared_cap(self):
        levels=self.select()
        self.assertEqual({(x['kind'],x['price']) for x in levels},
                         {('event_close',2.32),('event_high',3.47),('prior_premarket_high',3.67)})
        high=next(x for x in levels if x['kind']=='event_high')
        self.assertGreater(high['price'],2.71*1.25)
        self.assertEqual(high['event']['selection'],'above_today_high')
        self.assertEqual(high['event']['today_range']['high'],3.36)
        self.assertNotIn(3.97,[x['price'] for x in levels])
        self.assertLessEqual(len(spaced_levels(levels)),4)

    def test_same_volume_range_and_independent_spike_filters_as_closes(self):
        for reason in ('volume','range','earlier_volume'):
            daily,pm=high_history()
            if reason=='volume':daily[40]['volume']=1999
            elif reason=='range':daily[40]=candle(START+timedelta(days=40),volume=133012597)
            else:daily[39]['volume']=200000000
            with self.subTest(reason=reason):
                self.assertFalse(self.select(daily,pm,enabled={'event_high'}))

    def test_later_breaks_and_returns_do_not_erase_or_move_source_high(self):
        daily,pm=high_history()
        daily[44]=candle(START+timedelta(days=44),2.4,4.5,2.3,3.55)
        daily[45]=candle(START+timedelta(days=45),3.55,3.9,3.2,3.6)
        daily[46]=candle(START+timedelta(days=46),3.6,3.8,3.1,3.38)
        high=self.select(daily,pm,enabled={'event_high'})[0]
        self.assertEqual(high['price'],3.47)
        self.assertEqual(high['time'],daily[40]['time'])
        self.assertEqual(high['kind'],'event_high')

    def test_today_and_older_than_lookback_cannot_create_historical_highs(self):
        daily,_=high_history()
        daily += [candle(NOW,3,3.6,2,2.9,200000000)]
        self.assertEqual([x['price'] for x in self.select(daily,enabled={'event_high'})],[3.47])
        daily=high_history()[0]
        daily[5]=daily[40] | {'time':daily[5]['time']}
        daily[40]=candle(START+timedelta(days=40))
        self.assertFalse(self.select(daily,enabled={'event_high'}))

    def test_minute_context_is_applied_to_high_instead_of_close(self):
        bars=[minute(0,3.5),minute(1,3.51)]
        high=self.select(enabled={'event_high'},minutes=bars)[0]
        self.assertEqual(high['event']['intraday']['state'],'reclaimed')
        self.assertEqual(high['event']['intraday']['quote_side'],'below')
        high=self.select(enabled={'event_high'},minutes=bars,now=NOW.replace(hour=9,minute=31,second=30))[0]
        self.assertIsNone(high['event']['intraday']['qualified_at'])
        self.assertNotEqual(high['event']['intraday']['state'],'reclaimed')

    def test_nearby_high_merges_without_losing_source_or_date_on_repeated_spacing(self):
        high=self.select(enabled={'event_high'})[0]
        merged=spaced_levels([high,dict(kind='resistance',price=3.48,time=START.timestamp(),description='Resistance')])[0]
        merged=spaced_levels([merged,dict(kind='previous_high',price=3.485,time=START.timestamp(),description='Prev high')])[0]
        self.assertEqual(len(merged['events']),1)
        self.assertEqual((merged['events'][0]['kind'],merged['events'][0]['price']),('event_high',3.47))
        self.assertEqual(merged['events'][0]['time'],high['time'])
        self.assertIn('High-volume high 05/11',drawing_label(merged,NOW))
        text=explain_level(merged,2.71,label_sources(merged))
        for words in ('Historical high-volume high: $3.47','closing at $2.32','133,012,597 shares','Premarket and after-hours highs are excluded'):
            self.assertIn(words,text)
        self.assertNotIn('Historical high-volume close:',text)

    def test_catalog_and_both_themes_preserve_event_style(self):
        self.assertEqual(CATALOG['event_high']['title'],'Historical high-volume highs')
        high=self.select(enabled={'event_high'})[0]
        for theme in ('dark','light'):
            for quote in (2.71,4):
                style=drawing_style(high,quote,theme=theme)
                self.assertEqual((style['style_family'],style['linestyle'],style['linewidth']),('event',2,1))


class Context(unittest.TestCase):
    def context(self,bars,quote=5.4,now=NOW):return minute_context(5.35,bars,quote,now,lambda p:.01)
    def test_single_wick_and_single_close_do_not_confirm_reclaim(self):
        self.assertEqual(self.context([minute(0,5.1,high=5.5)])['state'],'tested')
        self.assertEqual(self.context([minute(0,5.4)])['state'],'above_unconfirmed')
    def test_two_consecutive_closes_then_separate_retest(self):
        bars=[minute(0,5.4),minute(1,5.41)]
        self.assertEqual(self.context(bars)['state'],'reclaimed')
        bars += [minute(2,5.4,low=5.35)]
        self.assertEqual(self.context(bars)['state'],'retested')
        self.assertEqual(self.context(bars)['retested_at'],bars[-1]['time'])
    def test_loss_and_later_reclaim(self):
        bars=[minute(0,5.4),minute(1,5.41),minute(2,5.2)]
        self.assertEqual(self.context(bars,3.83)['state'],'lost')
        bars += [minute(3,5.4),minute(4,5.41)]
        self.assertEqual(self.context(bars)['state'],'reclaimed')
    def test_missing_minutes_forming_and_future_candles_cannot_combine(self):
        self.assertEqual(self.context([minute(0,5.4),minute(2,5.41)])['state'],'above_unconfirmed')
        bars=[minute(0,5.4),minute(1,5.41)]
        self.assertEqual(self.context(bars,now=NOW.replace(hour=9,minute=31,second=30))['state'],'above_unconfirmed')
        bars[1]['complete']=False
        self.assertEqual(self.context(bars)['state'],'above_unconfirmed')
    def test_previous_session_does_not_confirm_today(self):
        bars=[dict(minute(i,5.4),time=minute(i,5.4)['time']-86400) for i in range(2)]
        self.assertEqual(self.context(bars,3.83)['state'],'resistance')
    def test_context_explains_lost_level_and_source_date(self):
        event=next(x for x in select(minutes=[minute(0,5.4),minute(1,5.41),minute(2,5.2)]) if x['kind']=='event_close')
        text=explain_level(event,3.83,label_sources(event))
        self.assertIn('lost level',text);self.assertIn('Historical high-volume close',text)
        self.assertIn('not rules attributed',text)


class Workflow(unittest.TestCase):
    class Client(Fake):
        def __init__(self):super().__init__();self.calls=[]
        def call(self,name,**args):
            self.calls.append((name,args))
            if name=='quote_snapshot':return dict(last_price=3.83,lp_time=NOW.timestamp())
            if name=='data_get_ohlcv':return dict(bars=history()[0]+[candle(NOW.replace(hour=9,minute=30),3,5.94,2.87,3.83,1000000)])
            if name=='data_get_session_history':return dict(bars=history()[1])
            if name=='data_get_intraday':return dict(bars=[minute(0,5.4),minute(1,5.41),minute(2,5.2)])
            return super().call(name,**args)
    def test_workflow_draws_both_events_and_restores_original(self):
        client=self.Client();result=run(client,enabled_types=EVENT_TYPES,now=NOW)
        self.assertEqual({x['price'] for x in result['levels']},{5.35,6.27})
        self.assertEqual((client.resolution,client.session),('5','regular'))
        self.assertNotIn('manual',client.removed)
        self.assertTrue(all('intraday' in e for x in result['levels'] for e in x['events']))
    def test_event_history_failure_preserves_old_drawings_and_restores(self):
        class Missing(self.Client):
            def call(self,name,**args):
                if name=='data_ensure_history' and args.get('session_name')=='historical premarket':raise RuntimeError('Incomplete historical premarket')
                return super().call(name,**args)
        client=Missing()
        with self.assertRaisesRegex(RuntimeError,'Incomplete'):run(client,enabled_types=EVENT_TYPES,now=NOW)
        self.assertFalse(client.created);self.assertFalse(client.removed)
        self.assertEqual((client.resolution,client.session),('5','regular'))
    def test_disabled_categories_skip_historical_and_minute_reads(self):
        client=self.Client();run(client,enabled_types=['previous_open'],now=NOW)
        self.assertFalse(any(n in ('data_get_session_history','data_get_intraday') for n,a in client.calls))
    def test_unsupported_events_explain_omission(self):
        class Unsupported(self.Client):
            def call(self,name,**args):
                if name=='session_snapshot':return dict(session=self.session,premarket_supported=False)
                return super().call(name,**args)
        result=run(Unsupported(),enabled_types=EVENT_TYPES,now=NOW)
        self.assertFalse(result['levels']);self.assertEqual(set(result['availability']),EVENT_TYPES)

    def test_high_only_draw_uses_regular_daily_data_without_premarket_history(self):
        class HighOnly(self.Client):
            def call(self,name,**args):
                if name=='quote_snapshot':return dict(last_price=2.71,lp_time=NOW.timestamp())
                if name=='data_get_ohlcv':
                    return dict(bars=high_history()[0]+[candle(NOW,2.8,3.36,1.8,2.71,1000000)])
                return super().call(name,**args)
        client=HighOnly()
        result=run(client,enabled_types={'event_high'},now=NOW)
        self.assertEqual([(x['kind'],x['price']) for x in result['levels']],[('event_high',3.47)])
        high=result['levels'][0]
        self.assertEqual(high['label'],'High-volume high 05/11')
        self.assertEqual(high['events'][0]['price'],3.47)
        self.assertIn('133,012,597 shares',high['explanation'])
        self.assertEqual((client.resolution,client.session),('5','regular'))
        self.assertNotIn('manual',client.removed)
        self.assertFalse(any(n=='data_get_session_history' or (n=='chart_set_timeframe' and a['timeframe']=='30') for n,a in client.calls))


class HistoricalPane(unittest.TestCase):
    def test_history_is_checked_after_the_last_permitted_load(self):
        client=Fixture();bound=PaneClient(client)
        try:
            raw=[[START.timestamp(),2.4,2.5,2.3,2.4,100]]
            earlier=[[START.timestamp()-1800,2.4,2.5,2.3,2.4,100]]
            client.send(op='intraday',bars=raw,earlier=earlier,end=False)
            bound.call('chart_set_timeframe',timeframe='30')
            self.assertTrue(bound.call('data_ensure_history',start=earlier[0][0],max_requests=1)['complete'])
        finally:bound.release();client.close()
    def test_thirty_minute_range_is_bound_to_selected_pane(self):
        client=Fixture();bound=PaneClient(client)
        try:
            raw=[[START.timestamp()+i*1800,2.4,2.5,2.3,2.4,100] for i in range(3)]
            client.send(op='intraday',bars=raw,end=True)
            with self.assertRaisesRegex(RuntimeError,'Thirty-minute history not ready'):
                bound.call('data_get_session_history',start=raw[0][0],end=raw[-1][0])
            bound.call('chart_set_timeframe',timeframe='30')
            result=bound.call('data_get_session_history',start=raw[0][0],end=raw[-1][0])
            self.assertEqual(len(result['bars']),2)
            client.send(op='select',index=1)
            with self.assertRaisesRegex(RuntimeError,'Selected chart pane changed'):
                bound.call('data_get_session_history',start=raw[0][0],end=raw[-1][0])
        finally:bound.release();client.close()


if __name__=='__main__':unittest.main()
