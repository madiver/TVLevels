import unittest
from unittest.mock import patch
from daily_levels import analyze, run, clear_levels, candle_windows, historical_peaks, role_reversal_levels, drawing_label, drawing_color, latest_quote, read_reference, spaced_levels, price_tick, levels_near, premarket_levels, LEVEL_TYPES
from datetime import datetime
from zoneinfo import ZoneInfo


def bar(t, low, high):
    return dict(time=t, low=low, high=high, open=low, close=(low+high)/2)

class AnalysisTests(unittest.TestCase):
    def mi_gaps(self):
        # MI's historical 4.00-6.42 and 0.90-2.16 gaps, synthetic timestamps.
        return [dict(time=1,open=6.88,high=7.34,low=6.42,close=7.23),
                dict(time=2,open=3.85,high=4,low=2.8,close=3),
                dict(time=3,open=3,high=3.07,low=2.3,close=2.7),
                dict(time=4,open=2.265,high=2.3,low=2.16,close=2.16),
                dict(time=5,open=.9,high=.9,low=.7508,close=.885),
                dict(time=6,open=.89,high=.894,low=.73,close=.894)]

    def test_mi_gap_surrounding_live_quote_replaces_lower_daily_close_gap(self):
        levels=analyze(self.mi_gaps(),current_price=5.5,enabled_types=['gap'])
        self.assertEqual([x['price'] for x in levels],[4,6.42])
        self.assertEqual([drawing_color(x,5.5) for x in levels],['#66bb6a','#d18b32'])

    def test_gap_selection_moves_up_when_price_passes_lower_corridor(self):
        lower=analyze(self.mi_gaps(),current_price=.85,enabled_types=['gap'])
        upper=analyze(self.mi_gaps(),current_price=2.5,enabled_types=['gap'])
        self.assertEqual([x['price'] for x in lower],[.9,2.16])
        self.assertEqual([x['price'] for x in upper],[4,6.42])

    def test_nearest_crossed_gap_keeps_historical_context_when_none_is_above(self):
        levels=analyze(self.mi_gaps(),current_price=7.5,enabled_types=['gap'])
        self.assertEqual([x['price'] for x in levels],[4,6.42])

    def test_gap_partial_fill_and_full_fill(self):
        bars = [bar(1, 8, 10), bar(2, 4, 5), bar(3, 4, 6)]
        gaps = [x['price'] for x in analyze(bars) if x['kind']=='gap']
        self.assertEqual(gaps, [6, 8])
        filled=analyze(bars+[bar(4, 5, 9)],enabled_types=['gap'])
        self.assertEqual([x['price'] for x in filled],[5,8])
        self.assertTrue(all(x['corridor']['state']=='filled_recent' for x in filled))
        self.assertTrue(all('Filled gap' in drawing_label(x) for x in filled))

    def test_minor_old_high_invalidated_by_later_wick(self):
        bars = [bar(1, 8.5, 9.8), bar(2, 8.5, 10), bar(3, 8, 9.5), bar(4, 8, 10.1), bar(5, 8, 9)]
        prices = [x['price'] for x in analyze(bars) if x['kind']=='resistance']
        self.assertNotIn(10, prices)
        self.assertIn(10.1, prices)

    def test_selected_corridor_excludes_irrelevant_extremes(self):
        bars = [bar(1,8.2,14.082), bar(2,5.75,7.33), bar(3,5.42,6.6),
                bar(4,4.7,5.5), bar(5,5.97,6.38), bar(6,5.3,5.9),
                bar(7,4.18,4.77), bar(8,3.34,4.195), bar(9,3.44,3.85),
                bar(10,4.1901,6), bar(11,4.3798,5.28)]
        bars[-1]['close'] = 4.56
        levels=analyze(bars,enabled_types=LEVEL_TYPES[:6])
        self.assertIn(4.3798,[x['price'] for x in levels])
        self.assertEqual([x['price'] for x in levels if x['price']>4.56][:2],[4.77,5.3])
        self.assertNotIn(14.082,[x['price'] for x in levels])
        self.assertLessEqual(len(levels),9)

    def test_shared_gap_fill_and_window_entry_preserves_both(self):
        bars = [bar(i,9,10) for i in range(1,5)]
        bars += [dict(time=5,open=10,close=6,high=11,low=5),bar(6,3,4),bar(7,3,4.2)]
        levels=analyze(bars,current_price=5.5)
        shared=next(x for x in levels if x['price']==5)
        self.assertEqual(shared['kind'],'gap')
        self.assertIn('Gap fill',drawing_label(shared))
        self.assertIn('Window entry',drawing_label(shared))
        self.assertEqual({c['id'].split(':')[0] for c in shared['corridors']},{'gap','window'})

    def test_exposed_high_is_kept_even_when_older_neighbor_is_higher(self):
        bars=[bar(1,5,12),bar(2,5,10),bar(3,5,9),bar(4,5,8)]
        resistance=[x['price'] for x in analyze(bars) if x['kind']=='resistance']
        self.assertEqual(resistance,[8,9,10,12])

    def test_exposed_low_is_kept_without_local_swing(self):
        bars=[bar(1,1,10),bar(2,2,9),bar(3,3,8),bar(4,4,7)]
        levels=analyze(bars)
        self.assertIn(4,[x['price'] for x in levels if x['kind']=='support'])

    def test_equal_extremes_use_latest_candle(self):
        bars=[bar(1,4,10),bar(2,4,10),bar(3,5,7)]
        resistance=next(x for x in analyze(bars) if x['price']==10)
        self.assertEqual(resistance['time'],2)

    def test_invalid_chronology_rejected(self):
        with self.assertRaises(ValueError):
            analyze([bar(2, 3, 4),bar(1, 3, 4)])

