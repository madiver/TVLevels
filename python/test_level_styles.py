import json
import unittest
from itertools import combinations
from level_styles import drawing_style, SESSION_COLOR, CLOSE_COLOR, RALLY_COLOR, category_appearance, assign_rally_colors, RALLY_PALETTE
from level_catalog import LEVEL_TYPES
from daily_levels import run, spaced_levels, label_sources
from level_explanations import explain_level
from test_daily_levels import Fake, bar
from test_reference_levels import at, candle


def level(kind,price=6):
    return dict(kind=kind,price=price,time=1,description=kind)

class StyleTests(unittest.TestCase):
    def test_rally_groups_have_distinct_quote_independent_colors_and_reclaimed_shades(self):
        groups = [dict(kind='failed_rally', price=6+i, state='failed',
                       failures=[dict(peak_time=10+i, peak=6+i)]) for i in range(5)]
        assign_rally_colors(list(reversed(groups)))
        self.assertEqual([g['rally_color_index'] for g in groups], list(range(5)))
        active = [drawing_style(g, 7) for g in groups]
        self.assertEqual(len({s['color'] for s in active}), 5)
        self.assertEqual(len({s['border_color'] for s in active}), 5)
        for i, group in enumerate(groups):
            self.assertEqual(drawing_style(group, 20), active[i])
            group['state'] = 'reclaimed'
            shade = drawing_style(group, 20)
            self.assertEqual(shade['color'], RALLY_PALETTE[i][3])
            self.assertEqual(shade['border_color'], RALLY_PALETTE[i][4])
            self.assertEqual(shade['rally_color_name'], active[i]['rally_color_name'])
            group['state'] = 'returned_below'
            self.assertEqual(drawing_style(group, 20), active[i])
    def test_all_categories_have_matching_family_style_on_both_sides(self):
        fixed={'premarket_high':('#ff00ff',0),'premarket_low':('#ff00ff',0),
               'previous_high':(SESSION_COLOR,2),'previous_low':(SESSION_COLOR,2),
               'previous_close':(CLOSE_COLOR,1),'previous_open':(CLOSE_COLOR,2),'day_high':(SESSION_COLOR,0),'day_low':(SESSION_COLOR,0),'failed_rally':(RALLY_COLOR,0),'support_zone':('#66bb6a',0),'ascending_support':('#66bb6a',1),'descending_resistance':('#d18b32',1)}
        for kind in LEVEL_TYPES:
            for quote in (5,6,7):
                with self.subTest(kind=kind,quote=quote):
                    style=drawing_style(level(kind),quote)
                    expected=fixed.get(kind)
                    if expected is None:
                        prior=kind.startswith('former_')
                        expected=('#00e676' if prior and quote>6 else '#ffb74d' if prior else '#66bb6a' if quote>6 else '#d18b32',1 if kind in ('gap','window') else 2)
                    self.assertEqual((style['color'],style['linestyle']),expected)
                    self.assertEqual(style['linewidth'],2 if kind in ('failed_rally','support_zone') else 1)
                    self.assertTrue(category_appearance(kind))
    def test_merge_precedence_does_not_depend_on_highest_price_representative(self):
        order=['premarket_high','former_support','resistance','gap','day_high','previous_high','previous_close']
        families=['premarket','prior','daily','corridor','day_range','previous_range','previous_close']
        for early,late in combinations(range(len(order)),2):
            for flip in (False,True):
                inputs=[level(order[early],6 if flip else 6.01),level(order[late],6.01 if flip else 6)]
                merged=spaced_levels(inputs)[0]
                self.assertEqual(drawing_style(merged,7,label_sources(merged))['style_family'],families[early])
                self.assertEqual({s['kind'] for s in label_sources(merged)},{order[early],order[late]})
    def test_repeated_merge_keeps_prior_precedence_over_corridor_and_sessions(self):
        merged=spaced_levels([level('former_resistance',6),level('gap',6.01)])[0]
        twice=spaced_levels([merged,level('day_low',6.015)])[0]
        self.assertEqual(drawing_style(twice,7,label_sources(twice))['style_family'],'prior')
    def test_session_explanations_identify_source_color_instead_of_price_role(self):
        for kind,words in [('previous_high','cyan and dashed'),('day_low','cyan and solid'),('previous_close','gray and dotted'),('premarket_low','fuchsia and solid')]:
            text=explain_level(level(kind),7,label_sources(level(kind)))
            self.assertIn(words,text);self.assertNotIn('so it is green',text)
    def test_corridor_and_prior_explanations_match_their_rendered_style(self):
        text=explain_level(level('window'),7,label_sources(level('window')))
        self.assertIn('green and dotted',text)
        text=explain_level(level('former_resistance'),5,label_sources(level('former_resistance')))
        self.assertIn('brighter orange and dashed',text)
    def test_merged_explanation_names_the_winning_family(self):
        merged=spaced_levels([level('previous_close'),level('previous_high',6.01)])[0]
        text=explain_level(merged,7,label_sources(merged))
        self.assertIn('Previous-session range styling takes precedence',text)
        self.assertIn('cyan and dashed',text);self.assertIn('$6.00',text)
    def test_actual_draw_overrides_and_saved_metadata_use_identical_session_styles(self):
        class Drawing(Fake):
            def __init__(self):super().__init__();self.styles=[]
            def call(self,name,**args):
                if name=='data_get_ohlcv':return {'bars':[candle('2026-10-05',4,6)] if self.resolution=='1D' else [candle('2026-10-06',4.2,5.8)]}
                if name=='draw_shape':self.styles.append(json.loads(args['overrides']))
                return super().call(name,**args)
        client=Drawing();client.session='extended'
        enabled=['previous_high','previous_low','previous_close','day_high','day_low']
        result=run(client,enabled_types=enabled,now=at('2026-10-06'))
        self.assertEqual(len(result['levels']),5)
        for item,style in zip(result['levels'],client.styles):
            self.assertEqual(style['linecolor'],item['color'])
            self.assertEqual(style['textcolor'],item['color'])
            self.assertEqual(style['linestyle'],item['linestyle'])
            self.assertEqual(style['linewidth'],1)
        self.assertEqual(client.resolution,'5');self.assertEqual(client.session,'extended')
    def test_disabled_daily_category_does_not_override_session_style(self):
        # The spacing stage receives only enabled references: no hidden category styling.
        session=spaced_levels([level('day_high',6)])[0]
        self.assertEqual(drawing_style(session,7,label_sources(session))['style_family'],'day_range')

if __name__=='__main__':unittest.main()
