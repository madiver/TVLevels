import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from daily_levels import (analyze, confirmed, levels_near, price_tick, spaced_levels,
                          candle_windows, drawing_label, run)
from reaction_levels import reaction_levels, gap_corridors, daily_context, selection_rank


def candle(t, close=10, high=10.01, low=9.99, volume=100):
    return dict(time=t, open=close, close=close, high=high, low=low, volume=volume)


def repeated():
    return [candle(1), candle(2, high=10.08), candle(3),
            candle(4, high=10.075), candle(5)]


def areas(bars, quote=10):
    return reaction_levels(bars, quote, levels_near, price_tick)


def resistance_area(bars, quote=10):
    return next(x for x in areas(bars, quote) if abs(x['price']-10.08)<.001)


class ReactionTests(unittest.TestCase):
    def test_quiet_independent_tests_qualify_without_ten_percent_move(self):
        area=resistance_area(repeated())
        self.assertEqual(area['independent_tests'],2)
        self.assertEqual(area['zone'],dict(low=10.075, high=10.08))
        self.assertEqual({x['price'] for x in area['source_prices']},{10.075,10.08})
        self.assertEqual(area['time'],2)

    def test_consecutive_wick_shelf_is_not_counted_as_independent_tests(self):
        bars=[candle(i, high=10.08) for i in range(1,9)]
        self.assertEqual(areas(bars),[])

    def test_repeated_area_survives_later_wick_pass(self):
        bars=repeated()+[candle(6,high=10.15),candle(7)]
        area=resistance_area(bars)
        self.assertEqual(area['state'],'active')
        self.assertEqual(area['confirmed_role'],'resistance')

    def test_live_cross_preserves_unconfirmed_retest_reference(self):
        area=resistance_area(repeated(),10.12)
        self.assertEqual((area['kind'],area['state']),('resistance','crossed'))
        self.assertEqual(area['display_text'],'Retest R')
        self.assertEqual(area['history'],[])
        selected=analyze(repeated(),current_price=10.12,enabled_types=['resistance'])
        self.assertIn(10.08,[x['price'] for x in selected])

    def test_support_cross_break_and_reclaim_are_symmetric(self):
        bars=[dict(x,low=20-x['high'],high=20-x['low']) for x in repeated()]
        area=next(x for x in areas(bars,9.88) if x['price']==9.92)
        self.assertEqual((area['kind'],area['state'],area['display_text']),('support','crossed','Retest S'))
        bars.append(candle(6,9.8,9.82,9.77))
        area=next(x for x in areas(bars,9.8) if x['price']==9.92)
        self.assertEqual(area['kind'],'former_support')
        bars.append(candle(7))
        area=next(x for x in areas(bars,10) if x['price']==9.92)
        self.assertEqual((area['kind'],area['state']),('support','reclaimed'))

    def test_boundary_equal_to_live_quote_remains_a_reference(self):
        selected=analyze([candle(1,10,12,9),candle(2,10,11,9)],current_price=11,enabled_types=['resistance'])
        self.assertIn(11,[x['price'] for x in selected])

    def test_quiet_tests_across_a_failed_break_keep_reclaim_history(self):
        bars=[candle(1,10.06,10.07,10.05),candle(2,10.06,10.08,10.05),
              candle(3,10.2,10.22,10.19),candle(4,10,10.075,9.99),candle(5)]
        area=resistance_area(bars)
        self.assertEqual(area['independent_tests'],2)
        self.assertEqual(area['state'],'reclaimed')
        self.assertEqual([x['role'] for x in area['history']],['support','resistance'])

    def test_repeated_merge_retains_both_corridor_identities(self):
        gap=dict(price=10,time=1,kind='gap',description='Gap fill',
                 corridor=dict(id='gap:1:up',remaining_low=9,high=10,state='partial'))
        window=dict(price=10,time=2,kind='window',description='Window entry',
                    corridor=dict(id='window:2',remaining_low=10,high=12,state='partial'))
        merged=spaced_levels([gap,window])
        merged=spaced_levels(merged+[dict(price=11,time=3,kind='resistance',description='Daily high')])
        self.assertEqual({c['id'] for c in merged[0]['corridors']},{'gap:1:up','window:2'})

    def test_completed_break_retest_and_reclaim_preserve_same_area(self):
        broken=repeated()+[candle(6,10.20,10.22,10.19)]
        area=resistance_area(broken,10.2)
        self.assertEqual((area['kind'],area['state']),('former_resistance','flipped'))
        retested=broken+[candle(7,10.1,10.15,10.075)]
        self.assertEqual(resistance_area(retested,10.1)['state'],'retested')
        reclaimed=retested+[candle(8)]
        area=resistance_area(reclaimed)
        self.assertEqual((area['kind'],area['state']),('resistance','reclaimed'))
        self.assertEqual([x['role'] for x in area['history']],['support','resistance'])

    def test_live_return_does_not_erase_completed_prior_role(self):
        bars=repeated()+[candle(6,10.20,10.22,10.19)]
        area=resistance_area(bars,10)
        self.assertEqual(area['kind'],'former_resistance')
        self.assertEqual(area['display_text'],'Prior R retest')
        selected=analyze(bars,current_price=10,enabled_types=['former_resistance'])
        self.assertIn(10.08,[x['price'] for x in selected])

    def test_close_inside_zone_does_not_flip_role(self):
        area=resistance_area(repeated()+[candle(6,10.077,10.1,10.06)],10.077)
        self.assertEqual(area['confirmed_role'],'resistance')
        self.assertEqual(area['history'],[])

    def test_old_significant_area_has_no_sixty_day_cutoff(self):
        bars=repeated()+[candle(i) for i in range(6,110)]
        selected=analyze(bars,current_price=10.04,enabled_types=['resistance'])
        self.assertIn(10.08,[x['price'] for x in selected])

    def test_relative_volume_affects_strength_not_source_price(self):
        normal=repeated()
        busy=[dict(x) for x in normal];busy[3]['volume']=400
        a,b=resistance_area(normal),resistance_area(busy)
        self.assertEqual(a['price'],b['price'])
        self.assertGreater(b['strength'],a['strength'])
        self.assertGreater(b['volume_ratio'],a['volume_ratio'])
        self.assertLess(selection_rank(b,10.1),selection_rank(a,10.1))

    def test_pm_merge_keeps_actual_zone_and_prices(self):
        a=resistance_area(repeated())
        merged=spaced_levels([a,dict(price=10.081,time=7,kind='premarket_high',description='PM high')])[0]
        self.assertEqual(merged['price'],10.081)
        self.assertEqual(merged['reaction_areas'][0]['zone'],a['zone'])
        self.assertEqual(merged['reaction_areas'][0]['source_prices'],a['source_prices'])
        self.assertIn(10.08,[x['price'] for x in merged['label_sources']])

    def test_daily_budget_bounds_many_reaction_areas(self):
        bars=[candle(0,24.5,25,24)]
        for i in range(1,30):
            p=10+i*.2
            bars.append(candle(i,p,p+.4,p-.4))
        selected=analyze(bars,current_price=13,enabled_types=['resistance','support','former_support','former_resistance'])
        self.assertLessEqual(len(selected),5)
        self.assertGreaterEqual(sum(x['price']>13 for x in selected),2)