class HistoricalPeakTests(unittest.TestCase):
    def veea(self):
        # VEEA's Sep 14–18 daily prices, with synthetic day indexes.
        return [dict(time=1,open=1.6,high=2.36,low=1.58,close=2.29),
                dict(time=2,open=4.33,high=7.49,low=4.31,close=5.71),
                dict(time=3,open=5.49,high=7.2186,low=5.01,close=6.10),
                dict(time=4,open=7.85,high=8.88,low=4.91,close=5.33),
                dict(time=5,open=5,high=5.25,low=3.8065,close=4.45)]

    def test_veea_old_749_peak_survives_later_888_high(self):
        levels=analyze(self.veea(),current_price=5.7,enabled_types=['resistance'])
        self.assertEqual([x['price'] for x in levels],[7.49,8.88])
        self.assertEqual(levels[0]['origin'],'resistance')
        self.assertEqual(levels[0]['state'],'active')
        self.assertEqual(levels[0]['time'],2)

    def test_minor_high_with_insufficient_rise_is_not_reintroduced(self):
        bars=[bar(1,9,9.9),bar(2,9,10),bar(3,8,9),bar(4,9,12),bar(5,8,9)]
        self.assertNotIn(10,[x['price'] for x in historical_peaks(bars)])

    def test_small_pullback_is_not_reintroduced(self):
        bars=[bar(1,5,6),bar(2,9,10),bar(3,9,9.8),bar(4,9,12),bar(5,8,9)]
        self.assertNotIn(10,[x['price'] for x in historical_peaks(bars)])

    def test_continuing_upward_candle_is_not_a_peak(self):
        bars=[bar(1,4,5),bar(2,5,10),bar(3,4,11),bar(4,4,12),bar(5,4,6)]
        self.assertNotIn(10,[x['price'] for x in historical_peaks(bars)])

    def test_recent_lookback_excludes_older_reclaim_peaks(self):
        bars=self.veea()+[bar(i,3,4) for i in range(6,70)]
        self.assertNotIn(7.49,[x['price'] for x in historical_peaks(bars)])

    def test_crossed_peak_is_retained_for_provisional_retest(self):
        levels=analyze(self.veea(),current_price=7.6,enabled_types=['resistance'])
        self.assertEqual([x['price'] for x in levels],[7.49,8.88])
        self.assertEqual(levels[0]['display_text'],'Retest R')
        self.assertEqual(levels[0]['confirmed_role'],'resistance')

    def test_resistance_checkbox_disables_historical_peaks(self):
        self.assertFalse(any(x['kind']=='resistance' for x in
                             analyze(self.veea(),enabled_types=['support','gap','window'])))

    def test_near_duplicate_old_peak_merges_with_newer_unbroken_high(self):
        bars=self.veea();bars[3].update(open=7,high=7.50)
        levels=analyze(bars,current_price=5.7,enabled_types=['resistance'])
        self.assertEqual([x['price'] for x in levels],[7.50])

    def test_equal_historical_peaks_use_most_recent_source(self):
        bars=[bar(1,3,4),bar(2,4,10),bar(3,4,6),bar(4,7,12),bar(5,4,6),
              bar(6,4,10),bar(7,4,6),bar(8,7,12),bar(9,4,6)]
        levels=analyze(bars,current_price=8,enabled_types=['resistance'])
        self.assertEqual(next(x for x in levels if x['price']==10)['time'],6)

