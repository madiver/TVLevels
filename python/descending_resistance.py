"""Five-minute descending resistance with the shared fixed-anchor policy."""
from ascending_support import directional_trendline


def descending_resistance(bars,quote,now=None,tick=lambda p:.01):
    return directional_trendline(bars,quote,now,tick,-1)
