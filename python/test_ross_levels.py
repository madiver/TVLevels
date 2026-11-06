"""Daily gap/window source boundaries and their user-facing explanations."""
import unittest
from daily_levels import analyze, candle_windows, drawing_label, label_sources
from reaction_levels import gap_corridors
from level_explanations import explain_level
from window_policy import window_width_filter
from gap_policy import gap_width_filter


def bar(t, o, h, l, c):
    return dict(time=t, open=o, high=h, low=l, close=c, volume=100)


def explanation(level, quote):
    sources=[dict(kind=level['kind'],price=level['price'],time=level['time'],
                  text=level.get('display_text',level['description']))]
    return explain_level(level,quote,sources)


class RossBoundaryTests(unittest.TestCase):
    def test_close_open_gap_with_overlapping_wicks_is_not_a_wick_gap(self):
        bars=[bar(1,9,10,7,9),bar(2,5,8,4,5)]
        self.assertEqual(gap_corridors(bars),[])

    def test_upward_fill_keeps_original_wick_target_and_source_dates(self):
        bars=[bar(1,9,10,7.60,8),bar(2,2.01,2.11,1.81,2.05),
              bar(3,2.24,2.6689,2.24,2.53)]
        entry,target=gap_corridors(bars)[0]
        self.assertEqual([entry['price'],target['price']],[2.6689,7.60])
        self.assertEqual([entry['time'],target['time']],[3,1])
        c=target['corridor']
        self.assertEqual((c['low'],c['high']),(2.11,7.60))
        self.assertEqual((c['original_low_time'],c['original_high_time']),(2,1))
        self.assertEqual(c['method'],'ross_daily_gap')
        self.assertIn('Gap fill target',drawing_label(target))
        text=explanation(entry,3.22)
        self.assertIn('Original gap edges: $2.11',text)
        self.assertIn('$7.60',text)
        self.assertIn('already inside',text)

    def test_downward_fill_keeps_original_low_target_and_source_dates(self):
        bars=[bar(1,4,5,3,4),bar(2,9,10,8,9),bar(3,8,9,7,8)]
        target,entry=gap_corridors(bars)[0]
        self.assertEqual([target['price'],entry['price']],[5,7])
        self.assertEqual([target['time'],entry['time']],[1,3])
        self.assertEqual((target['corridor']['original_low_time'],
                          target['corridor']['original_high_time']),(1,2))
        self.assertIn('Gap fill target down',drawing_label(target))

    def test_filled_and_quote_crossed_targets_become_references(self):
        bars=[bar(1,9,10,8,9),bar(2,4.5,5,4,4.5)]
        pairs=[gap_corridors(bars+[bar(3,8,9,5,8)])[0],
               gap_corridors(bars,current_day=bar(3,8,9,5,8))[0],
               analyze(bars,current_price=9,enabled_types=['gap'])]
        for pair in pairs:
            target=next(x for x in pair if x['price']==8)
            with self.subTest(state=target['corridor']['state']):
                expected='Gap fill ref' if target['corridor']['state']=='crossed_quote' else 'Filled gap high'
                self.assertIn(expected,drawing_label(target))
                self.assertNotIn('target',drawing_label(target))

    def test_window_uses_red_source_high_not_preceding_green_spike(self):
        # Synthetic shape modeled on Ross's GLBS example; not historical OHLC.
        bars=[bar(i,9.98,10.1,9.9,10) for i in range(1,5)]
        bars += [bar(5,10,24,9,18),bar(6,18,19.5,5,6),
                 bar(7,6,8.77,5.5,7)]
        entry,top=candle_windows(bars)[0]
        self.assertEqual([entry['price'],top['price']],[8.77,19.5])
        self.assertEqual([entry['time'],top['time']],[7,6])
        self.assertEqual(top['corridor']['method'],'ross_large_candle_window')
        text=explanation(top,7)
        self.assertIn('our automation choice',text)
        self.assertIn('does not use ATR',text)
        self.assertEqual(candle_windows(bars+[bar(8,7,19.5,6,18)]),[])