class RoleReversalTests(unittest.TestCase):
    def jagx(self):
        # Actual Sep 24, 25, 28, 29 daily boundaries; synthetic timestamps.
        return [dict(time=1,open=7.03,high=7.72,low=6.0208,close=7.06),
                dict(time=2,open=9.09,high=12.10,low=6.80,close=7.70),
                dict(time=3,open=6.99,high=7.25,low=5.80,close=6.02),
                dict(time=4,open=5.37,high=6.10,low=5,close=5.32)]

    def breakout(self):
        return [dict(time=1,open=9,high=10,low=8,close=9),
                dict(time=2,open=10,high=12,low=6,close=8),
                dict(time=3,open=11,high=14,low=10,close=13)]

    def test_jagx_large_candle_low_survives_without_local_swing(self):
        levels=analyze(self.jagx(),current_price=5.5,enabled_types=['former_support'])
        self.assertEqual([x['price'] for x in levels],[6.8])
        self.assertEqual(levels[0]['kind'],'former_support')
        self.assertEqual(levels[0]['time'],2)

    def test_old_high_becomes_support_after_closing_break(self):
        levels=analyze(self.breakout(),current_price=13.5,enabled_types=['former_resistance'])
        self.assertEqual([x['price'] for x in levels],[12])
        self.assertEqual(levels[0]['kind'],'former_resistance')

    def test_wick_only_break_never_confirms_either_role(self):
        low=self.jagx()[:3];low[-1]['close']=7.1
        high=self.breakout();high[-1]['close']=11
        self.assertEqual(role_reversal_levels(low,5.5),[])
        self.assertEqual(role_reversal_levels(high,13.5),[])

    def test_daily_reclaim_retires_previous_role(self):
        low=self.jagx()+[dict(time=5,open=6,high=8,low=5,close=7)]
        high=self.breakout()+[dict(time=4,open=13,high=14,low=10,close=11)]
        self.assertEqual(role_reversal_levels(low,5.5),[])
        self.assertEqual(role_reversal_levels(high,13.5),[])

    def test_live_price_on_original_side_hides_both_roles(self):
        self.assertEqual(role_reversal_levels(self.jagx(),7),[])
        self.assertEqual(role_reversal_levels(self.breakout(),11),[])

    def test_exact_boundary_is_not_a_closing_break(self):
        low=self.jagx()[:3];low[-1]['close']=6.8
        high=self.breakout();high[-1]['close']=12
        self.assertEqual(role_reversal_levels(low,5.5),[])
        self.assertEqual(role_reversal_levels(high,13.5),[])

    def test_minor_boundary_with_no_reaction_is_not_reintroduced(self):
        bars=[bar(1,10.1,11),bar(2,10,11),bar(3,9,10)]
        self.assertEqual(role_reversal_levels(bars,9.5),[])

    def test_separated_repeated_support_tests_qualify(self):
        bars=[dict(time=1,open=10.5,high=11.2,low=10,close=11.1),
              dict(time=2,open=10.6,high=10.9,low=10.5,close=10.6),
              dict(time=3,open=10.5,high=11.2,low=10.01,close=11.1),
              dict(time=4,open=9.8,high=10,low=9,close=9.5)]
        self.assertEqual([x['price'] for x in role_reversal_levels(bars,9.7)],[10.01])

    def test_lookback_excludes_old_sources(self):
        bars=self.jagx()+[bar(i,4,5.5) for i in range(5,70)]
        self.assertEqual(role_reversal_levels(bars,5),[])

    def test_two_nearest_levels_per_role_bound_the_new_lines(self):
        falling=[bar(1,30,35),bar(2,20,35),bar(3,10,20),bar(4,5,12),bar(5,1,4)]
        rising=[bar(1,1,3),bar(2,1,5),bar(3,1,10),bar(4,2,15),bar(5,17,22)]
        lower=analyze(falling,current_price=3,enabled_types=['former_support'])
        upper=analyze(rising,current_price=20,enabled_types=['former_resistance'])
        self.assertEqual([x['price'] for x in lower],[5,10])
        self.assertEqual([x['price'] for x in upper],[10,15])

    def test_separated_repeated_resistance_tests_qualify(self):
        bars=[dict(time=1,open=10,high=10.8,low=9.4,close=9.6),
              dict(time=2,open=9.8,high=10,low=9.7,close=9.8),
              dict(time=3,open=10,high=10.79,low=9.4,close=9.5),
              dict(time=4,open=11,high=11.5,low=10.9,close=11.2)]
        self.assertEqual([x['price'] for x in role_reversal_levels(bars,11.3)],[10.79])

    def test_independent_checkbox_does_not_leak_into_labels(self):
        levels=analyze(self.jagx(),current_price=5.5,enabled_types=['resistance'])
        self.assertFalse(any('Prior' in x.get('label','') for x in levels))
        self.assertFalse(any(x['kind'].startswith('former_') for x in levels))

    def test_spacing_merges_flipped_role_with_existing_daily_role(self):
        bars=self.jagx();bars[-1]['high']=6.81
        levels=analyze(bars,current_price=5.5,enabled_types=['resistance','former_support'])
        level=next(x for x in levels if x['price']==6.81)
        self.assertEqual(level['label'],'Resistance / Prior S')
        self.assertFalse(any(x['price']==6.8 for x in levels))

    def test_both_role_types_request_daily_data_without_premarket(self):
        class FlippedOnly(Fake):
            def call(self,name,**args):
                if name=='data_ensure_history':raise AssertionError('Premarket requested')
                if name=='data_get_ohlcv':
                    self.assert_resolution(args)
                    return dict(bars=RoleReversalTests().jagx())
                return super().call(name,**args)
            def assert_resolution(self,args):
                if self.resolution!='1D':raise AssertionError('Daily data not requested')
        result=run(FlippedOnly(),dry_run=True,enabled_types=['former_support','former_resistance'])
        self.assertEqual([x['price'] for x in result['levels']],[6.8])
        self.assertEqual(result['premarket']['status'],'disabled')

    def test_drawing_labels_colors_and_clear_ownership(self):
        import json
        for kind,bars,quote,label,color in (
                ('former_support',self.jagx(),5.5,'Prior S 12/31','#ffb74d'),
                ('former_resistance',self.breakout(),13.5,'Prior R 12/31','#00e676')):
            class Drawing(Fake):
                def call(self,name,**args):
                    if name=='data_get_ohlcv':return dict(bars=bars)
                    if name=='quote_snapshot':return dict(last_price=quote,lp_time=100)
                    if name=='draw_shape':self.drawing=args
                    return super().call(name,**args)
            client=Drawing();run(client,enabled_types=[kind])
            self.assertEqual(client.drawing['text'],label)
            style=json.loads(client.drawing['overrides'])
            self.assertEqual(style['linecolor'],color)
            self.assertEqual((style['linewidth'],style['linestyle']),(1,2))
            self.assertEqual(client.removed,['managed'])
            self.assertEqual(client.resolution,'5')

