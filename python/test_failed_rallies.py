import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from failed_rallies import failed_rally_zones, band_label
from daily_levels import run, spaced_levels, drawing_label, label_sources
from level_explanations import explain_level
from level_inspector import inspect_chart
from test_daily_levels import Fake
from test_pane_client import Fixture

NY = ZoneInfo('America/New_York')
START = datetime(2026,10,9,6,tzinfo=NY)


def candle(minute, opened, high, low, close):
    return dict(time=(START+timedelta(minutes=minute)).timestamp(),open=opened,high=high,low=low,close=close,volume=1000)


def attempts(peaks=(1.04,1.042)):
    result = [candle(0,1,1.001,.999,1)]
    for peak in peaks:
        m=len(result)
        result += [candle(m,1.01,peak,1.005,peak-.004),
                   candle(m+1,peak-.004,peak-.004,1.005,1.01)]
    return result


def detect(bars, minute=30, quote=1.02, step=.0001):
    return failed_rally_zones(bars,quote,START+timedelta(minutes=minute),lambda p:step)


class DetectorTests(unittest.TestCase):
    def test_two_independent_failures_produce_one_padded_band_with_actual_evidence(self):
        zone=detect(attempts())[0]
        self.assertEqual(zone['independent_tests'],2)
        self.assertEqual(zone['peak_bounds'],dict(low=1.04,high=1.042))
        self.assertLess(zone['zone']['low'],1.04);self.assertGreater(zone['zone']['high'],1.042)
        self.assertEqual(zone['qualified_at'],attempts()[-1]['time'])
        self.assertTrue(all(f['failed_at']>f['peak_time'] for f in zone['failures']))
        self.assertIn('2 tests',zone['display_text'])

    def test_single_failure_and_continuing_rally_do_not_qualify(self):
        self.assertFalse(detect(attempts((1.04,))))
        bars=attempts()[:-1]+[candle(4,1.038,1.045,1.035,1.04)]
        self.assertFalse(detect(bars))

    def test_peak_candle_cannot_confirm_its_own_failure(self):
        bars=[candle(0,1,1.001,.999,1),candle(1,1,1.10,.99,1.02)]
        self.assertFalse(detect(bars))

    def test_forming_and_future_candles_do_not_confirm(self):
        bars=attempts()
        self.assertFalse(detect(bars,minute=4))
        bars[-1]['complete']=False
        self.assertFalse(detect(bars,minute=30))

    def test_exact_sixty_percent_boundary_and_tick_floor(self):
        bars=attempts((1.04,1.04));bars[0]['low']=1
        bars[2]['low']=1;bars[2]['close']=1.016
        bars[4]['low']=1;bars[4]['close']=1.016
        self.assertEqual(detect(bars)[0]['independent_tests'],2)
        bars[4]['close']=1.01601
        self.assertFalse(detect(bars))
        self.assertFalse(detect(attempts((1.015,1.015)),step=.01))

    def test_consecutive_touches_are_one_rally(self):
        bars=[candle(0,1,1.001,.999,1),candle(1,1,1.04,1,1.03),
              candle(2,1.03,1.04,1.025,1.03),candle(3,1.03,1.04,1.02,1.025),
              candle(4,1.025,1.03,1.005,1.01)]
        self.assertFalse(detect(bars))

    def test_distinct_ceilings_and_no_chain_bridging(self):
        zones=detect(attempts((1.04,1.044,1.048,1.049)))
        self.assertEqual(len(zones),2)
        self.assertEqual([z['independent_tests'] for z in zones],[2,2])
        self.assertLess(zones[0]['zone']['high'],zones[1]['zone']['low'])

    def test_small_wiggles_do_not_become_rallies(self):
        bars=[candle(0,1,1.001,.999,1),candle(1,1,1.008,1,1.004),
              candle(2,1.004,1.004,1,1.001),candle(3,1.001,1.008,1.001,1.004),
              candle(4,1.004,1.004,1,1.001)]
        self.assertFalse(detect(bars))

    def test_gap_does_not_combine_unqualified_tests(self):
        bars=attempts();bars[3]['time']+=600;bars[4]['time']+=600
        self.assertFalse(detect(bars))

    def test_yesterday_and_overnight_do_not_supply_tests(self):
        bars=attempts()
        yesterday=[dict(b,time=b['time']-86400) for b in bars]
        overnight=[dict(b,time=b['time']-10800) for b in bars]
        self.assertFalse(detect(yesterday+overnight+attempts((1.04,))))

    def test_new_rally_after_prolonged_plateau_uses_recent_base(self):
        bars=attempts((1.04,))+[candle(3,1.01,1.04,1.01,1.035)]
        bars += [candle(i,1.025,1.03,1.023,1.025) for i in range(4,14)]
        bars += [candle(14,1.025,1.042,1.025,1.038),candle(15,1.038,1.038,1.024,1.027)]
        zone=detect(bars)[0]
        self.assertEqual(zone['independent_tests'],2)
        self.assertAlmostEqual(zone['failures'][-1]['base'],1.023)

    def test_two_closes_reclaim_wick_and_one_close_do_not(self):
        bars=attempts()
        wick=candle(5,1.02,1.07,1.019,1.02)
        self.assertEqual(detect(bars+[wick])[0]['state'],'active')
        close=candle(5,1.02,1.055,1.02,1.053)
        self.assertEqual(detect(bars+[close])[0]['state'],'active')
        second=candle(6,1.053,1.058,1.052,1.055)
        zone=detect(bars+[close,second])[0]
        self.assertEqual(zone['state'],'reclaimed')
        self.assertEqual(zone['history'][-1]['time'],second['time'])
        back=candle(7,1.055,1.055,1.01,1.02)
        zone=detect(bars+[close,second,back])[0]
        self.assertEqual(zone['state'],'returned_below')
        self.assertEqual(zone['independent_tests'],2)

    def test_closes_across_a_gap_cannot_confirm_reclaim(self):
        bars=attempts()+[candle(5,1.02,1.055,1.02,1.053),candle(10,1.053,1.058,1.052,1.055)]
        self.assertEqual(detect(bars)[0]['state'],'active')

    def test_later_test_does_not_rewrite_a_previously_confirmed_reclaim(self):
        bars=attempts()+[candle(5,1.02,1.0438,1.02,1.0435),
                         candle(6,1.0435,1.045,1.0434,1.044),
                         candle(7,1.044,1.044,1.005,1.01)]
        before=detect(bars,minute=7)[0]
        after=detect(bars,minute=8)[0]
        self.assertEqual(before['state'],'reclaimed')
        self.assertEqual(after['independent_tests'],3)
        self.assertEqual(after['history'],before['history'])
        self.assertEqual(after['state'],'active')

    def test_invalid_duplicate_out_of_order_and_unaligned_candles_fail(self):
        for bars in [attempts()+[attempts()[-1]],list(reversed(attempts())),
                     [dict(attempts()[0],time=attempts()[0]['time']+1)],
                     [dict(attempts()[0],high=.5)], [dict(attempts()[0],close=float('nan'))]]:
            with self.assertRaises(ValueError):detect(bars)

    def test_zone_budget_and_price_proximity(self):
        zones=detect(attempts((1.02,1.021,1.04,1.041,1.06,1.061,1.08,1.081)))
        self.assertEqual(len(zones),3)
        self.assertFalse(detect(attempts(),quote=3))

    def test_stronger_ceiling_survives_new_nearer_two_test_zone(self):
        peaks=(1.04,1.041,1.08,1.081,1.10,1.101,1.14,1.141,1.142)
        before=detect(attempts(peaks))
        after=detect(attempts(peaks+(1.06,1.061)))
        for zones in (before,after):
            ceiling=next(z for z in zones if z['price']==1.142)
            self.assertEqual(ceiling['independent_tests'],3)
            self.assertEqual(ceiling['selection_reason'],'repeated_tests')
            self.assertEqual(len(zones),4)
        self.assertIn(1.101,[z['price'] for z in before])
        self.assertNotIn(1.101,[z['price'] for z in after])
        self.assertIn(1.061,[z['price'] for z in after])

    def test_strong_extras_bounded_and_ranked_by_tests_then_recency(self):
        peaks=(1.04,1.041,1.06,1.061,1.08,1.081,
               1.10,1.101,1.102,1.103,1.14,1.141,1.142,1.18,1.181,1.182)
        zones=detect(attempts(peaks),minute=60)
        self.assertEqual(len(zones),5)
        self.assertEqual([z['price'] for z in zones if z['selection_reason']=='repeated_tests'],[1.103,1.182])
        self.assertNotIn(1.142,[z['price'] for z in zones])

    def test_nearby_strong_ceiling_not_duplicated_and_distant_ceiling_not_retained(self):
        zones=detect(attempts((1.04,1.041,1.042,1.06,1.061,1.08,1.081)))
        self.assertEqual(len(zones),3)
        self.assertEqual(len({z['price'] for z in zones}),3)
        zones=detect(attempts((1.04,1.041,1.06,1.061,1.08,1.081,1.40,1.401,1.402)))
        self.assertEqual(len(zones),3)
        self.assertNotIn(1.402,[z['price'] for z in zones])

    def test_reclaimed_ceiling_not_retained_as_extra(self):
        bars=attempts((1.04,1.041,1.06,1.061,1.08,1.081,1.12,1.121,1.122))
        n=len(bars)
        bars += [candle(n,1.01,1.135,1.01,1.13),candle(n+1,1.13,1.14,1.13,1.135)]
        zones=detect(bars)
        self.assertEqual(len(zones),3)
        self.assertNotIn(1.122,[z['price'] for z in zones])

    def test_zero_volume_is_excluded_and_macd_remains_irrelevant(self):
        bars=[dict(b,volume=0,macd=-10) for b in attempts()]
        self.assertFalse(detect(bars))
        self.assertEqual(len(detect([dict(b,macd=-10) for b in attempts()])),1)

    def test_band_label_compact_bounds_and_reclaimed_state(self):
        self.assertEqual(band_label(.6628365,.6656635,3,'active'),
                         'Failed rallies · 3 tests · ~$0.666')
        self.assertEqual(band_label(.00012,.00014,2,'reclaimed'),
                         'Reclaimed rally zone · 2 tests · ~$0.00014')
        self.assertEqual(band_label(2.1171,2.12,2,'active'),
                         'Failed rallies · 2 tests · ~$2.12')


