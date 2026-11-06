import copy
import json
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from ascending_support import ascending_support, completed_five_minutes, confirmed_pullbacks
from daily_levels import run, clear_levels
from level_inspector import inspect_chart
from level_theme import apply_drawing_theme
from level_styles import drawing_style
from test_pane_client import Fixture
import test_failed_rallies as rallies

START=datetime(2026,10,9,6,tzinfo=ZoneInfo('America/New_York'))


def candle(minute,opened,high,low,close,volume=10000):
    return dict(time=(START+timedelta(minutes=minute)).timestamp(),open=opened,high=high,low=low,close=close,volume=volume)


def series(lows=(1,1.04,1.08)):
    bars=[candle(0,1.08,1.10,1.08,1.08)]
    for low in lows:
        minute=len(bars)*5;previous=bars[-1]['close']
        bars.append(candle(minute,previous,max(previous,low+.005),low,low+.005))
        bars.append(candle(minute+5,low+.005,low+.08,low+.005,low+.07))
    return bars


def detect(bars,minute=60,quote=1.12,tick=.0001):
    return ascending_support(bars,quote,START+timedelta(minutes=minute),lambda p:tick)


class DetectorTests(unittest.TestCase):
    def test_two_pullbacks_make_provisional_line_only_after_second_close(self):
        bars=series()[:5]
        self.assertFalse(detect(bars,minute=24))
        z=detect(bars,minute=25)[0]
        self.assertEqual(z['state'],'provisional')
        self.assertEqual([a['price'] for a in z['anchors']],[1,1.04])
        self.assertEqual(z['qualified_at'],(START+timedelta(minutes=25)).timestamp())
        self.assertIn('provisional',z['display_text'])
        bars[-1]['complete']=False
        self.assertFalse(detect(bars))

    def test_third_independent_reaction_strengthens_without_refitting(self):
        before=detect(series()[:5])[0];after=detect(series())[0]
        self.assertEqual(after['state'],'confirmed')
        self.assertEqual(after['anchors'],before['anchors'])
        self.assertEqual(after['qualified_at'],before['qualified_at'])
        self.assertEqual(after['independent_tests'],3)
        self.assertEqual(after['confirmed_at'],(START+timedelta(minutes=35)).timestamp())
        self.assertEqual(after['slope_per_bar'],before['slope_per_bar'])

    def test_single_reaction_equal_lows_and_nearly_flat_noise_are_omitted(self):
        for lows in ((1,),(1,1),(1,1.004),(1,.98)):
            self.assertFalse(detect(series(lows)))

    def test_repeated_touches_in_one_drop_do_not_count_as_new_anchors(self):
        bars=series()[:2]+[candle(10,1.005,1.008,1,1.006),candle(15,1.006,1.009,1,1.007)]
        self.assertFalse(detect(bars))

    def test_single_wick_and_single_close_do_not_break_but_two_closes_do(self):
        bars=series()
        wick=candle(35,1.15,1.17,.95,1.16)
        self.assertEqual(detect(bars+[wick])[0]['state'],'confirmed')
        one=candle(35,1.15,1.15,1.09,1.10)
        two=candle(40,1.10,1.11,1.09,1.10)
        self.assertNotEqual(detect(bars+[one])[0]['state'],'broken')
        broken=detect(bars+[one,two])[0]
        self.assertEqual(broken['state'],'broken')
        self.assertEqual(broken['broken_at'],(START+timedelta(minutes=45)).timestamp())
        self.assertIn('Broken ascending support',broken['display_text'])
        self.assertEqual(broken['anchors'],detect(bars)[0]['anchors'])
        later=candle(45,1.10,1.3,1.10,1.25)
        still=detect(bars+[one,two,later])[0]
        self.assertEqual(still['broken_at'],broken['broken_at'])
        self.assertEqual(still['touches'],broken['touches'])

    def test_forming_second_break_close_cannot_break(self):
        bars=series()+[candle(35,1.15,1.15,1.09,1.1),candle(40,1.1,1.11,1.09,1.1)]
        bars[-1]['complete']=False
        self.assertNotEqual(detect(bars)[0]['state'],'broken')
        self.assertNotEqual(detect(bars,minute=44)[0]['state'],'broken')

    def test_gaps_separate_anchors_and_reset_consecutive_breaks(self):
        bars=series()[:5]
        for b in bars[3:]:b['time']+=300
        self.assertFalse(detect(bars))
        bars=series()+[candle(35,1.15,1.15,1.09,1.1),candle(45,1.1,1.11,1.09,1.1)]
        self.assertNotEqual(detect(bars)[0]['state'],'broken')

    def test_formation_that_cuts_through_two_completed_closes_is_rejected(self):
        # Test the fit independently of swing discovery: the known low prices
        # would project above two intervening candle closes.
        bars=series()[:5]
        holds=confirmed_pullbacks(bars,lambda p:.0001)
        bars[2].update(open=.9,high=.95,low=.89,close=.91)
        bars[3].update(open=.91,high=.96,low=.90,close=.92)
        with patch('ascending_support.confirmed_pullbacks',return_value=holds):
            self.assertFalse(detect(bars))

    def test_zero_missing_and_thin_reaction_volume_cannot_supply_anchors(self):
        for volume in (None,0,10,100):
            self.assertFalse(detect([dict(b,volume=volume) for b in series()]))
        bars=series();bars[2]['volume']=1
        # The next two real reactions remain eligible, but the illiquid first
        # rebound cannot be an anchor in their line.
        z=detect(bars)[0]
        self.assertEqual(z['anchors'][0]['price'],1.04)

    def test_five_minute_volume_is_normalized_per_minute(self):
        z=detect(series())[0]
        v=z['touches'][0]['volume']
        self.assertEqual(v['bar_seconds'],300)
        self.assertEqual(v['reaction']['shares_per_minute'],2000)
        self.assertEqual(v['reversal']['shares_per_minute'],2000)

    def test_future_data_cannot_rewrite_anchor_evidence(self):
        before=detect(series(),minute=25)[0]
        bars=series()+[candle(35,1.15,1.17,1.14,1.16,10000000)]
        after=detect(bars,minute=40)[0]
        self.assertEqual(before['anchors'],after['anchors'])
        self.assertEqual(before['qualified_at'],after['qualified_at'])

    def test_only_one_nearby_ray_is_returned(self):
        zones=detect(series())
        self.assertEqual(len(zones),1)
        self.assertFalse(detect(series(),quote=3))

    def test_bad_data_ticks_and_other_sessions_do_not_produce_lines(self):
        for bars in (list(reversed(series())),[dict(series()[0],time=START.timestamp()+1)],
                     [dict(series()[0],low=-1)],[dict(series()[0],volume=-1)]):
            with self.assertRaises(ValueError):detect(bars)
        with self.assertRaises(ValueError):detect(series(),tick=0)
        self.assertFalse(detect([dict(b,time=b['time']-86400) for b in series()]))

    def test_styles_preserve_state_across_themes_and_quote_sides(self):
        for state,color,pattern in (('provisional','#66bb6a',1),('confirmed','#66bb6a',0),('broken','#d18b32',2)):
            for quote in (.5,2):
                z=dict(kind='ascending_support',price=1.1,state=state)
                dark=drawing_style(z,quote);light=drawing_style(z,quote,theme='light')
                self.assertEqual((dark['color'],dark['linestyle'],dark['linewidth']),(color,pattern,1))
                self.assertNotEqual(light['color'],dark['color'])
                self.assertEqual(light['linestyle'],pattern)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.client=Fixture()
        self.client.details_path=Path(self.client.tmp.name)/'details.json'
        bars=series()
        self.client.send(op='intraday',bars=[[b[k] for k in ('time','open','high','low','close','volume')] for b in bars],end=True)
        self.reference=patch('daily_levels.read_reference',return_value=dict(price=1.12,time=START.timestamp(),source='last_price',tick_size=.0001))
        self.reference.start()
        self.client.call('ui_evaluate',expression='(()=>{window.TradingViewApi._activeChartWidgetWV.value().selection=()=>({allItems:()=>[]});return true})()')
    def tearDown(self):
        self.reference.stop();self.client.close()
    def draw(self,**kwargs):
        return run(self.client,enabled_types=['ascending_support'],now=START+timedelta(minutes=40),**kwargs)

    def test_native_multipoint_ray_is_owned_explained_selected_and_clearable(self):
        before=self.client.send(op='snapshot');result=self.draw();after=self.client.send(op='snapshot')
        z=result['levels'][0];self.assertEqual(z['kind'],'ascending_support')
        shape=dict(after['panes'][0]['shapes'])[z['entity_id']]
        self.assertEqual(shape['points'],[dict(time=a['time'],price=a['price']) for a in z['anchors']])
        self.assertTrue(shape['props']['extendRight']);self.assertFalse(shape['props']['extendLeft'])
        self.assertEqual(shape['props']['linewidth'],1)
        self.assertIn('Anchor 1',z['explanation']);self.assertIn('Volume evidence',z['explanation'])
        self.assertIn('25%',z['explanation'])
        self.assertEqual(inspect_chart(self.client)['levels'][0]['entity_id'],z['entity_id'])
        self.assertNotIn('You edited',inspect_chart(self.client)['levels'][0]['explanation'])
        self.assertEqual(after['panes'][1],before['panes'][1])
        self.assertEqual((after['panes'][0]['resolution'],after['panes'][0]['session']),('5','regular'))
        self.assertEqual(clear_levels(self.client)['removed'],1)

    def test_theme_restyles_ray_without_moving_anchors_or_changing_text(self):
        self.draw();before=self.client.send(op='snapshot')['panes'][0]['shapes']
        apply_drawing_theme(self.client,'light')
        after=self.client.send(op='snapshot')['panes'][0]['shapes']
        self.assertEqual(before[0][0],after[0][0]);self.assertEqual(before[0][1]['points'],after[0][1]['points'])
        self.assertEqual(after[0][1]['props']['linecolor'],'#2e8332')
        self.assertEqual(before[0][1]['props']['text'],after[0][1]['props']['text'])
        apply_drawing_theme(self.client,'dark')
        self.assertEqual(self.client.send(op='snapshot')['panes'][0]['shapes'],before)

    def test_manual_point_edits_are_reported_as_anchor_edits(self):
        result=self.draw();eid=result['levels'][0]['entity_id']
        self.client.call('ui_evaluate',expression=f"window.TradingViewApi._chartWidgetCollection.getAll()[0].shapes.get('{eid}').points[1].price+=.01")
        text=inspect_chart(self.client)['levels'][0]['explanation']
        self.assertIn('edited or removed a trendline',text);self.assertIn('anchors',text)

    def test_selection_change_rolls_back_and_does_not_redirect(self):
        before=self.client.send(op='snapshot')['panes'][1]
        self.client.send(op='switchDuringCreate')
        with self.assertRaisesRegex(RuntimeError,'Selected chart pane changed'):self.draw()
        after=self.client.send(op='snapshot')
        self.assertEqual(after['panes'][1],before)
        self.assertFalse(after['panes'][0]['shapes'])
        self.assertEqual((after['panes'][0]['resolution'],after['panes'][0]['session']),('5','regular'))

    def test_mixed_intraday_marks_use_their_native_drawing_intervals(self):
        class Mixed(rallies.WorkflowTests.Client):
            def __init__(self):super().__init__();self.draw_intervals=[]
            def call(self,name,**args):
                if name=='data_get_intraday':
                    bars=series() if args.get('timeframe')=='5' else rallies.attempts()
                    return dict(bars=[b for b in bars if args['start']<=b['time']<args['end']])
                if name=='draw_shape':self.draw_intervals.append((args['shape'],self.resolution))
                return super().call(name,**args)
        client=Mixed()
        result=run(client,enabled_types=['failed_rally','ascending_support'],now=START+timedelta(minutes=40))
        self.assertEqual({z['kind'] for z in result['levels']},{'failed_rally','ascending_support'})
        self.assertTrue(all(resolution==('5' if shape=='trend_line' else '1') for shape,resolution in client.draw_intervals))
        self.assertEqual((client.resolution,client.session),('5','regular'))

    def test_older_actual_session_is_dated_once(self):
        result=run(self.client,enabled_types=['ascending_support'],now=START+timedelta(days=2))
        z=result['levels'][0]
        self.assertTrue(result['ascending_support']['historical'])
        self.assertEqual(z['session_date'],'2026-10-09')
        self.assertEqual(z['label'].count('10/09'),1)

    def test_disabled_category_does_not_fetch_its_five_minute_history(self):
        client=rallies.WorkflowTests.Client()
        run(client,enabled_types=['support_zone'],now=START+timedelta(minutes=40))
        self.assertFalse(any(n=='data_get_intraday' and a.get('timeframe')=='5' for n,a in client.calls))

    def test_dry_run_changes_no_drawings_and_preserves_original_interval(self):
        before=self.client.send(op='snapshot');result=self.draw(dry_run=True)
        after=self.client.send(op='snapshot')
        self.assertTrue(result['levels'])
        self.assertEqual(before['panes'][0]['shapes'],after['panes'][0]['shapes'])
        self.assertEqual(after['panes'][0]['resolution'],'5')


if __name__=='__main__':unittest.main()
