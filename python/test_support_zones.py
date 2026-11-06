import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
import test_failed_rallies as rallies
from support_zones import support_zones, support_label
from daily_levels import run, clear_levels, drawing_label, label_sources
from level_explanations import explain_level
from level_styles import drawing_style
from level_inspector import inspect_chart

START = rallies.START
candle = rallies.candle


def attempts(troughs=(.96,.958)):
    return [dict(b,open=2-b['open'],high=2-b['low'],low=2-b['high'],close=2-b['close'])
            for b in rallies.attempts(tuple(2-t for t in troughs))]


def detect(bars,minute=30,quote=.98,step=.0001):
    return support_zones(bars,quote,START+timedelta(minutes=minute),lambda p:step)


def lifecycle():
    return attempts()+[candle(5,.99,1,.95,.95),candle(6,.95,.954,.949,.949),
                       candle(7,.95,.958,.945,.95),candle(8,.95,.975,.95,.97),
                       candle(9,.97,.985,.965,.98)]


class SupportDetectorTests(unittest.TestCase):
    def test_single_confirmed_hold_is_not_displayed(self):
        self.assertFalse(detect(attempts((.96,))))

    def test_repeated_holds_group_actual_lows_and_qualify_on_second_confirmation(self):
        zone=detect(attempts())[0]
        self.assertEqual(zone['independent_tests'],2)
        self.assertAlmostEqual(zone['price'],.958)
        self.assertLess(zone['zone']['low'],.958)
        self.assertGreater(zone['zone']['high'],.96)
        self.assertEqual(zone['qualified_at'],attempts()[4]['time'])
        self.assertTrue(all(h['confirmed_at']>h['trough_time'] for h in zone['holds']))
        self.assertIn('Support holds · 2 tests',zone['display_text'])

    def test_continuing_selloff_and_trough_candle_cannot_confirm_a_hold(self):
        self.assertFalse(detect(attempts((.96,))[:-1]))
        self.assertFalse(detect([candle(0,1,1.01,.99,1),candle(1,1,1.01,.9,.98)]))
        bars=attempts((.96,))[:-1]+[candle(2,.964,.965,.95,.951)]
        self.assertFalse(detect(bars))

    def test_forming_and_future_rebounds_cannot_confirm(self):
        bars=attempts((.96,))
        self.assertFalse(detect(bars,minute=2))
        bars[-1]['complete']=False
        self.assertFalse(detect(bars))

    def test_unconfirmed_second_test_does_not_qualify_area(self):
        self.assertFalse(detect(attempts(),minute=4))
        bars=attempts();bars[-1]['complete']=False
        self.assertFalse(detect(bars))

    def test_other_sessions_and_overnight_are_not_evidence(self):
        bars=[dict(b,time=b['time']-86400) for b in attempts()]
        self.assertFalse(detect(bars))
        bars=[dict(b,time=b['time']-10800) for b in attempts()]
        self.assertFalse(detect(bars))

    def test_small_wiggles_and_tick_floor_excluded(self):
        self.assertFalse(detect([candle(0,1,1.001,.999,1),
                                candle(1,1,1,.995,.996),candle(2,.996,1,.996,.999)]))
        self.assertFalse(detect(attempts(),step=.05))

    def test_sixty_percent_rebound_boundary(self):
        bars=attempts((.96,.96));bars[0]['high']=1
        bars[2].update(high=1,close=.984)
        bars[4].update(high=1,close=.984)
        self.assertEqual(detect(bars)[0]['independent_tests'],2)
        bars[4]['close']=.98399
        self.assertFalse(detect(bars))

    def test_missing_minutes_separate_hold_groups_and_interrupt_candidates(self):
        first=attempts((.96,))
        bars=first+[dict(b,time=b['time']+780) for b in first]
        self.assertFalse(detect(bars))
        bars=attempts((.96,));bars[-1]['time']+=60
        self.assertFalse(detect(bars))

    def test_repeated_touches_without_independent_rebounds_are_one_hold(self):
        bars=attempts((.96,))[:-1]+[candle(2,.964,.97,.96,.965),candle(3,.965,.995,.96,.99)]
        self.assertFalse(detect(bars))

    def test_no_chain_bridging(self):
        zones=detect(attempts((.96,.956,.952,.951)))
        self.assertEqual(len(zones),2)
        self.assertEqual([z['independent_tests'] for z in zones],[2,2])

    def test_expired_candidate_restarts_from_recent_high(self):
        bars=attempts((.96,))[:-1]
        bars += [candle(m,.976,.977,.975,.976) for m in range(2,12)]
        bars += [candle(12,.976,.977,.96,.964),candle(13,.964,.975,.964,.973)]
        self.assertFalse(detect(bars))
        bars += [candle(14,.973,.975,.958,.96),candle(15,.96,.98,.96,.975)]
        zone=detect(bars)[0]
        self.assertEqual(zone['independent_tests'],2)
        self.assertAlmostEqual(zone['holds'][0]['base'],.977)
        self.assertEqual(zone['holds'][0]['trough_time'],bars[-4]['time'])

    def test_later_breaks_do_not_relabel_or_remove_successful_holds(self):
        before=detect(attempts())[0]
        for minute in (6,7,8,10):
            after=next(z for z in detect(lifecycle(),minute=minute) if z['holds'][0]['trough_time']==before['holds'][0]['trough_time'])
            self.assertEqual({k:v for k,v in after.items() if k!='end_time'},
                             {k:v for k,v in before.items() if k!='end_time'})

    def test_future_hold_adds_evidence_without_rewriting_existing_sources(self):
        before=next(z for z in detect(lifecycle()) if z['independent_tests']==2)
        bars=lifecycle()+[candle(10,.98,1,.957,.96),candle(11,.96,1,.96,.99)]
        after=next(z for z in detect(bars) if z['holds'][0]['trough_time']==before['holds'][0]['trough_time'])
        self.assertEqual(after['holds'][:2],before['holds'])
        self.assertEqual(after['qualified_at'],before['qualified_at'])
        self.assertEqual(after['independent_tests'],3)

    def test_bounded_nearby_and_strong_floors(self):
        troughs=(.96,.959,.94,.939,.92,.919,.90,.899,.898,.86,.859,.858,.82,.819,.818)
        zones=detect(attempts(troughs),minute=60,quote=.98)
        self.assertEqual(len(zones),5)
        self.assertEqual(len([z for z in zones if z['selection_reason']=='repeated_tests']),2)
        self.assertTrue(all(abs(z['price']-.98)/.98<=.25 for z in zones))
        self.assertEqual(len({z['price'] for z in zones}),len(zones))
        self.assertFalse(detect(attempts(),quote=2))

    def test_repeated_holds_win_equal_proximity_tie_and_are_not_duplicated(self):
        zones=detect(attempts((.96,.96,.96,.93,.93,.90,.90,.86,.86,.86)),quote=.98)
        self.assertEqual(len({z['price'] for z in zones}),len(zones))
        self.assertTrue(all(z['independent_tests']>=3 for z in zones if z['selection_reason']=='repeated_tests'))

    def test_invalid_data_and_ticks_fail_explicitly(self):
        for bars in (list(reversed(attempts())),[dict(attempts()[0],low=-1)],
                     [dict(attempts()[0],close=float('nan'))]):
            with self.assertRaises(ValueError):detect(bars)
        for quote in (0,float('nan')):
            with self.assertRaises(ValueError):detect(attempts(),quote=quote)
        with self.assertRaises(ValueError):detect(attempts(),step=0)

    def test_green_style_is_independent_of_quote_and_legacy_state(self):
        zone=detect(attempts())[0]
        for quote in (.9,1.1):
            for old_state in ('holding','broken','failed_retest','reclaimed'):
                style=drawing_style(dict(zone,state=old_state),quote)
                self.assertEqual(style['color'],'#66bb6a')
                self.assertEqual((style['linewidth'],style['linestyle']),(2,0))