class CeilingRetestTests(unittest.TestCase):
    def bars(self):
        # A new, much larger rally is still pending. Its full-impulse fade
        # threshold must not hide independent local rejections of the old $2.10.
        return attempts((2.10,2.10))+[
            candle(5,2.04,2.16,2.02,2.14),
            candle(6,2.14,2.14,2.04,2.04),
            candle(7,2.04,2.06,2.04,2.05),
            candle(8,2.05,2.10,2.05,2.095),
            candle(9,2.095,2.10,2.07,2.075),
            candle(10,2.075,2.08,2.05,2.06),
            candle(11,2.06,2.10,2.06,2.09),
            candle(12,2.09,2.10,2.07,2.075)]

    def test_local_rejections_strengthen_established_ceiling_with_exact_sources(self):
        zone=detect(self.bars(),step=.01,quote=2.05)[0]
        self.assertEqual(zone['independent_tests'],4)
        self.assertEqual(zone['retest_tests'],2)
        self.assertEqual(zone['peak_bounds'],dict(low=2.10,high=2.10))
        self.assertEqual(zone['qualified_at'],self.bars()[4]['time'])
        self.assertEqual([f['peak_time'] for f in zone['failures'][-2:]],
                         [self.bars()[8]['time'],self.bars()[11]['time']])
        self.assertEqual(zone['display_text'],'Failed rallies · 4 tests · ~$2.10')
        text=explain_level(zone,2.05,label_sources(zone))
        self.assertIn('2 later ceiling retests',text)
        self.assertIn('Padded drawing range',text)
        self.assertIn('Ceiling retest $2.10',text)

    def test_local_retest_cannot_establish_a_zone_from_one_full_failure(self):
        bars=self.bars()
        # Leave only the first original failure, with the same subsequent bars.
        bars=bars[:3]+[dict(b,time=b['time']-120) for b in bars[5:]]
        self.assertFalse(detect(bars,step=.01,quote=2.05))

    def test_adjacent_touch_candles_without_move_away_do_not_add_tests(self):
        bars=self.bars()[:10]+[
            candle(10,2.075,2.10,2.07,2.09),
            candle(11,2.09,2.10,2.07,2.075)]
        zone=detect(bars,step=.01,quote=2.05)[0]
        self.assertEqual(zone['retest_tests'],1)

    def test_higher_wick_cancels_local_candidate_without_moving_ceiling(self):
        bars=self.bars()[:10]
        bars[9]=candle(9,2.095,2.12,2.07,2.075)
        zone=detect(bars,step=.01,quote=2.05)[0]
        self.assertEqual(zone['retest_tests'],0)
        self.assertEqual(zone['peak_bounds']['high'],2.10)

    def test_confirmation_requires_completed_later_candle(self):
        bars=self.bars()[:10]
        self.assertEqual(detect(bars,minute=9,step=.01,quote=2.05)[0]['retest_tests'],0)
        bars[-1]['complete']=False
        self.assertEqual(detect(bars,step=.01,quote=2.05)[0]['retest_tests'],0)
        self.assertEqual(detect(bars[:9],step=.01,quote=2.05)[0]['retest_tests'],0)

    def test_missing_minute_interrupts_retest(self):
        bars=self.bars()[:10]
        bars[-1]['time']+=60
        self.assertEqual(detect(bars,step=.01,quote=2.05)[0]['retest_tests'],0)

    def test_missing_or_insufficient_volume_cannot_qualify_retest(self):
        for volume in (None,0,99):
            bars=self.bars()[:10]
            for b in bars[8:]:b['volume']=volume
            self.assertEqual(detect(bars,step=.01,quote=2.05)[0]['retest_tests'],0)

    def test_full_failure_and_local_retest_are_not_double_counted(self):
        bars=attempts((2.10,2.10,2.10,2.10))
        zone=detect(bars,step=.01,quote=2.05)[0]
        self.assertEqual(zone['independent_tests'],4)
        self.assertEqual(len({f['peak_time'] for f in zone['failures']}),4)

    def test_later_retests_preserve_earlier_evidence_and_qualification(self):
        before=detect(self.bars()[:10],step=.01,quote=2.05)[0]
        after=detect(self.bars(),step=.01,quote=2.05)[0]
        self.assertEqual(after['qualified_at'],before['qualified_at'])
        self.assertEqual(after['failures'][:3],before['failures'])


