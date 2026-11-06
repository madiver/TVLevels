"""Causal participation evidence for intraday price reactions.

These are initial engineering filters, not evidence of trader identity/intent.
Only preceding candles in the same premarket/regular/after-hours phase supply
baselines. No full-session totals or candles after confirmation are used.
"""
from bisect import bisect_left, bisect_right
from datetime import datetime
from statistics import median
from zoneinfo import ZoneInfo
import math

MIN_SHARES_PER_MINUTE = 100
MIN_DOLLARS_PER_MINUTE = 500
BASELINE_BARS = 20
MIN_BASELINE_BARS = 5
ELEVATED_RATIO = 1.5
NY = ZoneInfo('America/New_York')


def phase(timestamp):
    t = datetime.fromtimestamp(timestamp, NY)
    minute = t.hour * 60 + t.minute
    return t.date(), 'premarket' if minute < 570 else 'regular' if minute < 960 else 'afterhours'


class ReactionVolume:
    def __init__(self, bars, bar_seconds=60):
        if bar_seconds not in (60,300):raise ValueError('Unsupported reaction timeframe')
        self.bar_seconds=bar_seconds
        self.minutes=bar_seconds/60
        self.bars = bars
        self.times = [b['time'] for b in bars]
        for b in bars:
            volume = b.get('volume')
            if volume is not None and (not isinstance(volume, (int, float)) or not math.isfinite(volume) or volume < 0):
                raise ValueError('Invalid one-minute reaction volume')

    def measure(self, extreme_time, confirmed_at):
        first = bisect_left(self.times, extreme_time)
        last = bisect_right(self.times, confirmed_at)
        # Fixed short window around the extreme; late confirmation does not
        # retroactively turn the entire approach into reaction participation.
        reaction = self.bars[first:min(first + 4, last)]
        reversal = reaction[1:]
        def activity(bars):
            if not bars or any(b.get('volume') is None for b in bars):
                return dict(available=False, shares_per_minute=None, dollars_per_minute=None, eligible=False)
            shares = sum(b['volume'] for b in bars) / (len(bars)*self.minutes)
            dollars = sum(b['volume'] * (b['high']+b['low']+b['close'])/3 for b in bars) / (len(bars)*self.minutes)
            return dict(available=True, shares_per_minute=shares, dollars_per_minute=dollars,
                        eligible=shares >= MIN_SHARES_PER_MINUTE and dollars >= MIN_DOLLARS_PER_MINUTE)
        combined, away = activity(reaction), activity(reversal)
        # Stop at a session-phase boundary, missing minute, or absent volume.
        prior = []
        next_time = extreme_time
        for b in reversed(self.bars[max(0, first-BASELINE_BARS):first]):
            if next_time-b['time'] != self.bar_seconds or phase(b['time']) != phase(extreme_time) or b.get('volume') is None:
                break
            prior.append(b['volume']/self.minutes); next_time=b['time']
        usual = median(prior) if len(prior) >= MIN_BASELINE_BARS else None
        ratio = combined['shares_per_minute']/usual if usual and combined['available'] else None
        reversal_ratio = away['shares_per_minute']/usual if usual and away['available'] else None
        # Crossing the open/close does not earn a mismatched relative-volume bonus.
        same_phase = all(phase(b['time']) == phase(extreme_time) for b in reaction)
        if not same_phase:
            ratio = reversal_ratio = None
        complete_volume = all(b.get('volume') is not None for b in self.bars[first:last])
        return dict(eligible=complete_volume and combined['eligible'] and away['eligible'],
                    reaction=combined, reversal=away, baseline_bars=len(prior), baseline_median=usual,
                    relative_volume=ratio, reversal_relative_volume=reversal_ratio,
                    elevated=ratio is not None and ratio >= ELEVATED_RATIO,
                    from_time=extreme_time, through_time=reaction[-1]['time'] if reaction else None,
                    phase=phase(extreme_time)[1], baseline_method='preceding_same_phase_minutes',bar_seconds=self.bar_seconds,
                    thresholds=dict(minimum_shares_per_minute=MIN_SHARES_PER_MINUTE,
                                    minimum_dollars_per_minute=MIN_DOLLARS_PER_MINUTE,
                                    elevated_ratio=ELEVATED_RATIO, baseline_bars=BASELINE_BARS,
                                    minimum_baseline_bars=MIN_BASELINE_BARS))


def zone_volume(evidence):
    measured = [e['volume'] for e in evidence]
    ratios = [e['relative_volume'] for e in measured if e['relative_volume'] is not None]
    return dict(elevated_tests=sum(e['elevated'] for e in measured),
                measured_tests=len(ratios), maximum_relative_volume=max(ratios) if ratios else None)


def volume_priority(zone):
    # Bounded bonus: one exceptional print cannot outweigh arbitrary distance.
    info = zone['volume']
    return (info['elevated_tests'] > 0, min(2, info['elevated_tests']))