class PriorLabelTests(unittest.TestCase):
    def level(self, kind='former_support', price=6.8, day='2026-09-25', clock='09:30'):
        timestamp=datetime.fromisoformat(day+'T'+clock).replace(tzinfo=ZoneInfo('America/New_York')).timestamp()
        return dict(kind=kind,price=price,time=timestamp,description='Prior support')

    def test_source_candle_date_for_both_roles(self):
        self.assertEqual(drawing_label(self.level()),'Prior S 09/25')
        self.assertEqual(drawing_label(self.level('former_resistance',7.49,'2026-09-15')),'Prior R 09/15')

    def test_date_uses_chart_market_timezone(self):
        # This evening source is already the next date in UTC.
        self.assertEqual(drawing_label(self.level(day='2026-09-25',clock='22:00')),'Prior S 09/25')

    def test_pm_merge_keeps_daily_source_date_on_repeated_spacing(self):
        daily=self.level()
        pm=self.level('premarket_high',6.81,'2026-10-05')
        combined=spaced_levels([daily,pm])
        self.assertEqual(combined[0]['price'],6.81)
        now=datetime(2026,10,5,12,tzinfo=ZoneInfo('America/New_York'))
        self.assertEqual(drawing_label(spaced_levels(combined)[0],now),'PM high / Prior S 09/25')

    def test_each_role_keeps_its_date_in_combined_label(self):
        levels=spaced_levels([self.level(),self.level('former_resistance',6.81,'2026-09-15')])
        self.assertEqual(drawing_label(levels[0]),'Prior S 09/25 / Prior R 09/15')

    def test_other_daily_labels_include_their_dates(self):
        self.assertEqual(drawing_label(self.level('support')),'Support 09/25')
        self.assertEqual(drawing_label(dict(kind='gap',price=6.8,time=1,description='Gap fill')),'Gap fill 12/31')

class HistoricalLabelTests(unittest.TestCase):
    now=datetime(2026,10,5,12,tzinfo=ZoneInfo('America/New_York'))

    def level(self, kind, text, day, price=6):
        timestamp=datetime.fromisoformat(day+'T09:30').replace(tzinfo=ZoneInfo('America/New_York')).timestamp()
        return dict(kind=kind,description=text,price=price,time=timestamp)

    def test_every_historical_daily_source_is_dated(self):
        cases=[('resistance','Resistance'),('support','Support'),
               ('gap','Gap entry (remaining)'),('gap','Gap fill'),
               ('window','Window entry'),('window','Window top'),
               ('former_support','Prior S'),('former_resistance','Prior R')]
        for kind,text in cases:
            expected=text.replace(' (remaining)','')+' 09/25'
            with self.subTest(text=text):
                self.assertEqual(drawing_label(self.level(kind,text,'2026-09-25'),self.now),expected)

    def test_todays_levels_are_undated(self):
        for kind,text in [('premarket_high','PM high'),('premarket_low','PM low'),
                          ('support','Support'),('window','Window entry')]:
            self.assertEqual(drawing_label(self.level(kind,text,'2026-10-05'),self.now),text)

    def test_pm_merge_uses_each_daily_reference_date(self):
        levels=[self.level('premarket_high','PM high','2026-10-05',6.01),
                self.level('resistance','Resistance','2026-09-29',6),
                self.level('former_support','Prior S','2026-09-25',6.005)]
        combined=spaced_levels(spaced_levels(levels))
        self.assertEqual(drawing_label(combined[0],self.now),
                         'PM high / Resistance 09/29 / Prior S 09/25')

    def test_gap_and_window_merged_boundary_preserves_separate_dates(self):
        levels=[self.level('gap','Gap fill','2026-08-20',6.42),
                self.level('window','Window entry','2026-08-19',6.43)]
        merged=spaced_levels(spaced_levels(levels))[0]
        self.assertEqual(drawing_label(merged,self.now),'Gap fill 08/20 / Window entry 08/19')

    def test_repeated_same_day_reference_deduplicates_visible_label(self):
        levels=[self.level('resistance','Resistance','2026-09-29',6.01),
                self.level('resistance','Resistance','2026-09-29',6)]
        self.assertEqual(drawing_label(spaced_levels(levels)[0],self.now),'Resistance 09/29')

    def test_same_type_different_days_preserves_both_dates(self):
        levels=[self.level('resistance','Resistance','2026-09-29',6.01),
                self.level('resistance','Resistance','2026-09-25',6)]
        self.assertEqual(drawing_label(spaced_levels(levels)[0],self.now),
                         'Resistance 09/29 / Resistance 09/25')

    def test_partial_gap_entry_dates_the_candle_setting_the_remaining_edge(self):
        def candle(day,low,high):
            timestamp=self.level('gap','Gap entry',day)['time']
            return bar(timestamp,low,high)
        bars=[candle('2026-09-24',8,10),candle('2026-09-25',4,5),candle('2026-09-28',4,6)]
        levels=analyze(bars,current_price=5,enabled_types=['gap'])
        self.assertEqual([drawing_label(x,self.now) for x in levels],
                         ['Gap entry 09/28','Gap fill target 09/24'])

