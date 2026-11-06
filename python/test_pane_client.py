import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from daily_levels import run, clear_levels
from pane_client import PaneClient

class Fixture:
    def __init__(self):
        self.process=subprocess.Popen(['node',str(Path(__file__).with_name('pane_fixture.mjs'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True)
        self.tmp=tempfile.TemporaryDirectory()
        self.ownership_path=Path(self.tmp.name)/'owned.json'
    def send(self, **q):
        self.process.stdin.write(json.dumps(q)+'\n');self.process.stdin.flush()
        r=json.loads(self.process.stdout.readline())
        if 'error' in r:raise RuntimeError(r['error'])
        return r['result']
    def call(self,name,**args):
        assert name=='ui_evaluate'
        return {'result':self.send(op='evaluate',**args)}
    def bind_selected(self):return PaneClient(self)
    def close(self):
        self.process.terminate();self.process.wait();self.process.stdin.close();self.process.stdout.close();self.tmp.cleanup()

class PaneTests(unittest.TestCase):
    def setUp(self):self.client=Fixture()
    def tearDown(self):self.client.close()
    def test_selected_pane_only_and_timeframe_restored(self):
        result=run(self.client)
        s=self.client.send(op='snapshot')
        self.assertEqual(result['pane']['pane_id'],'1')
        self.assertEqual(s['panes'][0]['resolution'],'5')
        self.assertEqual(s['panes'][0]['session'],'regular')
        self.assertEqual(s['panes'][1]['writes'],[])
        self.assertEqual(s['panes'][1]['shapes'],[])
        self.assertTrue(all(v['link'] is None for _,v in s['panes'][0]['shapes']))
    def test_same_symbol_panes_have_separate_ownership_and_reruns(self):
        run(self.client);original=self.client.send(op='snapshot')['panes'][0]['shapes']
        self.client.send(op='select',index=1);run(self.client);run(self.client)
        s=self.client.send(op='snapshot')
        self.assertEqual(s['panes'][0]['shapes'],original)
        self.assertEqual(len(s['panes'][1]['shapes']),len(original))
        self.assertEqual(len(json.loads(self.client.ownership_path.read_text())),2)
    def test_selection_change_during_async_create_rolls_back_and_restores_original(self):
        self.client.send(op='switchDuringCreate')
        with self.assertRaisesRegex(RuntimeError,'Selected chart pane changed'):run(self.client)
        s=self.client.send(op='snapshot')
        self.assertEqual(s['selected'],1)
        self.assertEqual(s['panes'][0]['resolution'],'5')
        self.assertEqual(s['panes'][0]['shapes'],[])
        self.assertEqual(s['panes'][1]['writes'],[])
    def test_selection_change_before_mutation_is_rejected(self):
        bound=PaneClient(self.client);self.client.send(op='select',index=1)
        with self.assertRaisesRegex(RuntimeError,'Selected chart pane changed'):bound.call('chart_set_timeframe',timeframe='1D')
        self.assertEqual(self.client.send(op='snapshot')['panes'][1]['writes'],[])
        bound.release()

    def test_tab_change_rejects_new_writes_but_allows_original_pane_restoration(self):
        bound=PaneClient(self.client)
        bound.call('chart_set_timeframe',timeframe='1')
        self.client.send(op='visibility',state='hidden')
        before=self.client.send(op='snapshot')
        with self.assertRaisesRegex(RuntimeError,'TradingView tab changed'):
            bound.call('draw_shape',shape='horizontal_line',point=dict(time=1,price=3),text='New level',overrides='{}')
        self.assertEqual(self.client.send(op='snapshot'),before)
        bound.allow_inactive=True
        bound.call('chart_set_timeframe',timeframe='5')
        self.assertEqual(self.client.send(op='snapshot')['panes'][0]['resolution'],'5')
        bound.release()
    def test_clear_preserves_manual_and_other_same_symbol_pane(self):
        run(self.client)
        self.client.send(op='select',index=1);run(self.client)
        other=self.client.send(op='snapshot')['panes'][1]
        self.client.send(op='select',index=0)
        self.client.call('ui_evaluate', expression="window.TradingViewApi._activeChartWidgetWV.value().createShape({price:3,time:1},{text:'Manual',disableUndo:true})")
        before=self.client.send(op='snapshot')
        result=clear_levels(self.client)
        after=self.client.send(op='snapshot')
        self.assertGreater(result['removed'],0)
        self.assertEqual(after['panes'][1],before['panes'][1])
        self.assertEqual(after['panes'][0]['resolution'],before['panes'][0]['resolution'])
        self.assertEqual([s['props']['text'] for _,s in after['panes'][0]['shapes']],['Manual'])
        self.assertEqual(clear_levels(self.client)['removed'],0)

    def test_clear_selection_change_rejects_without_redirecting(self):
        run(self.client)
        bound=PaneClient(self.client)
        self.client.send(op='select',index=1)
        before=self.client.send(op='snapshot')
        with self.assertRaisesRegex(RuntimeError,'Selected chart pane changed'):clear_levels(bound)
        self.assertEqual(self.client.send(op='snapshot'),before)

    def test_removed_pane_is_not_replaced_by_same_index(self):
        bound=PaneClient(self.client)
        self.client.call('ui_evaluate',expression='(()=>{window.TradingViewApi._chartWidgetCollection.getAll=()=>[];return true})()')
        with self.assertRaisesRegex(RuntimeError,'no longer exists'):bound.call('chart_get_state')
        bound.release()

    def pm_time(self,clock):
        return datetime.fromisoformat('2026-09-30T'+clock).replace(tzinfo=ZoneInfo('America/New_York'))

    def test_depositary_receipt_premarket_is_supported(self):
        self.client.send(op='symbolType',type='dr')
        bound=PaneClient(self.client)
        try:
            self.assertTrue(bound.call('session_snapshot')['premarket_supported'])
        finally:
            bound.release()

    def pm_bar(self,clock,low,high):
        return [self.pm_time(clock).timestamp(),low,high,low,(low+high)/2,10]

    def test_full_premarket_history_loaded_and_exact_levels_drawn(self):
        self.client.send(op='intraday',bars=[self.pm_bar('08:00',3,5),self.pm_bar('09:30',1,12)],
                         earlier=[self.pm_bar('03:55',2,10),self.pm_bar('04:00',2.5,7)])
        result=run(self.client,now=self.pm_time('10:00'),enabled_types=['premarket_high','premarket_low'])
        self.assertEqual([x['price'] for x in result['premarket']['levels']],[7,2.5])
        s=self.client.send(op='snapshot')
        self.assertIn(['history',500],s['panes'][0]['writes'])
        self.assertEqual(s['panes'][0]['session'],'regular')
        self.assertEqual(s['panes'][0]['resolution'],'5')
        self.assertEqual(s['panes'][1]['writes'],[])
        labels=[v['props']['text'] for _,v in s['panes'][0]['shapes']]
        self.assertIn('PM high',labels)
        self.assertIn('PM low',labels)
        clear_levels(self.client)
        self.assertEqual(self.client.send(op='snapshot')['panes'][0]['shapes'],[])

    def test_partial_history_is_rejected_and_no_drawings_changed(self):
        self.client.send(op='intraday',bars=[self.pm_bar('08:00',3,5)])
        with self.assertRaisesRegex(RuntimeError,'Full premarket history'):run(self.client,now=self.pm_time('10:00'))
        s=self.client.send(op='snapshot')
        self.assertEqual(s['panes'][0]['session'],'regular')
        self.assertEqual(s['panes'][0]['resolution'],'5')
        self.assertEqual(s['panes'][0]['shapes'],[])
        self.assertEqual(s['panes'][1]['writes'],[])

    def test_end_of_history_accepts_sparse_new_listing(self):
        self.client.send(op='intraday',bars=[self.pm_bar('08:00',3,5)],end=True)
        result=run(self.client,dry_run=True,now=self.pm_time('10:00'))
        self.assertEqual([x['price'] for x in result['premarket']['levels']],[5,3])

    def test_selection_change_during_session_switch_restores_original_pane(self):
        self.client.send(op='switchDuringSession')
        with self.assertRaisesRegex(RuntimeError,'Selected chart pane changed'):run(self.client,now=self.pm_time('10:00'))
        s=self.client.send(op='snapshot')
        self.assertEqual(s['panes'][0]['session'],'regular')
        self.assertEqual(s['panes'][0]['resolution'],'5')
        self.assertEqual(s['panes'][0]['shapes'],[])
        self.assertEqual(s['panes'][1]['writes'],[])