class WorkflowTests(unittest.TestCase):
    class Client(Fake):
        def __init__(self):
            super().__init__();self.calls=[];self.bars=attempts()
        def call(self,name,**args):
            self.calls.append((name,args))
            if name=='quote_snapshot':return dict(last_price=1.02,lp_time=START.timestamp(),minmov=1,pricescale=10000)
            if name=='data_latest_intraday_time':
                times=[b['time'] for b in self.bars if b['time']<=args['end']
                       and 4<=datetime.fromtimestamp(b['time'],NY).hour<20]
                return dict(time=max(times) if times else None)
            if name=='data_get_intraday':
                return dict(bars=[b for b in self.bars if args['start']<=b['time']<args['end']])
            return super().call(name,**args)

    def test_peak_ovals_and_one_label_have_shared_ownership_and_saved_explanation(self):
        client=self.Client()
        with tempfile.TemporaryDirectory() as folder:
            client.details_path=Path(folder)/'details.json'
            result=run(client,enabled_types=['failed_rally'],now=START+timedelta(minutes=30))
            saved=json.loads(client.details_path.read_text())['NASDAQ:TEST']
            self.assertEqual(saved['levels'][0]['zone'],result['levels'][0]['zone'])
        drawings=[a for n,a in client.calls if n=='draw_shape']
        self.assertEqual([d['shape'] for d in drawings],['ellipse','ellipse','text'])
        style=json.loads(drawings[0]['overrides'])
        self.assertEqual(style['transparency'],84);self.assertTrue(style['fillBackground'])
        self.assertEqual(style['linewidth'],2)
        label_style=json.loads(drawings[-1]['overrides'])
        self.assertEqual(label_style['fontsize'],13);self.assertTrue(label_style['bold'])
        self.assertFalse(any(d['shape'] in ('horizontal_line','rectangle') for d in drawings))
        for drawing,peak in zip(drawings,result['levels'][0]['failures']):
            points=drawing['points']
            self.assertEqual([p['time'] for p in points],
                             [peak['peak_time']-120,peak['peak_time']+120,peak['peak_time']])
            self.assertEqual(points[0]['price'],peak['peak']);self.assertEqual(points[1]['price'],peak['peak'])
            self.assertGreater(points[2]['price'],peak['peak'])
        self.assertEqual(result['levels'][0]['time'],attempts()[-1]['time'])
        self.assertEqual([d['text'] for d in drawings[:2]],['',''])
        self.assertIn('~$1.04',drawings[-1]['text'])
        self.assertEqual(result['levels'][0]['entity_ids'],client.created)
        self.assertEqual(result['levels'][0]['entity_id'],client.created[-1])
        self.assertTrue(all(json.loads(d['overrides'])['backgroundColor'] == result['levels'][0]['color']
                            for d in drawings[:-1]))
        self.assertEqual(json.loads(drawings[-1]['overrides'])['color'], result['levels'][0]['color'])
        self.assertNotIn('1D',[a['timeframe'] for n,a in client.calls if n=='chart_set_timeframe'])
        self.assertEqual((client.resolution,client.session),('5','regular'))
        self.assertIn('06:04 ET',result['levels'][0]['explanation'])
        self.assertIn('TradingView',result['levels'][0]['explanation'])

    def test_unselected_category_never_requests_one_minute_history(self):
        client=self.Client();run(client,enabled_types=['resistance'])
        self.assertFalse(any(n=='data_get_intraday' for n,a in client.calls))

    def test_sunday_draw_uses_friday_session_and_dates_labels_once(self):
        client=self.Client()
        result=run(client,enabled_types=['failed_rally'],now=START+timedelta(days=2,hours=6))
        info=result['failed_rallies'];level=result['levels'][0]
        self.assertEqual((info['status'],info['date'],info['historical'],info['completed_bars']),
                         ('ok','2026-10-09',True,len(attempts())))
        self.assertEqual(level['session_date'],'2026-10-09')
        self.assertTrue(level['label'].endswith(' 10/09'))
        self.assertEqual(level['label'].count('10/09'),1)
        self.assertIn('10/09/2026 session',level['explanation'])
        self.assertNotIn('today’s completed',level['explanation'])
        requested=next(a for n,a in client.calls if n=='data_get_intraday')
        self.assertEqual(requested,dict(start=START.replace(hour=4).timestamp(),end=START.replace(hour=20).timestamp()))
        coverage=next(a for n,a in client.calls if n=='data_ensure_history')
        self.assertEqual(coverage['start'],requested['start'])
        self.assertEqual((client.resolution,client.session),('5','regular'))

    def test_holiday_draw_uses_latest_actual_session_without_weekday_guess(self):
        client=self.Client();friday=datetime(2026,9,4,6,tzinfo=NY)
        shift=(friday-START).total_seconds()
        client.bars=[dict(b,time=b['time']+shift) for b in attempts()]
        # Labor Day, Monday: a weekday-only fallback would choose Sunday.
        result=run(client,enabled_types=['failed_rally'],now=datetime(2026,9,7,12,tzinfo=NY))
        self.assertEqual(result['failed_rallies']['date'],'2026-09-04')
        self.assertTrue(result['levels'][0]['label'].endswith(' 09/04'))

    def test_current_session_keeps_labels_undated_and_does_not_merge_prior_tests(self):
        client=self.Client();current=START+timedelta(days=3)
        client.bars+= [dict(attempts()[0],time=current.timestamp())]
        result=run(client,enabled_types=['failed_rally'],now=current+timedelta(minutes=1))
        self.assertEqual(result['failed_rallies']['date'],'2026-10-12')
        self.assertFalse(result['failed_rallies']['historical'])
        self.assertEqual(result['failed_rallies']['completed_bars'],1)
        self.assertEqual(result['failed_rallies']['status'],'no_pattern')
        self.assertFalse(result['levels'])
        self.assertIn('today’s session',result['availability']['failed_rally'])
        today=run(self.Client(),enabled_types=['failed_rally'],now=START+timedelta(minutes=30))
        self.assertNotIn('10/09',today['levels'][0]['label'])

    def test_first_forming_candle_selects_today_but_supplies_no_evidence(self):
        client=self.Client();current=START+timedelta(days=3)
        client.bars += [dict(attempts()[0],time=current.timestamp())]
        result=run(client,enabled_types=['failed_rally'],now=current+timedelta(seconds=30))
        self.assertEqual(result['failed_rallies']['date'],'2026-10-12')
        self.assertEqual(result['failed_rallies']['status'],'no_trades')
        self.assertEqual(result['failed_rallies']['completed_bars'],0)
        self.assertFalse(result['levels'])
        self.assertIn('No completed one-minute',result['availability']['failed_rally'])
        self.assertNotIn('qualifying rally',result['availability']['failed_rally'])

    def test_empty_history_is_not_reported_as_no_pattern(self):
        client=self.Client();client.bars=[]
        result=run(client,enabled_types=['failed_rally'],now=START)
        self.assertEqual(result['failed_rallies']['status'],'no_trades')
        self.assertIn('No completed one-minute',result['availability']['failed_rally'])

    def test_historical_session_without_pattern_reports_its_actual_date(self):
        client=self.Client();client.bars=attempts((1.04,))
        result=run(client,enabled_types=['failed_rally'],now=START+timedelta(days=2))
        self.assertEqual(result['failed_rallies']['status'],'no_pattern')
        self.assertIn('10/09 session',result['availability']['failed_rally'])
        self.assertNotIn('today',result['availability']['failed_rally'])

    def test_last_completed_minute_of_historical_session_is_included(self):
        client=self.Client()
        shift=(START.replace(hour=19,minute=55)-START).total_seconds()
        client.bars=[dict(b,time=b['time']+shift) for b in attempts()]
        result=run(client,enabled_types=['failed_rally'],now=START+timedelta(days=2))
        self.assertEqual(result['failed_rallies']['through_time'],START.replace(hour=19,minute=59).timestamp())
        self.assertEqual(len(result['levels']),1)

    def test_before_extended_session_still_reports_not_started(self):
        client=self.Client()
        result=run(client,enabled_types=['failed_rally'],now=START.replace(hour=3))
        self.assertEqual(result['failed_rallies']['status'],'not_started')
        self.assertFalse(any(n=='data_latest_intraday_time' for n,a in client.calls))

    def test_ovals_are_created_on_minute_data_even_with_daily_levels_selected(self):
        class Placement(self.Client):
            def call(self,n,**args):
                if n=='draw_shape' and args['shape']=='ellipse':
                    self.assertion=(self.resolution,self.session)
                return super().call(n,**args)
        client=Placement()
        run(client,enabled_types=['failed_rally','gap'],now=START+timedelta(minutes=30))
        self.assertEqual(client.assertion,('1','extended'))
        self.assertEqual((client.resolution,client.session),('5','regular'))

    def test_failed_oval_creation_rolls_back_new_set_and_keeps_old_and_manual(self):
        class Failure(self.Client):
            def call(self,n,**args):
                if n=='draw_shape' and self.created:
                    raise RuntimeError('injected oval failure')
                return super().call(n,**args)
        client=Failure();client.bars=attempts((1.04,1.044,1.048,1.049))
        with self.assertRaisesRegex(RuntimeError,'oval failure'):
            run(client,enabled_types=['failed_rally'],now=START+timedelta(minutes=30))
        self.assertEqual(client.removed,['0'])
        self.assertEqual((client.resolution,client.session),('5','regular'))

    def test_label_failure_rolls_back_all_peak_ovals(self):
        class Failure(self.Client):
            def call(self,n,**args):
                if n=='draw_shape' and args['shape']=='text':raise RuntimeError('label failed')
                return super().call(n,**args)
        client=Failure()
        with self.assertRaisesRegex(RuntimeError,'label failed'):
            run(client,enabled_types=['failed_rally'],now=START+timedelta(minutes=30))
        self.assertEqual(client.removed,['0','1'])

    def test_inspector_groups_peak_selection_edits_and_partial_deletion(self):
        client=self.Client()
        result=run(client,enabled_types=['failed_rally'],now=START+timedelta(minutes=30))
        zone=result['levels'][0]
        shapes=[dict(id=m['entity_id'],points=m.get('points') or [m['point']],
                     price=(m.get('points') or [m['point']])[0]['price'],text=m['text'],color=zone['color'])
                for m in zone['marks']]
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'details.json';path.write_text(json.dumps({'url|TEST|pane:1':{'levels':[zone]}}))
            class Inspector:
                details_path=path
                def call(self,*args,**kwargs):
                    return {'result':dict(url='url',symbol='TEST',pane={'pane_id':'1'},selected_ids=['0'],shapes=shapes)}
            observed=inspect_chart(Inspector())
            self.assertEqual(len(observed['levels']),1)
            self.assertEqual(observed['selected_id'],zone['entity_id'])
            self.assertNotIn('edited or removed',observed['levels'][0]['explanation'])
            shapes[0]['points'][0]['price']+=.01
            self.assertIn('edited or removed',inspect_chart(Inspector())['levels'][0]['explanation'])
            shapes.pop()
            observed=inspect_chart(Inspector())
            self.assertEqual(len(observed['levels']),1)
            self.assertEqual(observed['selected_id'],observed['levels'][0]['entity_id'])
            self.assertEqual(observed['levels'][0]['zone'],zone['zone'])

    def test_unsupported_instrument_reports_category_unavailable(self):
        class Unsupported(self.Client):
            def call(self,n,**args):
                if n=='session_snapshot':return dict(session=self.session,premarket_supported=False)
                return super().call(n,**args)
        result=run(Unsupported(),enabled_types=['failed_rally'],now=START)
        self.assertFalse(result['levels']);self.assertIn('US stocks',result['availability']['failed_rally'])

    def test_missing_full_history_keeps_previous_drawings_and_restores(self):
        class Missing(self.Client):
            def call(self,n,**args):
                if n=='data_ensure_history':raise RuntimeError('Full one-minute intraday history did not load')
                return super().call(n,**args)
        client=Missing()
        with self.assertRaisesRegex(RuntimeError,'history did not load'):
            run(client,enabled_types=['failed_rally'],now=START+timedelta(minutes=30))
        self.assertFalse(client.created);self.assertFalse(client.removed)
        self.assertEqual((client.resolution,client.session),('5','regular'))

    def test_inspector_treats_rectangle_as_zone_and_detects_edits(self):
        zone=detect(attempts())[0]
        zone.update(entity_id='zone',label=drawing_label(zone,START),color='#ff7043',
                    explanation=explain_level(zone,1.02,label_sources(zone)))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'details.json';path.write_text(json.dumps({'url|TEST|pane:1':{'levels':[zone]}}))
            class Inspector:
                details_path=path
                def call(self,*args,**kwargs):
                    return {'result':dict(url='url',symbol='TEST',pane={'pane_id':'1'},selected_ids=['zone'],
                        shapes=[dict(id='zone',price=zone['zone']['high'],points=[{'price':zone['zone']['high']},{'price':zone['zone']['low']}],text=zone['label'],color=zone['color'])])}
            client=Inspector();result=inspect_chart(client)
            self.assertNotIn('edited',result['levels'][0]['explanation'])
            self.assertEqual(result['selected_id'],'zone')
            zone['zone']['low']-=.01
            self.assertIn('edited this zone',inspect_chart(client)['levels'][0]['explanation'])