class ColorRoleTests(unittest.TestCase):
    def level(self, kind, price=6):
        return dict(kind=kind,price=price,time=1,description='Daily level')

    def test_daily_color_follows_price_side_for_every_source_type(self):
        for kind in ('support','resistance','gap','window'):
            with self.subTest(kind=kind):
                self.assertEqual(drawing_color(self.level(kind),7),'#66bb6a')
                self.assertEqual(drawing_color(self.level(kind),5),'#d18b32')

    def test_prior_color_uses_brighter_shade_and_current_role(self):
        for kind in ('former_support','former_resistance'):
            self.assertEqual(drawing_color(self.level(kind),7),'#00e676')
            self.assertEqual(drawing_color(self.level(kind),5),'#ffb74d')

    def test_merged_daily_line_keeps_prior_shading(self):
        levels=spaced_levels([self.level('resistance',6.01),self.level('former_support',6)])
        self.assertEqual(levels[0]['kind'],'resistance')
        self.assertEqual(drawing_color(spaced_levels(levels)[0],5),'#ffb74d')
        self.assertEqual(drawing_color(levels[0],7),'#00e676')

    def test_premarket_color_wins_even_when_merged_with_prior(self):
        for kind in ('premarket_high','premarket_low'):
            levels=spaced_levels([self.level(kind,6.01),self.level('former_support',6)])
            self.assertEqual(drawing_color(levels[0],5),'#ff00ff')
            self.assertEqual(drawing_color(levels[0],7),'#ff00ff')

    def test_level_at_quote_uses_resistance_color(self):
        self.assertEqual(drawing_color(self.level('gap'),6),'#d18b32')

    def test_gap_draw_uses_both_roles_and_matching_text_colors(self):
        import json
        class Drawing(Fake):
            def __init__(self):
                super().__init__();self.styles=[]
            def call(self,name,**args):
                if name=='draw_shape':self.styles.append(json.loads(args['overrides']))
                return super().call(name,**args)
        client=Drawing()
        # Fake daily gap is 6-8. A live quote inside it gives green/orange edges.
        with patch('daily_levels.read_reference',return_value=dict(price=7,time=100)):
            run(client,enabled_types=['gap'])
        self.assertEqual([s['linecolor'] for s in client.styles],['#66bb6a','#d18b32'])
        for style in client.styles:
            self.assertEqual(style['textcolor'],style['linecolor'])
            self.assertEqual((style['linewidth'],style['linestyle']),(1,1))

class LivePriceTests(unittest.TestCase):
    def test_premarket_trade_replaces_previous_regular_close(self):
        self.assertEqual(latest_quote(dict(last_price=4.51,lp_time=100,rtc=8.34,rtc_time=200))['price'],8.34)
    def test_regular_trade_replaces_old_premarket_trade(self):
        self.assertEqual(latest_quote(dict(last_price=9,lp_time=300,rtc=8.34,rtc_time=200))['price'],9)
    def test_overnight_trade_and_invalid_quote(self):
        self.assertEqual(latest_quote(dict(last_price=4,lp_time=100,rtc=5,rtc_time=200,ntc=6,ntc_time=300))['price'],6)
        with self.assertRaises(RuntimeError):latest_quote(dict(last_price=4))
    def test_numeric_strings_and_equal_timestamps_prefer_premarket(self):
        q=latest_quote(dict(last_price='4.51',lp_time='200',rtc='8.34',rtc_time='200',session='pre_market'))
        self.assertEqual(q['price'],8.34)
    def test_regular_close_uses_actual_timestamp_in_extended_session(self):
        q=latest_quote(dict(last_price=4.51,lp_time=300,regular_close_time=100,rtc=8.34,rtc_time=200,session='pre_market'))
        self.assertEqual(q['source'],'rtc')
    def test_loading_quote_retries_then_succeeds(self):
        class Loading:
            def __init__(self):self.calls=0
            def call(self,*a,**kw):
                self.calls+=1
                return {} if self.calls==1 else dict(rtc='8.34',rtc_time='200')
        c=Loading()
        with patch('daily_levels.time.sleep'):
            self.assertEqual(read_reference(c)['price'],8.34)
        self.assertEqual(c.calls,2)
    def test_quote_reset_keeps_valid_pre_switch_snapshot(self):
        class Empty:
            def call(self,*a,**kw):return {}
        snapshot=dict(price=8.34,time=200,source='rtc')
        self.assertEqual(read_reference(Empty(),timeout=0,fallback=snapshot),snapshot)
    def test_selection_errors_are_not_retried_or_hidden_by_fallback(self):
        class Changed:
            def call(self,*a,**kw):raise RuntimeError('Selected chart pane changed')
        with self.assertRaisesRegex(RuntimeError,'pane changed'):
            read_reference(Changed(),fallback=dict(price=8,time=200))

    def test_live_price_reserves_two_overhead_levels_and_keeps_gap_context(self):
        bars=[bar(1,12,14),bar(2,10,12),bar(3,8,10),bar(4,4,6),bar(5,4,5)]
        levels=analyze(bars,current_price=11)
        self.assertEqual([x['price'] for x in levels if x['price']>11],[12,14])
        self.assertEqual([x['price'] for x in levels if x['kind']=='gap'],[6,8])
    def test_one_or_no_overhead_levels_does_not_invent_levels(self):
        bars=[bar(1,5,12),bar(2,5,10),bar(3,5,8)]
        self.assertEqual([x['price'] for x in analyze(bars,current_price=11) if x['price']>11],[12])
        self.assertEqual([x for x in analyze(bars,current_price=13) if x['price']>13],[])
    def test_window_endpoint_cannot_use_up_overhead_budget(self):
        bars=[bar(1,12,16)]+[bar(i,9,10) for i in range(2,6)]
        bars += [dict(time=6,open=10,close=6,high=11,low=5),bar(7,4,4.8)]
        levels=analyze(bars,current_price=6)
        # A remote gap is filtered while actual daily highs still reserve
        # two distinct overhead references, including the window's top.
        self.assertEqual([x['price'] for x in levels if x['price']>6],[11,16])