class FloorRetestTests(unittest.TestCase):
    def bars(self):
        return [candle(0,2.20,2.20,2.19,2.20),
                candle(1,2.20,2.20,2.10,2.11),
                candle(2,2.11,2.19,2.11,2.18),
                candle(3,2.18,2.18,2.10,2.11),
                candle(4,2.11,2.19,2.11,2.18),
                # The full selloff to $2.04 never gets its 60% recovery.
                # Local bounces at the established $2.10 still qualify.
                candle(5,2.18,2.19,2.04,2.06),
                candle(6,2.06,2.13,2.06,2.125),
                candle(7,2.125,2.13,2.12,2.125),
                candle(8,2.125,2.125,2.10,2.105),
                candle(9,2.105,2.125,2.10,2.125),
                candle(10,2.125,2.13,2.12,2.125),
                candle(11,2.125,2.125,2.10,2.105),
                candle(12,2.105,2.125,2.10,2.125)]

    def test_rounding_shows_actual_floor_with_subdollar_precision(self):
        self.assertEqual(support_label(2.10,2.1071,4),'Support holds · 4 tests · ~$2.10')
        self.assertEqual(support_label(.958,.96,2),'Support holds · 2 tests · ~$0.958')
        self.assertEqual(support_label(.00012,.00014,2),'Support holds · 2 tests · ~$0.00012')
        self.assertEqual(support_label(.96,.96,1),'Support hold · 1 test · ~$0.960')

    def test_local_bounces_strengthen_floor_with_exact_sources_and_explanation(self):
        zone=detect(self.bars(),step=.01,quote=2.15)[0]
        self.assertEqual((zone['independent_tests'],zone['retest_tests']),(4,2))
        self.assertEqual(zone['trough_bounds'],dict(low=2.10,high=2.10))
        self.assertEqual(zone['qualified_at'],self.bars()[4]['time'])
        self.assertEqual([h['trough_time'] for h in zone['holds'][-2:]],
                         [self.bars()[8]['time'],self.bars()[11]['time']])
        self.assertEqual(zone['display_text'],'Support holds · 4 tests · ~$2.10')
        text=explain_level(zone,2.15,label_sources(zone))
        self.assertIn('2 later floor retests',text)
        self.assertIn('Floor retest held at $2.10',text)
        self.assertIn('Padded drawing range',text)

    def test_one_full_hold_cannot_establish_floor_from_local_bounces(self):
        bars=self.bars()
        bars=bars[:3]+[dict(b,time=b['time']-120) for b in bars[5:]]
        self.assertFalse(detect(bars,step=.01,quote=2.15))

    def test_adjacent_touches_without_separate_move_away_count_once(self):
        bars=self.bars()[:10]+[candle(10,2.125,2.125,2.10,2.105),
                                candle(11,2.105,2.125,2.10,2.125)]
        self.assertEqual(detect(bars,step=.01,quote=2.15)[0]['retest_tests'],1)

    def test_lower_wick_cancels_candidate_and_preserves_historical_floor(self):
        bars=self.bars()[:10]
        bars[9]=candle(9,2.105,2.125,2.08,2.125)
        zone=detect(bars,step=.01,quote=2.15)[0]
        self.assertEqual(zone['retest_tests'],0)
        self.assertEqual(zone['price'],2.10)
        self.assertNotIn('state',zone)
        self.assertTrue(zone['display_text'].startswith('Support holds'))

    def test_forming_future_and_same_trough_bar_cannot_confirm(self):
        bars=self.bars()[:10]
        self.assertEqual(detect(bars,minute=9,step=.01,quote=2.15)[0]['retest_tests'],0)
        bars[-1]['complete']=False
        self.assertEqual(detect(bars,step=.01,quote=2.15)[0]['retest_tests'],0)
        bars= self.bars()[:9]
        bars[-1].update(high=2.125,close=2.125)
        self.assertEqual(detect(bars,step=.01,quote=2.15)[0]['retest_tests'],0)

    def test_missing_minute_and_volume_cannot_confirm(self):
        bars=self.bars()[:10];bars[-1]['time']+=60
        self.assertEqual(detect(bars,step=.01,quote=2.15)[0]['retest_tests'],0)
        for volume in (None,0,99):
            bars=self.bars()[:10]
            for b in bars[8:]:b['volume']=volume
            self.assertEqual(detect(bars,step=.01,quote=2.15)[0]['retest_tests'],0)

    def test_rebound_threshold_boundary(self):
        bars=self.bars()[:10];bars[-1]['close']=2.121
        self.assertEqual(detect(bars,step=.01,quote=2.15)[0]['retest_tests'],1)
        bars[-1]['close']=2.1209
        self.assertEqual(detect(bars,step=.01,quote=2.15)[0]['retest_tests'],0)

    def test_full_hold_and_local_retest_not_double_counted(self):
        zone=detect(attempts((.96,.96,.96,.96)))[0]
        self.assertEqual(zone['independent_tests'],4)
        self.assertEqual(len({h['trough_time'] for h in zone['holds']}),4)

    def test_later_retests_do_not_rewrite_earlier_sources_or_qualification(self):
        before=detect(self.bars()[:10],step=.01,quote=2.15)[0]
        after=detect(self.bars(),step=.01,quote=2.15)[0]
        self.assertEqual(after['qualified_at'],before['qualified_at'])
        self.assertEqual(after['holds'][:3],before['holds'])


