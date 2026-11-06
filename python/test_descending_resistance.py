import json
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from ascending_support import confirmed_rallies
from descending_resistance import descending_resistance
from daily_levels import run,clear_levels
from level_inspector import inspect_chart
from level_theme import apply_drawing_theme
from level_styles import drawing_style
from test_pane_client import Fixture
from test_ascending_support import START,candle,series
import test_failed_rallies as rallies


def falling(highs=(1.2,1.16,1.12)):
    bars=[candle(0,1.12,1.12,1.10,1.12)]
    for high in highs:
        minute=len(bars)*5;previous=bars[-1]['close']
        bars.append(candle(minute,previous,high,min(previous,high-.005),high-.005))
        bars.append(candle(minute+5,high-.005,high-.005,high-.08,high-.07))
    return bars


def detect(bars,minute=60,quote=1.08,tick=.0001):
    return descending_resistance(bars,quote,START+timedelta(minutes=minute),lambda p:tick)


class DetectorTests(unittest.TestCase):
    def test_two_lower_highs_create_provisional_ray_after_second_rejection_close(self):
        bars=falling()[:5]
        self.assertFalse(detect(bars,minute=24))
        z=detect(bars,minute=25)[0]
        self.assertEqual(z['state'],'provisional')
        self.assertEqual([a['price'] for a in z['anchors']],[1.2,1.16])
        self.assertEqual(z['qualified_at'],(START+timedelta(minutes=25)).timestamp())
        self.assertLess(z['slope_per_bar'],0)
        self.assertEqual(z['kind'],'descending_resistance')
        self.assertIn('minimum_rejection',z['thresholds'])
        bars[-1]['complete']=False
        self.assertFalse(detect(bars))

    def test_third_rejection_strengthens_without_moving_original_anchors(self):
        before=detect(falling()[:5])[0];after=detect(falling())[0]
        self.assertEqual(after['state'],'confirmed')
        self.assertEqual(after['anchors'],before['anchors'])
        self.assertEqual(after['independent_tests'],3)
        self.assertEqual(after['qualified_at'],before['qualified_at'])
        self.assertEqual(after['confirmed_at'],(START+timedelta(minutes=35)).timestamp())

    def test_one_rejection_equal_highs_and_flat_noise_cannot_qualify(self):
        for highs in ((1.2,),(1.2,1.2),(1.2,1.198),(1.2,1.24)):
            self.assertFalse(detect(falling(highs)))

    def test_wick_and_single_close_above_do_not_break_two_closes_do(self):
        bars=falling()
        wick=candle(35,1.05,1.35,1.03,1.04)
        self.assertEqual(detect(bars+[wick])[0]['state'],'confirmed')
        one=candle(35,1.05,1.11,1.05,1.10)
        two=candle(40,1.10,1.11,1.09,1.10)
        self.assertNotEqual(detect(bars+[one])[0]['state'],'broken')
        broken=detect(bars+[one,two])[0]
        self.assertEqual(broken['state'],'broken')
        self.assertEqual(broken['broken_at'],(START+timedelta(minutes=45)).timestamp())
        self.assertEqual(broken['anchors'],detect(bars)[0]['anchors'])
        self.assertIn('Broken descending resistance',broken['display_text'])
        # Returning below the ray does not erase its historical break or add
        # a rejection that happened after the break to the original evidence.
        later=candle(45,1.10,1.10,.89,.90)
        after=detect(bars+[one,two,later])[0]
        self.assertEqual(after['broken_at'],broken['broken_at'])
        self.assertEqual(after['touches'],broken['touches'])

    def test_forming_or_future_second_close_cannot_confirm_break(self):
        bars=falling()+[candle(35,1.05,1.11,1.05,1.10),candle(40,1.10,1.11,1.09,1.10)]
        self.assertNotEqual(detect(bars,minute=44)[0]['state'],'broken')
        bars[-1]['complete']=False
        self.assertNotEqual(detect(bars)[0]['state'],'broken')

    def test_missing_bars_separate_anchors_and_interrupt_break_counting(self):
        bars=falling()[:5]
        for b in bars[3:]:b['time']+=300
        self.assertFalse(detect(bars))
        bars=falling()+[candle(35,1.05,1.11,1.05,1.10),candle(45,1.10,1.11,1.09,1.10)]
        self.assertNotEqual(detect(bars)[0]['state'],'broken')

    def test_two_closes_above_during_formation_invalidate_fit(self):
        bars=falling()[:5];known=confirmed_rallies(bars,lambda p:.0001)
        bars[2].update(open=1.3,high=1.4,low=1.3,close=1.35)
        bars[3].update(open=1.35,high=1.4,low=1.3,close=1.36)
        with patch('ascending_support.confirmed_rallies',return_value=known):
            self.assertFalse(detect(bars))

    def test_zero_missing_or_tiny_volume_cannot_establish_rays(self):
        for volume in (0,None,10,100):
            self.assertFalse(detect([dict(b,volume=volume) for b in falling()]))
        with self.assertRaises(ValueError):detect([dict(b,volume=-1) for b in falling()])
        bars=falling();bars[2]['volume']=1
        self.assertEqual(detect(bars)[0]['anchors'][0]['price'],1.16)

    def test_per_minute_activity_and_frozen_volume_evidence(self):
        before=detect(falling(),minute=25)[0]
        after=detect(falling()+[candle(35,1.05,1.06,1.02,1.04,10000000)])[0]
        self.assertEqual(before['anchors'],after['anchors'])
        self.assertEqual(after['anchors'][0]['volume']['reaction']['shares_per_minute'],2000)
        self.assertEqual(after['anchors'][0]['volume']['bar_seconds'],300)

    def test_only_one_nearby_ray_is_selected(self):
        self.assertEqual(len(detect(falling())),1)
        self.assertFalse(detect(falling(),quote=3))
        self.assertFalse(detect([dict(b,time=b['time']-86400) for b in falling()]))
        with self.assertRaises(ValueError):detect(falling(),tick=0)

    def test_style_is_orange_intact_green_broken_and_theme_aware(self):
        for state,color,pattern in (('provisional','#d18b32',1),('confirmed','#d18b32',0),('broken','#66bb6a',2)):
            for quote in (.5,2):
                z=dict(kind='descending_resistance',price=1.1,state=state)
                dark=drawing_style(z,quote);light=drawing_style(z,quote,theme='light')
                self.assertEqual((dark['color'],dark['linestyle'],dark['linewidth']),(color,pattern,1))
                self.assertNotEqual(dark['color'],light['color'])
                self.assertEqual(light['linestyle'],pattern)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.client=Fixture();self.client.details_path=Path(self.client.tmp.name)/'details.json'
        bars=falling()
        self.client.send(op='intraday',bars=[[b[k] for k in ('time','open','high','low','close','volume')] for b in bars],end=True)
        self.reference=patch('daily_levels.read_reference',return_value=dict(price=1.08,time=START.timestamp(),source='last_price',tick_size=.0001))
        self.reference.start()
        self.client.call('ui_evaluate',expression='(()=>{window.TradingViewApi._activeChartWidgetWV.value().selection=()=>({allItems:()=>[]});return true})()')
    def tearDown(self):
        self.reference.stop();self.client.close()
    def draw(self,**kwargs):
        return run(self.client,enabled_types=['descending_resistance'],now=START+timedelta(minutes=40),**kwargs)

    def test_native_ray_and_saved_inspector_explanation_use_actual_highs(self):
        before=self.client.send(op='snapshot');result=self.draw();z=result['levels'][0]
        after=self.client.send(op='snapshot')
        shape=dict(after['panes'][0]['shapes'])[z['entity_id']]
        self.assertEqual(shape['points'],[dict(price=a['price'],time=a['time']) for a in z['anchors']])
        self.assertTrue(shape['props']['extendRight']);self.assertFalse(shape['props']['extendLeft'])
        self.assertEqual(shape['props']['linecolor'],'#d18b32')
        self.assertIn('actual wick high $1.20',z['explanation'])
        self.assertIn('rejection became confirmed',z['explanation'])
        self.assertIn('Volume evidence',z['explanation'])
        self.assertNotIn('You edited',inspect_chart(self.client)['levels'][0]['explanation'])
        self.assertEqual(after['panes'][1],before['panes'][1])
        self.assertEqual((after['panes'][0]['resolution'],after['panes'][0]['session']),('5','regular'))
        self.assertEqual(clear_levels(self.client)['removed'],1)

    def test_restyle_round_trip_preserves_ids_text_anchor_prices_and_times(self):
        self.draw();before=self.client.send(op='snapshot')['panes'][0]['shapes']
        apply_drawing_theme(self.client,'light');after=self.client.send(op='snapshot')['panes'][0]['shapes']
        self.assertEqual(after[0][1]['props']['linecolor'],'#ad5d00')
        self.assertEqual(after[0][1]['points'],before[0][1]['points'])
        self.assertEqual(after[0][0],before[0][0])
        self.assertEqual(after[0][1]['props']['text'],before[0][1]['props']['text'])
        apply_drawing_theme(self.client,'dark')
        self.assertEqual(self.client.send(op='snapshot')['panes'][0]['shapes'],before)

    def test_edited_point_produces_anchor_edit_notice(self):
        z=self.draw()['levels'][0]
        self.client.call('ui_evaluate',expression=f"window.TradingViewApi._chartWidgetCollection.getAll()[0].shapes.get('{z['entity_id']}').points[1].price+=.01")
        text=inspect_chart(self.client)['levels'][0]['explanation']
        self.assertIn('edited or removed a trendline',text);self.assertIn('anchors',text)

    def test_selection_change_rolls_back_in_original_pane(self):
        before=self.client.send(op='snapshot')['panes'][1]
        self.client.send(op='switchDuringCreate')
        with self.assertRaisesRegex(RuntimeError,'Selected chart pane changed'):self.draw()
        after=self.client.send(op='snapshot')
        self.assertEqual(after['panes'][1],before);self.assertFalse(after['panes'][0]['shapes'])
        self.assertEqual((after['panes'][0]['resolution'],after['panes'][0]['session']),('5','regular'))

    def test_shared_read_fetches_native_five_minute_history_once_for_both_categories(self):
        class Both(rallies.WorkflowTests.Client):
            def call(self,name,**args):
                if name=='data_get_intraday' and args.get('timeframe')=='5':
                    self.calls.append((name,args))
                    return dict(bars=falling()+[dict(b,time=b['time']+2100) for b in series()])
                return super().call(name,**args)
        client=Both()
        result=run(client,enabled_types=['ascending_support','descending_resistance'],now=START+timedelta(minutes=80),dry_run=True)
        self.assertEqual({z['kind'] for z in result['levels']},{'ascending_support','descending_resistance'})
        self.assertEqual(len([1 for n,a in client.calls if n=='data_get_intraday' and a.get('timeframe')=='5']),1)
        self.assertEqual((client.resolution,client.session),('5','regular'))

    def test_disabled_categories_fetch_no_five_minute_history(self):
        client=rallies.WorkflowTests.Client()
        run(client,enabled_types=['failed_rally'],now=START+timedelta(minutes=40))
        self.assertFalse(any(a.get('timeframe')=='5' for n,a in client.calls if n=='data_get_intraday'))

    def test_latest_actual_historical_session_is_dated_once(self):
        result=run(self.client,enabled_types=['descending_resistance'],now=START+timedelta(days=2))
        z=result['levels'][0]
        self.assertEqual(z['label'].count('10/09'),1)
        self.assertTrue(result['descending_resistance']['historical'])


if __name__=='__main__':unittest.main()
