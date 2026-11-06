import copy
import json
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from daily_levels import run
from level_styles import LIGHT_COLORS, drawing_style, theme_color, theme_legend
from level_theme import apply_drawing_theme
from pane_client import PaneClient
from test_pane_client import Fixture
import test_failed_rallies as rallies
from theme_settings import read_theme


class ThemeStyleTests(unittest.TestCase):
    def test_light_colors_are_readable_on_white(self):
        for color in set(LIGHT_COLORS.values()):
            channels=[int(color[i:i+2],16)/255 for i in (1,3,5)]
            linear=[v/12.92 if v<=.04045 else ((v+.055)/1.055)**2.4 for v in channels]
            luminance=sum(a*b for a,b in zip(linear,(.2126,.7152,.0722)))
            self.assertGreaterEqual(1.05/(luminance+.05),4.5,color)

    def test_theme_preserves_style_and_meaning_for_all_categories(self):
        from level_catalog import LEVEL_TYPES
        for kind in LEVEL_TYPES:
            for quote in (5,7):
                level=dict(kind=kind,price=6)
                dark=drawing_style(level,quote,theme='dark')
                light=drawing_style(level,quote,theme='light')
                self.assertEqual(light['color'],theme_color(dark['color'],'light'))
                for key in ('linestyle','line_style','linewidth','style_family'):
                    self.assertEqual(dark[key],light[key])
                self.assertNotEqual(light['color'],dark['color'])

    def test_rally_groups_and_reclaimed_shades_remain_distinct(self):
        for state in ('active','reclaimed'):
            colors=[drawing_style(dict(kind='failed_rally',price=6,state=state,rally_color_index=i),7,theme='light')['color'] for i in range(5)]
            self.assertEqual(len(set(colors)),5)
        self.assertEqual(theme_legend('light')[0]['colors'],[theme_color(c,'light') for c in theme_legend('dark')[0]['colors']])

    def test_theme_preference_defaults_and_round_trips(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.assertEqual(read_theme(root),'dark')
            path=root/'.local/panel/theme.json';path.parent.mkdir(parents=True)
            path.write_text('{"theme":"light"}')
            self.assertEqual(read_theme(root),'light')
            path.write_text('{"theme":"invalid"}')
            with self.assertRaises(ValueError):read_theme(root)


class RestyleTests(unittest.TestCase):
    def setUp(self):
        self.client=Fixture()
        self.client.details_path=Path(self.client.tmp.name)/'details.json'
        self.drawn=run(self.client,enabled_types=['gap','resistance'])

    def tearDown(self):self.client.close()

    def saved(self):return json.loads(self.client.details_path.read_text())[self.drawn['scope']]

    def test_restyle_round_trip_preserves_geometry_ids_manual_and_other_pane(self):
        self.client.call('ui_evaluate',expression="window.TradingViewApi._activeChartWidgetWV.value().createShape({price:3,time:1},{text:'Manual',overrides:{color:'#123456'},disableUndo:true})")
        before=self.client.send(op='snapshot')
        original=self.saved()
        apply_drawing_theme(self.client,'light')
        after=self.client.send(op='snapshot')
        self.assertEqual(after['panes'][1],before['panes'][1])
        self.assertEqual(after['panes'][0]['resolution'],before['panes'][0]['resolution'])
        self.assertEqual(after['panes'][0]['session'],before['panes'][0]['session'])
        for (old_id,old),(new_id,new) in zip(before['panes'][0]['shapes'],after['panes'][0]['shapes']):
            self.assertEqual(old_id,new_id)
            self.assertEqual(old.get('points'),new.get('points'))
            self.assertEqual(old['props']['text'],new['props']['text'])
            if old['props']['text']=='Manual':self.assertEqual(old,new)
        current=self.saved()
        for key in ('drawn_at','reference','context','enabled_types'):
            self.assertEqual(current[key],original[key])
        self.assertEqual(current['drawing_theme'],'light')
        apply_drawing_theme(self.client,'dark')
        self.assertEqual(self.client.send(op='snapshot')['panes'][0]['shapes'],before['panes'][0]['shapes'])

    def test_manual_edits_are_preserved_and_role_uses_draw_quote(self):
        eid=self.drawn['levels'][0]['entity_id']
        self.client.call('ui_evaluate',expression=f"(()=>{{const s=window.TradingViewApi._activeChartWidgetWV.value().getShapeById('{eid}');s.getPoints()[0].price=500;s.getProperties().text='Edited label';}})()")
        before=self.client.send(op='snapshot')
        apply_drawing_theme(self.client,'light')
        after=self.client.send(op='snapshot')
        old=dict(before['panes'][0]['shapes'])[eid]
        new=dict(after['panes'][0]['shapes'])[eid]
        self.assertEqual(old['points'],new['points'])
        self.assertEqual(new['props']['text'],'Edited label')
        self.assertEqual(new['props']['linecolor'],drawing_style(self.drawn['levels'][0],self.drawn['reference']['price'],theme='light')['color'])

    def test_unowned_record_and_deleted_drawing_are_not_modified(self):
        owned=json.loads(self.client.ownership_path.read_text())
        eid=owned[self.drawn['scope']].pop()
        self.client.ownership_path.write_text(json.dumps(owned))
        before=dict(self.client.send(op='snapshot')['panes'][0]['shapes'])[eid]
        apply_drawing_theme(self.client,'light')
        self.assertEqual(dict(self.client.send(op='snapshot')['panes'][0]['shapes'])[eid],before)
        b=PaneClient(self.client)
        try:b.call('draw_remove_one',entity_id=eid)
        finally:b.release()
        apply_drawing_theme(self.client,'dark')
        self.assertNotIn(eid,dict(self.client.send(op='snapshot')['panes'][0]['shapes']))

    def test_scope_change_rejects_before_mutation(self):
        before=self.client.send(op='snapshot')
        with self.assertRaisesRegex(RuntimeError,'Selected chart changed'):
            apply_drawing_theme(self.client,'light','different|scope')
        self.assertEqual(self.client.send(op='snapshot'),before)

    def test_mid_update_failure_rolls_back_all_colors(self):
        before=self.client.send(op='snapshot');metadata=self.client.details_path.read_bytes()
        self.client.send(op='failRestyle',at=2)
        with self.assertRaisesRegex(RuntimeError,'injected restyle failure'):
            apply_drawing_theme(self.client,'light')
        after=self.client.send(op='snapshot')
        self.assertEqual(after['panes'][0]['shapes'],before['panes'][0]['shapes'])
        self.assertEqual(after['panes'][1],before['panes'][1])
        self.assertEqual(self.client.details_path.read_bytes(),metadata)

    def test_pane_change_mid_update_rolls_back_original_without_redirecting(self):
        before=self.client.send(op='snapshot')
        self.client.send(op='switchDuringRestyle')
        with self.assertRaisesRegex(RuntimeError,'Selected chart pane changed'):
            apply_drawing_theme(self.client,'light')
        after=self.client.send(op='snapshot')
        self.assertEqual(after['panes'][0]['shapes'],before['panes'][0]['shapes'])
        self.assertEqual(after['panes'][1],before['panes'][1])

    def test_metadata_write_failure_rolls_back_colors(self):
        before=self.client.send(op='snapshot')
        with patch('level_theme.save_details',side_effect=OSError('disk full')):
            with self.assertRaisesRegex(OSError,'disk full'):apply_drawing_theme(self.client,'light')
        self.assertEqual(self.client.send(op='snapshot')['panes'][0]['shapes'],before['panes'][0]['shapes'])

    def test_color_operation_rejects_non_color_properties(self):
        b=PaneClient(self.client)
        try:
            with self.assertRaisesRegex(ValueError,'only change drawing colors'):
                b.call('draw_restyle',patches=[dict(entity_id=self.drawn['levels'][0]['entity_id'],properties=dict(text='Replace'))])
        finally:b.release()

    def test_new_draw_uses_requested_theme(self):
        result=run(self.client,enabled_types=['resistance'],theme='light')
        self.assertEqual(result['drawing_theme'],'light')
        for level in result['levels']:
            self.assertEqual(level['color'],drawing_style(level,result['reference']['price'],theme='light')['color'])

    def test_grouped_ovals_and_labels_use_themed_colors_and_preserve_evidence(self):
        values=[[b['time'],*[b[k]*5 for k in ('open','high','low','close')],b['volume']] for b in rallies.attempts()]
        self.client.send(op='intraday',bars=values,end=True)
        result=run(self.client,enabled_types=['failed_rally'],now=rallies.START+timedelta(minutes=30))
        self.drawn=result
        old=copy.deepcopy(result['levels'][0])
        apply_drawing_theme(self.client,'light')
        level=self.saved()['levels'][0]
        self.assertEqual(level['failures'],old['failures'])
        self.assertEqual(level['entity_ids'],old['entity_ids'])
        shapes=dict(self.client.send(op='snapshot')['panes'][0]['shapes'])
        for mark in level['marks']:
            props=shapes[mark['entity_id']]['props']
            self.assertEqual(props['color'],level['border_color'] if mark['shape']=='ellipse' else level['color'])
            self.assertEqual(json.loads(mark['overrides'])['color'],props['color'])
            self.assertEqual(shapes[mark['entity_id']]['points'],next(m for m in old['marks'] if m['entity_id']==mark['entity_id']).get('points') or [old['marks'][-1]['point']])


if __name__=='__main__':unittest.main()