class WindowDisplayTests(unittest.TestCase):
    def bars(self, entry=2.0499):
        bars=[bar(i,2.625,2.7,2.4,2.5) for i in range(1,21)]
        return bars+[bar(21,2.10,2.11,1.79,1.80),bar(22,1.70,entry,1.60,1.90)]

    def test_nxts_small_remnant_is_omitted_even_with_only_windows_enabled(self):
        bars=self.bars()
        self.assertEqual([x['price'] for x in candle_windows(bars)[0]],[2.0499,2.11])
        self.assertEqual(analyze(bars,current_price=1.735,enabled_types=['window']),[])

    def test_exact_quarter_of_original_range_qualifies_with_real_edges(self):
        bars=self.bars(2.00)
        bars[-2].update(low=1.67,close=1.68)
        selected=analyze(bars,current_price=1.735,enabled_types=['window'])
        self.assertEqual([x['price'] for x in selected],[2.00,2.11])
        self.assertAlmostEqual(selected[0]['corridor']['width_filter']['remaining_fraction'],.25)
        self.assertIn('minimum remaining-range filter',explanation(selected[0],1.735))

    def test_price_minimum_filters_tiny_window_even_if_fraction_is_large(self):
        c=dict(low=2.00,high=2.11,remaining_low=2.08)
        self.assertGreater((2.11-2.08)/.11,.25)
        self.assertFalse(window_width_filter(c,lambda p:.01)['eligible'])
        c=dict(low=9.5,high=10,remaining_low=9.5)
        self.assertTrue(window_width_filter(c,lambda p:.01)['eligible'])

    def test_five_percent_equality_and_just_below_are_distinct(self):
        c=dict(low=1.8,high=2,remaining_low=1.9)
        result=window_width_filter(c,lambda p:.01)
        self.assertTrue(result['eligible'])
        self.assertAlmostEqual(result['minimum_width'],.10)
        self.assertEqual(result['min_price_fraction'],.05)
        self.assertFalse(window_width_filter(c|dict(remaining_low=1.900001),lambda p:.01)['eligible'])

    def test_six_cent_window_fails_even_when_quarter_range_requirement_passes(self):
        c=dict(low=1.8,high=2,remaining_low=1.94)
        self.assertGreater((2-1.94)/(2-1.8),.25)
        self.assertFalse(window_width_filter(c,lambda p:.01)['eligible'])

    def test_subdollar_window_uses_percentage_without_cent_rounding(self):
        c=dict(low=.4,high=.5,remaining_low=.475)
        result=window_width_filter(c,lambda p:.0001)
        self.assertTrue(result['eligible'])
        self.assertAlmostEqual(result['minimum_width'],.025)
        self.assertFalse(window_width_filter(c|dict(remaining_low=.475001),lambda p:.0001)['eligible'])

    def test_quarter_range_and_two_ticks_can_still_be_stricter(self):
        c=dict(low=1,high=2,remaining_low=1.8)
        self.assertFalse(window_width_filter(c,lambda p:.01)['eligible'])
        self.assertTrue(window_width_filter(c|dict(remaining_low=1.75),lambda p:.01)['eligible'])
        c=dict(low=.008,high=.01,remaining_low=.009)
        self.assertFalse(window_width_filter(c,lambda p:.001)['eligible'])
        self.assertTrue(window_width_filter(c|dict(remaining_low=.008),lambda p:.001)['eligible'])

    def test_variable_ticks_can_raise_minimum_width_at_upper_endpoint(self):
        c=dict(low=8,high=10,remaining_low=9.5)
        self.assertTrue(window_width_filter(c,lambda p:.01)['eligible'])
        self.assertFalse(window_width_filter(c,lambda p:.5 if p>=10 else .01)['eligible'])

    def test_narrow_pair_does_not_remove_independently_eligible_resistance(self):
        selected=analyze(self.bars(),current_price=1.735,enabled_types=['window','resistance'])
        self.assertFalse(any(s['kind']=='window' for x in selected for s in label_sources(x)))
        self.assertIn(2.11,[x['price'] for x in selected])

    def test_next_eligible_window_is_selected_after_nearest_remnant_is_omitted(self):
        bars=self.bars()
        bars.insert(20,bar(20.5,2.9,3,1,1.1))
        selected=analyze(bars,current_price=1.735,enabled_types=['window'])
        self.assertEqual([x['price'] for x in selected],[2.11,3])

    def test_six_cent_gap_at_two_dollars_is_below_five_percent(self):
        bars=[bar(1,2.08,2.11,2.05,2.08),bar(2,1.96,1.99,1.94,1.96)]
        selected=analyze(bars,current_price=1.96,enabled_types=['gap'])
        self.assertEqual(selected,[])