class SpacingTests(unittest.TestCase):
    def level(self,p,kind='resistance'):
        return dict(price=p,kind=kind,time=1,description='Resistance' if kind=='resistance' else 'Gap fill')
    def test_cntb_near_highs_merge_and_backfill_next_distinct_high(self):
        bars=[bar(1,1,2.4),bar(2,1,2.1),bar(3,1,2.0991),bar(4,1,1.5)]
        prices=[x['price'] for x in analyze(bars,current_price=1.9) if x['price']>1.9]
        self.assertEqual(prices,[2.1,2.4])
    def test_percentage_dominates_on_higher_prices(self):
        self.assertEqual([x['price'] for x in spaced_levels([self.level(100),self.level(100.4)])],[100.4])
    def test_tick_ladder_below_and_above_one_dollar(self):
        ladder='0.0001 1 0.01'
        self.assertEqual(price_tick(.5,.0001,ladder),.0001)
        self.assertEqual(price_tick(2.1,.0001,ladder),.01)
        self.assertTrue(levels_near(2.10,2.115,.0001,ladder))
        self.assertFalse(levels_near(.5,.51,.0001,ladder))
    def test_exact_two_tick_spacing_remains_distinct(self):
        self.assertEqual(len(spaced_levels([self.level(2.10),self.level(2.12)])),2)
    def test_group_does_not_bridge_an_arbitrarily_wide_chain(self):
        self.assertEqual([x['price'] for x in spaced_levels([self.level(2.10),self.level(2.115),self.level(2.13)])],[2.10,2.13])
    def test_narrow_gap_merges_at_actual_boundary_with_simple_label(self):
        merged=spaced_levels([self.level(2.099,'gap'),self.level(2.1,'gap')])
        self.assertEqual(merged[0]['price'],2.1)
        self.assertEqual(merged[0]['label'],'Gap')
    def test_merging_mixed_roles_preserves_meaning(self):
        merged=spaced_levels([self.level(2.099,'gap'),dict(self.level(2.1,'window'),description='Window entry')])
        self.assertEqual(merged[0]['label'],'Gap / Window')

class WindowTests(unittest.TestCase):
    def candles(self):
        data = [bar(i,9,10) for i in range(1,5)]
        data += [dict(time=5,open=10,close=6,high=11,low=5), bar(6,4,4.8),bar(7,4,4.7)]
        return data
    def test_boundaries_are_wicks_not_body(self):
        pairs = candle_windows(self.candles())
        self.assertEqual([(a['price'],b['price']) for a,b in pairs],[(5,11)])
    def test_newer_wick_obscures_entry_without_inventing_boundary(self):
        pair=candle_windows(self.candles()+[bar(8,4,5.28)])[0]
        self.assertEqual([x['price'] for x in pair],[5.28,11])
        self.assertEqual(pair[0]['time'],8)
        self.assertEqual(pair[0]['corridor']['low'],5)
    def test_filled_window_removed(self):
        self.assertEqual(candle_windows(self.candles()+[bar(8,5,11)]),[])
    def test_large_wick_is_not_long_body(self):
        data=self.candles(); data[4].update(open=6,close=5.8,high=20)
        self.assertEqual(candle_windows(data),[])
    def test_source_candle_invalidates_internal_historical_pivot(self):
        data = [bar(1,5,6),bar(2,5,8),bar(3,5,6),bar(4,5,6)]
        data += [dict(time=5,open=10,close=6,high=11,low=5),bar(6,4,4.8),bar(7,4,4.9)]
        pairs=candle_windows(data)
        self.assertEqual([(a['price'],b['price']) for a,b in pairs],[(5,11)])
    def test_shadowed_low_cannot_resurrect_broken_prior_swing(self):
        data = [bar(1,5,6),bar(2,5,8),bar(3,5,6),bar(4,5,6)]
        data += [dict(time=5,open=10,close=6,high=11,low=5),bar(6,4,6.5),bar(7,4,4.9)]
        pairs=candle_windows(data)
        self.assertEqual([x['price'] for x in pairs[0]],[6.5,11])
        self.assertNotIn(8,[x['price'] for p in pairs for x in p])
    def test_source_candle_supersedes_prior_high_at_its_open(self):
        data = [bar(1,5,6),bar(2,5,10),bar(3,5,6),bar(4,5,6)]
        data += [dict(time=5,open=10,close=6,high=11,low=5),bar(6,4,4.8),bar(7,4,4.9)]
        pairs=candle_windows(data)
        self.assertEqual([(a['price'],b['price']) for a,b in pairs],[(5,11)])

