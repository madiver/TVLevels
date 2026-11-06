"""Display thresholds for exposed daily windows; these are automation choices."""
MIN_REMAINING_FRACTION = .25
MIN_PRICE_FRACTION = .05


def window_width_filter(corridor, tick_at_price):
    original = corridor['high'] - corridor['low']
    remaining = corridor['high'] - corridor['remaining_low']
    minimum = max(MIN_PRICE_FRACTION * corridor['high'],
                  2 * max(tick_at_price(corridor['remaining_low']),
                          tick_at_price(corridor['high'])))
    eligible = (original > 0 and
                remaining >= MIN_REMAINING_FRACTION * original - 1e-12 and
                remaining >= minimum - 1e-12)
    return dict(eligible=eligible, original_width=original, remaining_width=remaining,
                remaining_fraction=remaining / original if original > 0 else 0,
                minimum_width=minimum, min_remaining_fraction=MIN_REMAINING_FRACTION,
                min_price_fraction=MIN_PRICE_FRACTION)
