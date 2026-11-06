import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from daily_levels import run, clear_levels, spaced_levels, label_sources, drawing_label, save_details, read_session_levels
from level_explanations import explain_level
from level_inspector import inspect_chart
from reference_levels import explicit_references, regular_day_levels, PREVIOUS_TYPES
from test_daily_levels import Fake, bar

NY=ZoneInfo('America/New_York')
def at(day,clock='10:00'):
    return datetime.fromisoformat(day+'T'+clock).replace(tzinfo=NY)
def candle(day, low=9, high=11, clock='09:30'):
    return bar(at(day,clock).timestamp(),low,high)

class References(unittest.TestCase):
    def test_active_extended_trade_wins_refreshed_regular_close_clocks(self):
        from daily_levels import latest_quote
        for session in ('pre_market','post_market'):
            quote=latest_quote(dict(last_price=1.41,lp_time=300,regular_close_time=300,rtc=1.29,rtc_time=299,session=session))
            self.assertEqual(quote['price'],1.29)
            self.assertEqual(quote['time'],299)
            self.assertEqual(quote['source'],'rtc')

    def test_redundant_round_and_sma_drawings_are_not_selectable(self):
        from level_catalog import LEVEL_TYPES, GROUPS
        self.assertEqual(len(LEVEL_TYPES),21)
        self.assertEqual([g['id'] for g in GROUPS],['structure','trendlines','sessions','events'])
        for kind in ('round_number','daily_sma200'):
            with self.assertRaises(ValueError):run(Fake(),enabled_types=[kind])

    def test_previous_session_excludes_completed_today_even_after_close(self):
        bars=[candle('2026-10-02',8,12),candle('2026-10-05',9,11),candle('2026-10-06',7,13)]
        levels,_=explicit_references(bars,10,PREVIOUS_TYPES,at('2026-10-06','17:00'))
        self.assertEqual([x['price'] for x in levels],[11,9,10,9])
        self.assertTrue(all(x['time']==bars[-2]['time'] for x in levels))
    def test_previous_open_uses_actual_prior_session_open_and_provenance(self):
        source=dict(candle('2026-10-16',8,12),open=9.25)
        levels,_=explicit_references([source,candle('2026-10-19')],10,{'previous_open'},at('2026-10-19'))
        self.assertEqual(levels[0]['price'],9.25)
        self.assertEqual(drawing_label(levels[0],at('2026-10-19')),'Prev open 10/16')
        self.assertIn('opening price',explain_level(levels[0],10,label_sources(levels[0])))
    def test_previous_open_alone_can_be_drawn_and_cleared(self):
        client=Fake();result=run(client,enabled_types=['previous_open'])
        self.assertEqual(len(result['levels']),1)
        self.assertEqual(result['levels'][0]['kind'],'previous_open')
        self.assertEqual(result['levels'][0]['linestyle'],2)
        self.assertEqual((client.resolution,client.session),('5','regular'))
        self.assertEqual(clear_levels(client)['removed'],1)
    def test_weekend_uses_last_loaded_session_not_calendar_yesterday(self):
        source=candle('2026-10-02')
        levels,_=explicit_references([source],10,{'previous_high'},at('2026-10-05'))
        self.assertEqual(levels[0]['time'],source['time'])
    def test_unavailable_and_far_reference_has_reason(self):
        levels,reasons=explicit_references([],10,PREVIOUS_TYPES,at('2026-10-06'))
        self.assertFalse(levels);self.assertEqual(set(reasons),PREVIOUS_TYPES)
        levels,reasons=explicit_references([candle('2026-10-05',1,2)],10,{'previous_high'},at('2026-10-06'))
        self.assertFalse(levels);self.assertIn('outside',reasons['previous_high'])
    def test_invalid_quotes_and_reference_bars_rejected(self):
        for price in (0,-1,float('nan'),float('inf')):
            with self.assertRaises(ValueError):explicit_references([],price,{'previous_high'},at('2026-10-06'))
        with self.assertRaises(ValueError):explicit_references([bar(2,9,11),bar(1,9,11)],10,PREVIOUS_TYPES,at('2026-10-06'))
    def test_disabled_reference_types_do_not_leak(self):
        levels,_=explicit_references([candle('2026-10-05')],10,{'previous_low'},at('2026-10-06'))
        self.assertEqual([x['kind'] for x in levels],['previous_low'])
    def test_day_extremes_clip_premarket_postmarket_future_bars_and_include_forming(self):
        bars=[candle('2026-10-06',1,30,'09:25'),candle('2026-10-06',9,11),candle('2026-10-06',8,12,'10:00'),candle('2026-10-06',1,40,'10:05'),candle('2026-10-06',1,50,'16:00')]
        self.assertEqual([x['price'] for x in regular_day_levels(bars,at('2026-10-06','10:02'))],[12,8])
    def test_regular_day_respects_new_york_dst_and_no_previous_day_substitute(self):
        for date in ('2026-01-05','2026-07-06'):
            self.assertEqual([x['price'] for x in regular_day_levels([candle(date)],at(date))],[11,9])
        self.assertFalse(regular_day_levels([candle('2026-10-02')],at('2026-10-03')))
    def test_pm_and_day_read_provider_regular_session_to_exclude_early_close_postmarket(self):
        class Sessions(Fake):
            def call(self,name,**args):
                if name=='data_get_ohlcv':
                    return {'bars':[candle('2026-11-27',8,12,'09:30')] if self.session=='regular' else [candle('2026-11-27',7,13,'08:00'),candle('2026-11-27',1,40,'14:00')]}
                return super().call(name,**args)
        client=Sessions()
        pm,day=read_session_levels(client,{'session':'regular','premarket_supported':True},at('2026-11-27','17:00'),{'premarket_high','day_high'})
        self.assertEqual([x['price'] for x in pm['levels']],[13]);self.assertEqual([x['price'] for x in day['levels']],[12])
    def test_previous_only_allows_one_daily_candle_and_restores_session(self):
        class Previous(Fake):
            def call(self,name,**args):
                if name=='data_get_ohlcv':return {'bars':[candle('2026-10-05',4,6)]}
                return super().call(name,**args)
        client=Previous();client.session='extended'
        result=run(client,enabled_types=['previous_close'],now=at('2026-10-06'))
        self.assertEqual(result['levels'][0]['price'],5);self.assertEqual(client.session,'extended')
    def test_explanation_preserves_merged_prices_and_dates(self):
        levels=spaced_levels([dict(price=10,time=candle('2026-10-05')['time'],kind='previous_high',description='Prev high'),dict(price=10.01,time=at('2026-10-06').timestamp(),kind='day_high',description='Day high')])
        text=explain_level(levels[0],9.5,label_sources(levels[0]))
        self.assertIn('$10.01',text);self.assertIn('10/05/2026',text);self.assertIn('not averaged',text);self.assertIn('regular session',text)
    def test_snapshot_write_preserves_other_pane_and_clear_removes_only_current_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'details.json';save_details(path,'pane:1',{'levels':[1]});save_details(path,'pane:2',{'levels':[2]});save_details(path,'pane:2',None)
            self.assertEqual(json.loads(path.read_text()),{'pane:1':{'levels':[1]}})
    def test_dry_run_does_not_write_explanations_successful_draw_and_clear_do(self):
        with tempfile.TemporaryDirectory() as temp:
            client=Fake();client.details_path=Path(temp)/'details.json'
            run(client,dry_run=True,enabled_types=['gap']);self.assertFalse(client.details_path.exists())
            result=run(client,enabled_types=['gap']);self.assertEqual(json.loads(client.details_path.read_text())['NASDAQ:TEST']['levels'],result['levels'])
            clear_levels(client);self.assertEqual(json.loads(client.details_path.read_text()),{})
    def test_failure_preserves_previous_explanation_snapshot(self):
        with tempfile.TemporaryDirectory() as temp:
            client=Fake(True);client.details_path=Path(temp)/'details.json';save_details(client.details_path,'NASDAQ:TEST',{'levels':['old']})
            with self.assertRaises(RuntimeError):run(client,enabled_types=['gap'])
            self.assertEqual(json.loads(client.details_path.read_text())['NASDAQ:TEST']['levels'],['old'])