class Fake:
    def __init__(self, fail=False):
        self.resolution='5'
        self.fail=fail
        self.created=[]
        self.removed=[]
        self.session='regular'
    def call(self, name, **args):
        if name=='chart_get_state':
            return dict(symbol='NASDAQ:TEST', resolution=self.resolution, chartType=1)
        if name=='chart_set_timeframe':
            self.resolution=args['timeframe']; return {}
        if name=='session_snapshot':
            return dict(session=self.session,premarket_supported=True)
        if name=='chart_set_session':
            self.session=args['session'];return {}
        if name=='data_ensure_history':
            return dict(complete=True)
        if name=='data_get_ohlcv':
            return dict(bars=[bar(1, 8, 10),bar(86401,4,5),bar(172801,4,6)])
        if name=='data_get_intraday':
            return dict(bars=[])
        if name=='data_get_session_history':
            return dict(bars=[])
        if name=='data_latest_intraday_time':
            return dict(time=None)
        if name=='quote_snapshot':
            return dict(last_price=5,lp_time=172801)
        if name=='draw_list':
            return dict(shapes=[dict(id='manual'),dict(id='managed')])
        if name=='draw_get_properties':
            return dict(properties=dict(text='Manual' if args['entity_id']=='manual' else '[DailyLevels] old'))
        if name=='draw_shape':
            if self.fail and self.created:
                raise RuntimeError('injected drawing failure')
            entity_id=str(len(self.created)); self.created.append(entity_id)
            return dict(entity_id=entity_id)
        if name=='draw_remove_one':
            self.removed.append(args['entity_id']); return {}
        raise AssertionError(name)

class WorkflowTests(unittest.TestCase):
    def test_restores_intraday_and_preserves_manual(self):
        client=Fake()
        run(client)
        self.assertEqual(client.resolution,'5')
        self.assertEqual(client.removed,['managed'])
        self.assertEqual(client.session,'regular')
    def test_restores_and_rolls_back_after_failure(self):
        client=Fake(True)
        with self.assertRaises(RuntimeError): run(client)
        self.assertEqual(client.resolution,'5')
        self.assertEqual(client.removed,['0'])
    def test_dry_run_does_not_mutate_drawings(self):
        client=Fake(); run(client,dry_run=True)
        self.assertEqual(client.created,[])
        self.assertEqual(client.resolution,'5')

class LevelSelectionTests(unittest.TestCase):
    def candles(self):
        return ([bar(i,9,10) for i in range(1,5)] +
                [dict(time=5,open=10,close=6,high=11,low=5),bar(6,3,4),bar(7,3,4.2)])

    def test_all_enabled_matches_default(self):
        self.assertEqual(analyze(self.candles()), analyze(self.candles(),enabled_types=LEVEL_TYPES))

    def test_each_daily_type_alone_keeps_only_its_roles(self):
        for kind in LEVEL_TYPES[:4]:
            with self.subTest(kind=kind):
                levels = analyze(self.candles(),enabled_types=[kind])
                self.assertTrue(levels)
                self.assertEqual({x['kind'] for x in levels},{kind})
                if kind == 'gap':
                    self.assertFalse(any('Window' in x['description'] or 'Window' in x.get('label','') for x in levels))

    def test_unchecked_pm_does_not_anchor_or_label_daily_cluster(self):
        bars=[bar(1,1,2.4),bar(2,1,2.1),bar(3,1,1.5)]
        pm=[dict(price=2.099,time=4,kind='premarket_high',description='PM high')]
        levels=analyze(bars,current_price=1.9,extra_levels=pm,enabled_types=['resistance'])
        self.assertEqual([x['price'] for x in levels],[2.1,2.4])
        self.assertFalse(any('PM' in x.get('label','') for x in levels))

    def test_unchecked_daily_role_does_not_leak_into_pm_label(self):
        pm=[dict(price=5.01,time=8,kind='premarket_high',description='PM high'),
            dict(price=5,time=8,kind='premarket_low',description='PM low')]
        levels=analyze(self.candles(),extra_levels=pm,enabled_types=['premarket_high'])
        self.assertEqual(levels,[pm[0]])

    def test_daily_only_skips_premarket_data_and_extended_session(self):
        class DailyOnly(Fake):
            def call(self,name,**args):
                if name=='data_ensure_history' or (name=='chart_set_session' and args['session']=='extended'):
                    raise AssertionError('Disabled premarket requested')
                return super().call(name,**args)
        client=DailyOnly()
        result=run(client,enabled_types=['gap'])
        self.assertEqual({x['kind'] for x in result['levels']},{'gap'})
        self.assertEqual(result['premarket']['status'],'disabled')
        self.assertEqual(client.session,'regular')
        self.assertEqual(client.resolution,'5')
        self.assertEqual(client.removed,['managed'])

    def test_pm_only_skips_daily_and_can_draw_one_boundary(self):
        class PMOnly(Fake):
            def call(self,name,**args):
                if name=='chart_set_timeframe' and args['timeframe']=='1D':
                    raise AssertionError('Disabled daily requested')
                if name=='data_get_ohlcv':
                    return dict(bars=[bar(datetime(2026,9,30,8,tzinfo=ZoneInfo('America/New_York')).timestamp(),2,7)])
                return super().call(name,**args)
        client=PMOnly()
        result=run(client,enabled_types=['premarket_low'],now=datetime(2026,9,30,10,tzinfo=ZoneInfo('America/New_York')))
        self.assertEqual([(x['kind'],x['price']) for x in result['levels']],[('premarket_low',2)])
        self.assertEqual(result['enabled_types'],['premarket_low'])
        self.assertEqual(len(client.created),1)
        self.assertEqual(client.session,'regular')
        self.assertEqual(client.resolution,'5')

    def test_invalid_or_empty_selection_fails_before_chart_access(self):
        class NoCalls:
            def bind_selected(self):raise AssertionError('Chart accessed')
        for selection in ([],['unknown']):
            with self.assertRaises(ValueError):run(NoCalls(),enabled_types=selection)

    def test_clear_still_removes_all_managed_types(self):
        client=Fake()
        result=clear_levels(client)
        self.assertEqual(result['removed'],1)
        self.assertEqual(client.removed,['managed'])
        self.assertEqual(client.resolution,'5')