class GapDisplayTests(unittest.TestCase):
    def upward(self, entry=7.99):
        return [bar(1,9,10,8,9),bar(2,4.5,5,4,4.5),bar(3,7.5,entry,4,min(7.8,entry))]

    def test_tiny_original_gap_is_omitted_even_when_unfilled_or_filled(self):
        bars=[bar(1,2.10,2.20,2.05,2.10),bar(2,2.01,2.03,2,2.01)]
        for data in (bars,bars+[bar(3,2.03,2.10,2,2.08)]):
            with self.subTest(filled=len(data)>2):
                self.assertEqual(analyze(data,current_price=2.04,enabled_types=['gap']),[])

    def test_narrow_upward_remnant_keeps_only_original_full_fill_target(self):
        selected=analyze(self.upward(),current_price=7.9,enabled_types=['gap'])
        self.assertEqual([x['price'] for x in selected],[8])
        target=selected[0]
        self.assertEqual(target['time'],1)
        self.assertIn('Gap fill target',drawing_label(target))
        self.assertNotIn('Gap entry',drawing_label(target))
        c=target['corridor']
        self.assertEqual((c['low'],c['high'],c['remaining_low']),(5,8,7.99))
        self.assertEqual(c['state'],'partial')
        self.assertEqual(c['display_mode'],'fill_target_only')
        self.assertIn('Only the full-fill boundary is drawn',explanation(target,7.9))

    def test_narrow_downward_remnant_keeps_original_lower_target(self):
        bars=[bar(1,4,5,3,4),bar(2,9,10,8,9),bar(3,6,9,5.01,6)]
        selected=analyze(bars,current_price=5.1,enabled_types=['gap'])
        self.assertEqual([x['price'] for x in selected],[5])
        self.assertEqual(selected[0]['time'],1)
        self.assertIn('Gap fill target down',drawing_label(selected[0]))
        self.assertEqual(selected[0]['corridor']['remaining_high'],5.01)

    def test_small_fraction_can_still_draw_pair_when_width_is_meaningful(self):
        selected=analyze(self.upward(7.55),current_price=7.9,enabled_types=['gap'])
        self.assertEqual([x['price'] for x in selected],[7.55,8])
        self.assertLess((8-7.55)/(8-5),.25)
        self.assertEqual(selected[0]['corridor']['display_mode'],'pair')

    def test_exact_original_and_remaining_price_thresholds_qualify(self):
        bars=[bar(1,2.05,2.10,2,2.05),bar(2,1.88,1.90,1.85,1.88)]
        self.assertEqual([x['price'] for x in analyze(bars,current_price=1.95,enabled_types=['gap'])],
                         [1.90,2])
        selected=analyze(self.upward(7.60),current_price=7.9,enabled_types=['gap'])
        self.assertEqual([x['price'] for x in selected],[7.60,8])
        c=dict(low=.475,high=.50,remaining_low=.475,remaining_high=.50)
        self.assertTrue(gap_width_filter(c,lambda p:.01)['eligible'])

    def test_variable_tick_ladder_at_original_upper_edge_filters_gap(self):
        bars=[bar(1,10.1,10.2,10,10.1),bar(2,9.3,9.4,9.2,9.3)]
        self.assertEqual(len(analyze(bars,current_price=9.7,enabled_types=['gap'])),2)
        self.assertEqual(analyze(bars,current_price=9.7,enabled_types=['gap'],
                                 variable_tick_size='0.01 10 0.5'),[])

    def test_far_single_target_is_suppressed_in_gap_only_selection(self):
        self.assertEqual(analyze(self.upward(),current_price=2,enabled_types=['gap']),[])

    def test_selection_falls_back_after_far_target_is_suppressed(self):
        bars=self.upward()+[bar(4,2,2.1,1.9,2)]
        selected=analyze(bars,current_price=2,enabled_types=['gap'])
        self.assertEqual([x['price'] for x in selected],[2.1,4])

    def test_quote_crossed_target_and_measured_fill_have_distinct_labels(self):
        for today in (None,bar(4,7.9,8.2,7.5,8.1)):
            selected=analyze(self.upward(),current_price=8.1,enabled_types=['gap'],current_day=today)
            self.assertEqual([x['price'] for x in selected],[8] if today is None else [5,8])
            target=selected[-1]
            self.assertIn('Gap fill ref' if today is None else 'Filled gap high',drawing_label(target))
            self.assertNotIn('target',drawing_label(target))
            self.assertEqual(selected[0]['corridor']['state'],
                             'crossed_quote' if today is None else 'traversed_today')

    def test_merged_single_target_retains_its_actual_price_date_and_corridor(self):
        pm=dict(price=8.001,time=4,kind='premarket_high',description='PM high')
        selected=analyze(self.upward(),current_price=7.9,enabled_types=['gap','premarket_high'],extra_levels=[pm])
        self.assertEqual([x['price'] for x in selected],[8.001])
        sources=label_sources(selected[0])
        gap=next(x for x in sources if x['kind']=='gap')
        self.assertEqual((gap['price'],gap['time']),(8,1))
        self.assertFalse(any('entry' in x['text'].lower() for x in sources))
        self.assertEqual(selected[0]['corridors'][0]['display_mode'],'fill_target_only')
        text=explain_level(selected[0],7.9,sources)
        self.assertIn('Only the full-fill boundary is drawn',text)
        self.assertIn('Their individual source prices',text)


if __name__=='__main__':
    unittest.main()
