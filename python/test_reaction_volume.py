import unittest
from datetime import timedelta

from reaction_volume import ReactionVolume
from failed_rallies import failed_rally_zones
from support_zones import support_zones
from level_explanations import explain_level
from daily_levels import label_sources, run
from test_failed_rallies import START, candle, attempts
import test_failed_rallies as rallies
from test_support_zones import attempts as holds


def prefix():
    return [candle(m,1,1.001,.999,1) for m in range(-20,0)]


class ReactionVolumeTests(unittest.TestCase):
    def detectors(self):
        return ((failed_rally_zones,attempts,1.02,'failures','peak_time','failed_at'),
                (support_zones,holds,.98,'holds','trough_time','confirmed_at'))

    def detect(self, detector, bars, quote):
        return detector(bars,quote,START+timedelta(minutes=90),lambda p:.0001)

    def test_invalid_volume_stops_workflow_before_replacing_drawings(self):
        client=rallies.WorkflowTests.Client()
        client.bars[2]['volume']=-1
        with self.assertRaisesRegex(ValueError,'reaction volume'):
            run(client,enabled_types=['failed_rally'],now=START+timedelta(minutes=30))
        self.assertFalse(any(n.startswith('draw_') for n,a in client.calls))
        self.assertEqual((client.resolution,client.session),('5','regular'))

    def test_liquid_tests_without_baseline_still_qualify_without_bonus(self):
        for detector,make,quote,key,_,_ in self.detectors():
            with self.subTest(key=key):
                z=self.detect(detector,make(),quote)[0]
                self.assertEqual(z['independent_tests'],2)
                self.assertEqual(z['volume']['measured_tests'],0)
                self.assertEqual(z['volume']['elevated_tests'],0)
                self.assertIsNone(z[key][0]['volume']['relative_volume'])

    def test_missing_zero_tiny_and_invalid_volume(self):
        for detector,make,quote,key,_,_ in self.detectors():
            for volume in (None,0,1,99,400):
                with self.subTest(key=key,volume=volume):
                    self.assertFalse(self.detect(detector,[dict(b,volume=volume) for b in make()],quote))
            for volume in (-1,float('nan'),float('inf'),'unknown'):
                with self.subTest(key=key,volume=volume):
                    with self.assertRaises(ValueError):
                        self.detect(detector,[dict(b,volume=volume) for b in make()],quote)

    def test_high_extreme_volume_cannot_hide_illiquid_reversal(self):
        for detector,make,quote,key,_,_ in self.detectors():
            bars=make()
            for i in (1,3):bars[i]['volume']=100000
            for i in (2,4):bars[i]['volume']=1
            self.assertFalse(self.detect(detector,bars,quote))

    def test_two_qualified_tests_required_after_thin_test_is_removed(self):
        for detector,make,quote,key,_,confirmation in self.detectors():
            prices=(1.04,1.04,1.04) if key=='failures' else (.96,.96,.96)
            bars=make(prices)
            bars[1]['volume']=bars[2]['volume']=1
            self.assertFalse(self.detect(detector,bars[:5],quote))
            z=self.detect(detector,bars,quote)[0]
            self.assertEqual(z['independent_tests'],2)
            self.assertEqual(z['qualified_at'],bars[6]['time'])
            self.assertEqual(z[key][0][confirmation],bars[4]['time'])

    def test_relative_volume_measured_with_quieter_second_test_retained(self):
        for detector,make,quote,key,_,_ in self.detectors():
            bars=prefix()+make()
            for i in (-4,-3):bars[i]['volume']=2000
            z=self.detect(detector,bars,quote)[0]
            self.assertEqual(z['volume']['elevated_tests'],1)
            self.assertEqual(z['volume']['measured_tests'],2)
            self.assertAlmostEqual(z[key][0]['volume']['relative_volume'],2)
            self.assertAlmostEqual(z[key][1]['volume']['relative_volume'],1)
            text=explain_level(z,quote,label_sources(z))
            self.assertIn('2.00×',text)
            self.assertIn('1 of 2',text)
            self.assertIn('not historical same-clock-time',text)

    def test_elevated_boundary_and_zero_baseline(self):
        bars=prefix()+attempts()
        for b in bars[-4:]:b['volume']=1500
        self.assertTrue(ReactionVolume(bars).measure(bars[-4]['time'],bars[-3]['time'])['elevated'])
        bars[-4]['volume']=1499
        self.assertFalse(ReactionVolume(bars).measure(bars[-4]['time'],bars[-3]['time'])['elevated'])
        for b in bars[:-5]:b['volume']=0
        v=ReactionVolume(bars).measure(bars[-4]['time'],bars[-3]['time'])
        self.assertTrue(v['eligible']);self.assertIsNone(v['relative_volume'])
        self.assertFalse(v['elevated'])

    def test_missing_minutes_and_session_boundaries_reset_baseline(self):
        bars=prefix()+attempts()
        # A gap inside the nearest five preceding bars prevents a ratio.
        v=ReactionVolume(bars[15:19]+bars[20:]).measure(bars[21]['time'],bars[22]['time'])
        self.assertIsNone(v['relative_volume'])
        shift=210*60  # 06:00 -> 09:30
        shifted=[dict(b,time=b['time']+shift) for b in prefix()+attempts()]
        v=ReactionVolume(shifted).measure(shifted[21]['time'],shifted[22]['time'])
        self.assertIsNone(v['relative_volume'])
        self.assertEqual(v['phase'],'regular')
        # Peak before the open followed by a reversal after it: no mismatched bonus.
        shifted=[dict(b,time=b['time']+shift-120) for b in prefix()+attempts()]
        v=ReactionVolume(shifted).measure(shifted[21]['time'],shifted[22]['time'])
        self.assertTrue(v['eligible']);self.assertIsNone(v['relative_volume'])

    def test_share_and_dollar_floors_are_independent(self):
        for price,volume in ((10,99),(.01,1000)):
            bars=[dict(candle(m,price,price,price,price),volume=volume) for m in range(2)]
            v=ReactionVolume(bars).measure(bars[0]['time'],bars[-1]['time'])
            self.assertFalse(v['eligible'])

    def test_late_confirmation_cannot_use_future_volume_or_missing_volume(self):
        bars=[candle(m,1,1,1,1) for m in range(10)]
        bars[-1]['volume']=100000
        before=ReactionVolume(bars[:6]).measure(bars[0]['time'],bars[5]['time'])
        after=ReactionVolume(bars).measure(bars[0]['time'],bars[5]['time'])
        self.assertEqual(before,after)
        self.assertEqual(after['through_time'],bars[3]['time'])
        bars[5]['volume']=None
        self.assertFalse(ReactionVolume(bars).measure(bars[0]['time'],bars[5]['time'])['eligible'])

    def test_future_volume_does_not_rewrite_confirmed_evidence(self):
        for detector,make,quote,key,_,_ in self.detectors():
            bars=prefix()+make()
            before=self.detect(detector,bars,quote)[0]
            later=bars+[candle(5,1.01,1.011,1.009,1.01)]
            later[-1]['volume']=1000000
            after=self.detect(detector,later,quote)[0]
            self.assertEqual(before[key],after[key])
            self.assertEqual(before['volume'],after['volume'])

    def test_volume_bonus_can_select_comparable_zone_without_exceeding_caps(self):
        for detector,make,quote,key,_,_ in self.detectors():
            prices=(1.04,1.04,1.046,1.046,1.052,1.052,1.058,1.058) if key=='failures' else (.96,.96,.954,.954,.948,.948,.942,.942)
            ordinary=prefix()+make(prices)
            bars=[dict(b) for b in ordinary]
            for b in bars[-4:]:b['volume']=4000
            before=self.detect(detector,ordinary,quote)
            after=self.detect(detector,bars,quote)
            self.assertEqual(len(after),3)
            self.assertFalse(any(z['volume']['elevated_tests'] for z in before))
            self.assertTrue(any(z['volume']['elevated_tests']==2 for z in after))
            self.assertNotEqual([z['price'] for z in before],[z['price'] for z in after])


if __name__=='__main__':unittest.main()