class PaneTests(unittest.TestCase):
    def setUp(self):self.client=Fixture()
    def tearDown(self):self.client.close()

    def test_latest_session_uses_selected_minute_candles_and_excludes_future_and_overnight(self):
        from pane_client import PaneClient
        sunday=START+timedelta(days=2)
        times=[START.timestamp(),START.replace(hour=20).timestamp(),(START+timedelta(days=3)).timestamp()]
        self.client.send(op='intraday',bars=[[t,1,1.01,.99,1,1] for t in times],end=True)
        bound=PaneClient(self.client)
        try:
            with self.assertRaisesRegex(RuntimeError,'One-minute chart not ready'):
                bound.call('data_latest_intraday_time',end=sunday.timestamp())
            bound.call('chart_set_timeframe',timeframe='1')
            latest=bound.call('data_latest_intraday_time',end=sunday.timestamp())
            self.assertEqual(latest['time'],START.timestamp())
            self.client.send(op='select',index=1)
            with self.assertRaisesRegex(RuntimeError,'Selected chart pane changed'):
                bound.call('data_latest_intraday_time',end=sunday.timestamp())
        finally:bound.release()

    def test_latest_session_can_be_empty(self):
        from pane_client import PaneClient
        self.client.send(op='intraday',bars=[],end=True)
        bound=PaneClient(self.client)
        try:
            # Use the fixture setter directly: an empty chart cannot pass
            # normal chart readiness, but the read itself still reports null.
            bound.evaluate("widget.setResolution('1'); return {};")
            self.assertIsNone(bound.call('data_latest_intraday_time',end=START.timestamp())['time'])
        finally:bound.release()

    def test_bounded_read_retains_more_than_five_hundred_bars(self):
        from pane_client import PaneClient
        raw=[[START.timestamp()+i*60,1,1.01,.99,1,1] for i in range(960)]
        self.client.send(op='intraday',bars=raw,end=True)
        bound=PaneClient(self.client)
        try:
            bound.call('chart_set_timeframe',timeframe='1')
            read=bound.call('data_get_intraday',start=START.timestamp(),end=START.timestamp()+960*60)
            self.assertEqual(len(read['bars']),960)
            self.assertEqual(read['bars'][0]['time'],raw[0][0])
        finally:bound.release()

    def test_rectangle_is_pane_local_and_selection_change_rolls_it_back(self):
        from pane_client import PaneClient
        bound=PaneClient(self.client)
        try:
            result=bound.call('draw_shape',shape='rectangle',point=dict(time=1,price=1.04),
                              point2=dict(time=60,price=1.03),text='Rally failures · 2 tests',overrides='{}')
            before=self.client.send(op='snapshot')
            self.assertEqual(len(before['panes'][0]['shapes'][0][1]['points']),2)
            self.assertIsNone(before['panes'][0]['shapes'][0][1]['link'])
            self.assertFalse(before['panes'][1]['shapes'])
            self.client.send(op='switchDuringCreate')
            with self.assertRaisesRegex(RuntimeError,'Selected chart pane changed'):
                bound.call('draw_shape',shape='rectangle',point=dict(time=1,price=1.04),
                           point2=dict(time=60,price=1.03),text='New zone',overrides='{}')
            after=self.client.send(op='snapshot')
            self.assertEqual(after['panes'][0]['shapes'],before['panes'][0]['shapes'])
            self.assertFalse(after['panes'][1]['shapes'])
        finally:bound.release()

    def test_three_point_ellipse_stays_on_selected_pane(self):
        from pane_client import PaneClient
        bound=PaneClient(self.client)
        points=[dict(time=60,price=1.04),dict(time=300,price=1.04),dict(time=180,price=1.043)]
        try:
            bound.call('draw_shape',shape='ellipse',points=points,text='',overrides='{}')
            snapshot=self.client.send(op='snapshot')
            self.assertEqual(snapshot['panes'][0]['shapes'][0][1]['points'],points)
            self.assertIsNone(snapshot['panes'][0]['shapes'][0][1]['link'])
            self.assertFalse(snapshot['panes'][1]['shapes'])
        finally:bound.release()


if __name__=='__main__':unittest.main()