class PremarketTests(unittest.TestCase):
    def at(self, date, clock):
        return datetime.fromisoformat(date+'T'+clock).replace(tzinfo=ZoneInfo('America/New_York'))
    def candle(self, date, clock, low, high):
        return bar(self.at(date,clock).timestamp(),low,high)
    def test_only_today_premarket_wicks_exclude_overnight_and_opening_bar(self):
        candles=[self.candle('2026-09-29','08:00',1,20), self.candle('2026-09-30','03:55',1,15),
                 self.candle('2026-09-30','04:00',3,5),self.candle('2026-09-30','09:25',2,6),
                 self.candle('2026-09-30','09:30',1,12)]
        levels=premarket_levels(candles,self.at('2026-09-30','10:00'))
        self.assertEqual([x['price'] for x in levels],[6,2])
    def test_running_session_includes_forming_bar_excludes_future(self):
        candles=[self.candle('2026-09-30','04:00',3,5),self.candle('2026-09-30','08:05',2,6),
                 self.candle('2026-09-30','08:10',1,12)]
        self.assertEqual([x['price'] for x in premarket_levels(candles,self.at('2026-09-30','08:07'))],[6,2])
    def test_no_previous_session_on_weekend_or_before_four(self):
        candles=[self.candle('2026-09-30','08:00',2,6)]
        self.assertEqual(premarket_levels(candles,self.at('2026-10-03','10:00')),[])
        self.assertEqual(premarket_levels(candles,self.at('2026-09-30','03:59')),[])
    def test_dst_uses_new_york_clock(self):
        for date in ('2026-01-05','2026-07-06'):
            levels=premarket_levels([self.candle(date,'04:00',2,6),self.candle(date,'09:30',1,12)],self.at(date,'10:00'))
            self.assertEqual([x['price'] for x in levels],[6,2])
    def test_premarket_exact_boundary_wins_near_daily_and_retains_roles(self):
        daily=dict(price=2.1,kind='resistance',time=1,description='Resistance')
        pm=dict(price=2.0991,kind='premarket_high',time=2,description='PM high')
        levels=spaced_levels([daily,pm])
        self.assertEqual(levels[0]['price'],2.0991)
        self.assertEqual(levels[0]['label'],'PM high / Resistance')
    def test_narrow_pm_range_combines_without_chain_bridging(self):
        levels=spaced_levels([dict(price=p,kind=k,time=1,description='') for p,k in
                              [(2.1,'premarket_high'),(2.09,'premarket_low'),(2.075,'support')]])
        self.assertEqual([x['price'] for x in levels],[2.075,2.1])
        self.assertEqual(levels[1]['label'],'PM high / PM low')
    def test_pm_merge_below_quote_backfills_two_overhead_lines(self):
        bars=[bar(1,1,3),bar(2,1,2.4),bar(3,1,2.1),bar(4,1,1.5)]
        pm=[dict(price=2.09,kind='premarket_high',time=5,description='PM high')]
        levels=analyze(bars,current_price=2.095,extra_levels=pm)
        self.assertEqual([x['price'] for x in levels if x['price']>2.095],[2.4,3])
    def test_incomplete_history_preserves_old_drawings_and_restores_session(self):
        class Missing(Fake):
            def call(self,name,**args):
                if name=='data_ensure_history':raise RuntimeError('Full premarket history did not load')
                return super().call(name,**args)
        client=Missing()
        with self.assertRaisesRegex(RuntimeError,'Full premarket history'):run(client,now=self.at('2026-09-30','10:00'))
        self.assertEqual(client.resolution,'5')
        self.assertEqual(client.session,'regular')
        self.assertEqual(client.created,[])
        self.assertEqual(client.removed,[])

if __name__=='__main__': unittest.main()
