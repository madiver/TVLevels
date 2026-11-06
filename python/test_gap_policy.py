"""Gap significance, historical preservation, and completed reaction evidence."""
import unittest
from daily_levels import analyze, drawing_label, label_sources, spaced_levels
from reaction_levels import gap_corridors
from gap_policy import gap_width_filter, historical_gap_evidence, historical_gap_rank
from level_explanations import explain_level


def bar(t, close, low, high):
    return dict(time=t, open=close, close=close, low=low, high=high, volume=100)


def filled():
    return [bar(1,9,8,10),bar(2,4.5,4,5),bar(3,8,5,9)]


class HistoricalGaps(unittest.TestCase):
    def test_dbgi_1_72_cent_original_is_omitted_open_and_filled(self):
        original=[bar(1,.705,.68,.75),bar(2,.5597,.55275,.6628)]
        for bars in (original,original+[bar(3,.7,.4904,.74)]):
            self.assertEqual(analyze(bars,current_price=1.01,enabled_types=['gap'],
                                    tick_size=.0001,variable_tick_size='0.0001 1 0.01'),[])
        c=gap_corridors(original)[0][0]['corridor']
        result=gap_width_filter(c,lambda p:.0001)
        self.assertAlmostEqual(result['original_minimum_width'],.034)
        self.assertFalse(result['eligible'])

    def test_significant_filled_gap_keeps_both_exact_sources_and_clear_labels(self):
        levels=analyze(filled(),current_price=8.1,enabled_types=['gap'])
        self.assertEqual([(x['price'],x['time']) for x in levels],[(5,2),(8,1)])
        self.assertTrue(drawing_label(levels[0]).startswith('Filled gap low'))
        self.assertTrue(drawing_label(levels[1]).startswith('Filled gap high'))
        self.assertTrue(all('target' not in drawing_label(x) for x in levels))
        c=levels[0]['corridor']
        self.assertEqual(c['filled_at'],3)
        self.assertEqual(c['display_mode'],'pair')
        self.assertIn('historical reference prices, not outstanding fill targets',
                      explain_level(levels[0],8.1,label_sources(levels[0])))

    def test_today_fill_restores_original_edges_after_narrow_upward_remnant(self):
        bars=filled()[:2]+[bar(3,7.8,4,7.99)]
        self.assertEqual([x['price'] for x in analyze(bars,current_price=7.9,enabled_types=['gap'])],[8])
        levels=analyze(bars,current_price=8.1,enabled_types=['gap'],current_day=bar(4,8.1,7.5,8.2))
        self.assertEqual([(x['price'],x['time']) for x in levels],[(5,2),(8,1)])
        self.assertTrue(all(x['corridor']['state']=='traversed_today' for x in levels))

    def test_today_fill_restores_original_edges_after_narrow_downward_remnant(self):
        bars=[bar(1,4,3,5),bar(2,9,8,10),bar(3,6,5.01,9)]
        levels=analyze(bars,current_price=4.9,enabled_types=['gap'],current_day=bar(4,4.9,4.8,6))
        self.assertEqual([(x['price'],x['time']) for x in levels],[(5,1),(8,2)])

    def test_original_threshold_applies_to_completed_fills_and_partial_remnants(self):
        c=dict(low=1.9,high=2,remaining_low=1.99,remaining_high=2)
        result=gap_width_filter(c,lambda p:.01)
        self.assertTrue(result['eligible'])
        self.assertEqual(result['display_mode'],'fill_target_only')
        result=gap_width_filter(c|dict(remaining_low=1.9),lambda p:.01)
        self.assertEqual(result['display_mode'],'pair')
        self.assertFalse(gap_width_filter(c|dict(low=1.90001),lambda p:.01)['eligible'])

    def test_adjacent_boundary_encounters_count_once(self):
        bars=filled()+[bar(4,8.03,7.99,8.05),bar(5,8.10,7.99,8.12),
                       bar(6,8.03,7.99,8.05),bar(7,8.3,8.2,8.4)]
        c=gap_corridors(bars)[0][0]['corridor']
        evidence=historical_gap_evidence(c,bars,lambda p:.01)
        self.assertEqual(evidence['independent_tests'],1)
        self.assertEqual(evidence['reactions'][0]['confirmed_at'],5)

    def test_move_away_allows_later_independent_confirmed_reaction(self):
        bars=filled()+[bar(4,8.03,7.99,8.05),bar(5,8.3,8.2,8.4),
                       bar(6,8.03,7.99,8.05),bar(7,8.3,8.2,8.4)]
        c=gap_corridors(bars)[0][0]['corridor']
        evidence=historical_gap_evidence(c,bars,lambda p:.01)
        self.assertEqual(evidence['independent_tests'],2)
        self.assertEqual([(r['price'],r['time'],r['confirmed_at']) for r in evidence['reactions']],
                         [(8,4,5),(8,6,7)])
        selected=analyze(bars,current_price=8.1,enabled_types=['gap'])
        self.assertEqual(selected[0]['corridor']['historical_evidence'],evidence)
        self.assertIn('2 independent daily boundary reactions',
                      explain_level(selected[0],8.1,label_sources(selected[0])))

    def test_fill_itself_and_unconfirmed_last_touch_cannot_count(self):
        bars=filled()+[bar(4,8.03,7.99,8.05)]
        c=gap_corridors(bars)[0][0]['corridor']
        self.assertEqual(historical_gap_evidence(c,bars,lambda p:.01)['independent_tests'],0)
        levels=analyze(bars,current_price=8.1,enabled_types=['gap'],current_day=bar(5,8.3,8.2,8.4))
        self.assertEqual(levels[0]['corridor']['historical_evidence']['independent_tests'],0)

    def test_both_edges_in_one_encounter_do_not_double_count(self):
        bars=filled()+[bar(4,7,4.99,8.01),bar(5,8.3,8.2,8.4)]
        c=gap_corridors(bars)[0][0]['corridor']
        self.assertEqual(historical_gap_evidence(c,bars,lambda p:.01)['independent_tests'],1)

    def test_reaction_requires_meaningful_completed_move(self):
        bars=filled()+[bar(4,8,7.99,8.01),bar(5,8.01,7.99,8.02)]
        c=gap_corridors(bars)[0][0]['corridor']
        self.assertEqual(historical_gap_evidence(c,bars,lambda p:.01)['independent_tests'],0)

    def test_recency_and_reactions_improve_rank_without_overwhelming_distance(self):
        def candidate(high=8,tests=0,age=10):
            return dict(low=high-1,high=high,source_time=1,
                        historical_evidence=dict(independent_tests=tests,fill_age_sessions=age))
        base=historical_gap_rank(candidate(),10)
        self.assertLess(historical_gap_rank(candidate(tests=2),10),base)
        self.assertLess(historical_gap_rank(candidate(age=1),10),base)
        self.assertGreater(historical_gap_rank(candidate(high=6,tests=20,age=0),10),base)
        self.assertEqual(historical_gap_rank(candidate(tests=3),10)[0],
                         historical_gap_rank(candidate(tests=20),10)[0])

    def test_merged_boundary_keeps_filled_label_and_exact_source(self):
        high=analyze(filled(),current_price=8.1,enabled_types=['gap'])[-1]
        merged=spaced_levels([high,dict(kind='premarket_high',price=8.001,time=4,description='PM high')])[0]
        gap=next(s for s in label_sources(merged) if s['kind']=='gap')
        self.assertEqual((gap['price'],gap['time'],gap['text']),(8,1,'Filled gap high'))
        self.assertEqual(merged['corridors'][0]['filled_at'],3)


if __name__=='__main__':unittest.main()