class CorridorTests(unittest.TestCase):
    def gap(self):
        return [candle(1,9,10,8),candle(2,4.5,5,4),candle(3,5,6,4)]

    def test_partial_gap_uses_completed_actual_edge(self):
        pair=gap_corridors(self.gap())[0]
        self.assertEqual([x['price'] for x in pair],[6,8])
        self.assertEqual(pair[0]['time'],3)
        self.assertEqual(pair[0]['corridor']['low'],5)
        self.assertEqual(pair[0]['corridor']['state'],'partial')

    def test_traversed_today_restores_original_historical_edges(self):
        today=candle(4,8.5,9,5)
        pair=gap_corridors(self.gap(),today)[0]
        self.assertEqual([x['price'] for x in pair],[5,8])
        self.assertEqual(pair[0]['corridor']['state'],'traversed_today')
        self.assertTrue(all('Filled gap' in drawing_label(x) for x in pair))

    def test_partial_today_is_recorded_without_inventing_an_entry(self):
        pair=gap_corridors(self.gap(),candle(4,6.5,7,5))[0]
        self.assertEqual([x['price'] for x in pair],[6,8])
        self.assertEqual(pair[0]['corridor']['state'],'partial_today')

    def test_filled_reference_expires_after_twenty_sessions(self):
        filled=self.gap()+[candle(4,8,9,5)]
        self.assertEqual(gap_corridors(filled)[0][0]['corridor']['state'],'filled_recent')
        self.assertEqual(gap_corridors(filled+[candle(i,7,9,5) for i in range(5,26)]),[])

    def test_downward_gap_uses_lows_and_its_own_fill_status(self):
        bars=[candle(1,4,5,3),candle(2,9,10,8),candle(3,8,9,7)]
        pair=gap_corridors(bars,candle(4,5,7,4))[0]
        self.assertEqual([x['price'] for x in pair],[5,8])
        self.assertEqual(pair[0]['corridor']['direction'],'down')
        self.assertEqual(pair[0]['corridor']['state'],'traversed_today')

    def test_far_gap_is_suppressed_with_daily_levels_but_can_be_inspected(self):
        bars=self.gap()+[candle(i,1,1.1,.9) for i in range(4,31)]
        selected=analyze(bars,current_price=1)
        corridors=[c for x in selected for c in x.get('corridors',[]) if c['id'].startswith('gap:')]
        self.assertFalse(any(c['high']==8 for c in corridors))
        explicit=analyze(bars,current_price=1,enabled_types=['gap'])
        self.assertTrue(explicit)

    def test_window_revisit_uses_real_newer_high_in_ross_example_shape(self):
        bars=[dict(candle(i,10,10.1,9.9),open=9.98) for i in range(1,5)]
        bars += [dict(time=5,open=18,close=6,low=5,high=19.5),candle(6,7,8.77,6)]
        pair=candle_windows(bars)[0]
        self.assertEqual([x['price'] for x in pair],[8.77,19.5])
        self.assertEqual(pair[0]['time'],6)
        self.assertEqual(candle_windows(bars+[candle(7,18,19.5,7)]),[])

    def test_computed_context_reports_ma_and_daily_level_inside_merged_corridor(self):
        bars=[candle(i,7,8,6) for i in range(1,201)]
        pair=gap_corridors(self.gap())[0]
        interior=dict(price=7.2,time=10,kind='resistance',description='Unbroken daily high')
        pm=dict(price=6,time=201,kind='premarket_high',description='PM high')
        levels=spaced_levels(list(pair)+[interior,pm])
        context=daily_context(bars,levels)
        self.assertEqual(context['computed_daily_sma200'],7)
        self.assertEqual({x['kind'] for x in context['obstructions'][0]['references']},
                         {'resistance','computed_daily_sma200'})
        self.assertIsNone(daily_context(bars[:199],levels)['computed_daily_sma200'])

    def test_completed_filter_respects_supplied_market_clock(self):
        zone=ZoneInfo('America/New_York')
        yesterday=candle(datetime(2026,10,5,9,30,tzinfo=zone).timestamp())
        today=candle(datetime(2026,10,6,9,30,tzinfo=zone).timestamp())
        self.assertEqual(confirmed([yesterday,today],datetime(2026,10,6,12,tzinfo=zone)),[yesterday])
        self.assertEqual(confirmed([yesterday,today],datetime(2026,10,6,16,tzinfo=zone)),[yesterday,today])

    def test_completed_today_can_create_a_new_gap(self):
        previous=candle(1,9,10,8)
        today=candle(2,4.5,5,4)
        pair=gap_corridors([previous,today],today)[0]
        self.assertEqual([x['price'] for x in pair],[5,8])
        self.assertEqual(pair[0]['corridor']['state'],'unfilled')

    def test_completed_today_marks_gap_traversal_at_original_edges(self):
        today=candle(4,8.5,9,5)
        pair=gap_corridors(self.gap()+[today],today)[0]
        self.assertEqual([x['price'] for x in pair],[5,8])
        self.assertEqual(pair[0]['corridor']['state'],'traversed_today')

    def test_quote_crossing_is_distinguished_from_observed_daily_fill(self):
        selected=analyze(self.gap(),current_price=9,enabled_types=['gap'])
        self.assertEqual(selected[0]['corridor']['state'],'crossed_quote')
        self.assertIn('ref',drawing_label(selected[0]))

    def test_bad_forming_bar_fails_before_drawing(self):
        with self.assertRaises(ValueError):
            analyze(self.gap(),current_day=dict(candle(4),high=float('nan')))

    def test_missing_or_nonfinite_volume_is_neutral(self):
        bars=repeated();bars[3]['volume']=float('nan')
        self.assertEqual(resistance_area(bars)['volume_ratio'],1)

    def test_hidden_reaction_area_is_an_obstruction_even_outside_line_budget(self):
        pair=gap_corridors(self.gap())[0]
        reference=dict(price=7.1,time=10,kind='former_support',description='Prior support')
        context=daily_context(self.gap(),list(pair),[reference])
        self.assertEqual(context['obstructions'][0]['references'][0]['price'],7.1)


if __name__=='__main__':
    unittest.main()