class Inspector(unittest.TestCase):
    def check_snapshot(self, moved=False, deleted=False, pane='2'):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            scope='chart|NASDAQ:TEST|pane:2'
            details=root/'details.json';owned=root/'owned.json'
            save_details(details,scope,{'levels':[dict(entity_id='owned',price=10,label='Prev high 10/05',explanation='Original source',color='#66bb6a')],'reference':{'price':11}})
            owned.write_text(json.dumps({scope:['owned']}))
            chart=dict(url='chart',symbol='NASDAQ:TEST',pane={'pane_id':pane},selected_ids=['manual','owned'],shapes=[] if deleted else [dict(id='manual',price=8,text='Manual',color='#ffffff'),dict(id='owned',price=12 if moved else 10,text='Prev high 10/05',color='#66bb6a')])
            class ReadOnly:
                details_path=details;ownership_path=owned
                def call(self,name,**args):
                    if name!='ui_evaluate':raise AssertionError('Observer mutated chart')
                    return {'result':chart}
            return inspect_chart(ReadOnly())
    def test_selected_owned_line_shows_snapshot_and_excludes_manual(self):
        result=self.check_snapshot();self.assertEqual(result['selected_id'],'owned');self.assertEqual(len(result['levels']),1);self.assertEqual(result['levels'][0]['explanation'],'Original source')
    def test_manual_move_is_explicit_and_uses_live_price(self):
        level=self.check_snapshot(moved=True)['levels'][0];self.assertEqual(level['price'],12);self.assertIn('You edited',level['explanation']);self.assertIn('original $10.00',level['explanation'])
    def test_deleted_line_removed_from_inspector(self):
        self.assertEqual(self.check_snapshot(deleted=True)['levels'],[])
    def test_same_symbol_other_pane_does_not_inherit_saved_metadata(self):
        self.assertEqual(self.check_snapshot(pane='3')['levels'],[])