class SupportClient(rallies.WorkflowTests.Client):
    def __init__(self):
        super().__init__();self.bars=attempts()


class SupportWorkflowTests(unittest.TestCase):
    def test_retest_drawings_and_saved_details_keep_exact_lows(self):
        class RetestClient(SupportClient):
            def call(self,name,**args):
                if name=='quote_snapshot':return dict(last_price=2.15,lp_time=START.timestamp(),minmov=1,pricescale=100)
                return super().call(name,**args)
        client=RetestClient();client.bars=FloorRetestTests().bars()
        with tempfile.TemporaryDirectory() as folder:
            client.details_path=Path(folder)/'details.json'
            result=run(client,enabled_types=['support_zone'],now=START+timedelta(minutes=30))
            saved=json.loads(client.details_path.read_text())['NASDAQ:TEST']
        zone=result['levels'][0]
        self.assertEqual((zone['independent_tests'],zone['retest_tests']),(4,2))
        self.assertEqual(len(zone['marks']),5)
        self.assertEqual(saved['levels'][0]['holds'],zone['holds'])
        self.assertEqual(saved['levels'][0]['trough_bounds'],dict(low=2.10,high=2.10))
        self.assertEqual(zone['label'],'Support holds · 4 tests · ~$2.10')
        for mark,hold in zip(zone['marks'],zone['holds']):
            self.assertEqual(mark['points'][0]['price'],hold['trough'])
        self.assertEqual((client.resolution,client.session),('5','regular'))

    def test_single_hold_is_omitted_with_two_test_explanation(self):
        client=SupportClient();client.bars=attempts((.96,))
        result=run(client,enabled_types=['support_zone'],now=START+timedelta(minutes=30))
        self.assertFalse(result['levels'])
        self.assertFalse(client.created)
        self.assertIn('two independent confirmed support holds',result['availability']['support_zone'])

    def test_marks_and_explanations_remain_about_holds_after_later_break(self):
        snapshots=[]
        for minute in (5,7,8,10):
            client=SupportClient();client.bars=lifecycle()
            zone=next(z for z in run(client,enabled_types=['support_zone'],now=START+timedelta(minutes=minute))['levels'] if z['independent_tests']==2)
            snapshots.append([{k:v for k,v in m.items() if k!='entity_id'} for m in zone['marks']])
            self.assertEqual(len(zone['marks']),zone['independent_tests']+1)
            self.assertTrue(zone['label'].startswith('Support holds'))
            self.assertNotIn('Current state:',zone['explanation'])
            self.assertIn('where support held at that time',zone['explanation'])
            self.assertNotIn('history',zone)
        self.assertTrue(all(marks==snapshots[0] for marks in snapshots))

    def test_catalog_keeps_preference_key_and_uses_support_holds_name(self):
        from level_catalog import CATALOG
        self.assertEqual(CATALOG['support_zone']['title'],'Support holds')
        self.assertIn('At least two independent',CATALOG['support_zone']['explanation'])

    def test_selected_category_draws_grouped_troughs_and_saves_sources(self):
        client=SupportClient()
        with tempfile.TemporaryDirectory() as folder:
            client.details_path=Path(folder)/'details.json'
            result=run(client,enabled_types=['support_zone','gap'],now=START+timedelta(minutes=30))
            saved=json.loads(client.details_path.read_text())['NASDAQ:TEST']
        zone=next(z for z in result['levels'] if z['kind']=='support_zone')
        self.assertEqual(zone['entity_ids'],[m['entity_id'] for m in zone['marks']])
        self.assertEqual([m['shape'] for m in zone['marks']],['ellipse','ellipse','text'])
        self.assertLess(zone['marks'][-1]['point']['price'],zone['holds'][-1]['trough'])
        for mark,failure in zip(zone['marks'],zone['holds']):
            self.assertEqual(mark['points'][0]['price'],failure['trough'])
            self.assertEqual(mark['points'][0]['time'],failure['trough_time']-120)
            self.assertEqual(json.loads(mark['overrides'])['backgroundColor'],zone['color'])
        self.assertIn('second confirmed rebound at 06:04 ET',zone['explanation'])
        self.assertEqual(zone['thresholds']['minimum_tests'],2)
        self.assertEqual([s['kind'] for s in zone['label_sources']],['support_zone'])
        self.assertNotIn('An actual daily low',zone['explanation'])
        self.assertIn('separate from daily Prior support',zone['explanation'])
        self.assertEqual(saved['support_zones']['status'],'ok')
        self.assertEqual((client.resolution,client.session),('5','regular'))
        self.assertNotIn('manual',client.removed)

    def test_both_detectors_share_a_single_session_fetch(self):
        client=SupportClient()
        result=run(client,enabled_types=['support_zone','failed_rally'],dry_run=True,now=START+timedelta(minutes=30))
        self.assertEqual(sum(n=='data_get_intraday' for n,a in client.calls),1)
        self.assertEqual(result['support_zones']['status'],'ok')
        self.assertEqual(result['failed_rallies']['completed_bars'],result['support_zones']['completed_bars'])
        self.assertFalse(client.created);self.assertFalse(client.removed)

    def test_disabled_support_does_not_run_detector(self):
        with patch('daily_levels.support_zones',side_effect=AssertionError('disabled')):
            result=run(SupportClient(),enabled_types=['failed_rally'],now=START+timedelta(minutes=30))
        self.assertEqual(result['support_zones']['status'],'disabled')

    def test_fallback_date_and_empty_unsupported_omission_reasons(self):
        result=run(SupportClient(),enabled_types=['support_zone'],now=START+timedelta(days=2))
        self.assertTrue(result['levels'][0]['label'].endswith(' 10/09'))
        self.assertIn('10/09/2026 session',result['levels'][0]['explanation'])
        client=SupportClient();client.bars=[]
        result=run(client,enabled_types=['support_zone'],now=START)
        self.assertIn('No completed one-minute',result['availability']['support_zone'])
        class Unsupported(SupportClient):
            def call(self,n,**args):
                if n=='session_snapshot':return dict(session=self.session,premarket_supported=False)
                return super().call(n,**args)
        result=run(Unsupported(),enabled_types=['support_zone'],now=START)
        self.assertIn('US stocks',result['availability']['support_zone'])

    def test_draw_failure_rolls_back_ovals_keeps_previous_and_restores(self):
        class Broken(SupportClient):
            def call(self,n,**args):
                if n=='draw_shape' and args['shape']=='text':raise RuntimeError('label failed')
                return super().call(n,**args)
        client=Broken()
        with self.assertRaisesRegex(RuntimeError,'label failed'):
            run(client,enabled_types=['support_zone'],now=START+timedelta(minutes=30))
        self.assertEqual(client.removed,['0','1'])
        self.assertEqual((client.resolution,client.session),('5','regular'))

    def test_clear_removes_all_group_members_preserves_manual_and_timeframe(self):
        class Owned(SupportClient):
            def call(self,n,**args):
                if n=='draw_list':return dict(shapes=[dict(id=x) for x in ['oval1','oval2','label','manual']])
                if n=='draw_get_properties':return dict(properties=dict(text='Manual'))
                if n=='ui_evaluate':return dict(result='url')
                return super().call(n,**args)
        with tempfile.TemporaryDirectory() as folder:
            client=Owned();client.ownership_path=Path(folder)/'owned.json'
            client.ownership_path.write_text(json.dumps({'url|NASDAQ:TEST':['oval1','oval2','label']}))
            result=clear_levels(client)
        self.assertEqual(result['removed'],3)
        self.assertEqual(client.removed,['oval1','oval2','label'])
        self.assertEqual((client.resolution,client.session),('5','regular'))

    def test_inspector_groups_selection_and_identifies_edited_support_marks(self):
        result=run(SupportClient(),enabled_types=['support_zone'],now=START+timedelta(minutes=30))
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
            shapes[0]['points'][0]['price']+=.01
            self.assertIn('support mark',inspect_chart(Inspector())['levels'][0]['explanation'])


if __name__=='__main__':unittest.main()
