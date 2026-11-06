"""Gap display rules; original significance and remaining width are separate."""
MIN_PRICE_FRACTION = .05


def minimum_width(low, high, tick_at_price):
    return max(MIN_PRICE_FRACTION * high,
               2 * max(tick_at_price(low), tick_at_price(high)))


def gap_width_filter(corridor, tick_at_price):
    low, high = corridor['low'], corridor['high']
    remaining_low = corridor['remaining_low']
    remaining_high = corridor.get('remaining_high', high)
    original_width = high-low
    remaining_width = remaining_high-remaining_low
    original_minimum = minimum_width(low, high, tick_at_price)
    remaining_minimum = minimum_width(remaining_low, remaining_high, tick_at_price)
    return dict(eligible=original_width >= original_minimum-1e-12,
                original_width=original_width, original_minimum_width=original_minimum,
                remaining_width=remaining_width, minimum_width=remaining_minimum,
                min_price_fraction=MIN_PRICE_FRACTION,
                display_mode='fill_target_only' if remaining_width < remaining_minimum-1e-12 else 'pair')


def historical_gap_evidence(corridor, bars, tick_at_price):
    """One completed post-fill boundary reaction per independent encounter."""
    filled_at = corridor.get('filled_at')
    evidence = []
    armed = True
    low, high = corridor['low'], corridor['high']
    tolerance = max(2*tick_at_price(low), 2*tick_at_price(high), .005*high)
    for i, candle in enumerate(bars[:-1]):
        if filled_at is None or candle['time'] <= filled_at:
            continue
        if candle['high'] < low-tolerance or candle['low'] > high+tolerance:
            armed = True
            continue
        if not armed:
            continue
        following = bars[i+1]
        reactions = []
        for edge in (low, high):
            move = max(2*tick_at_price(edge), .01*edge)
            touched = candle['low']-tolerance <= edge <= candle['high']+tolerance
            if touched and abs(following['close']-edge) >= move-1e-12:
                reactions.append(dict(price=edge, time=candle['time'],
                                      confirmed_at=following['time'], close=following['close']))
        if reactions:
            evidence.append(max(reactions, key=lambda r:abs(r['close']-r['price'])))
            armed = False
    return dict(independent_tests=len(evidence), reactions=evidence,
                fill_age_sessions=corridor.get('fill_age_sessions', 0))


def historical_gap_rank(corridor, price):
    """Bounded reaction and recency bonuses; price still anchors relevance."""
    low, high = corridor['low'], corridor['high']
    evidence = corridor['historical_evidence']
    proximity = ((high-low)/price if low <= price <= high else
                 max(low-price, price-high, 0)/price)
    age = evidence['fill_age_sessions']
    bonus = .10*min(evidence['independent_tests'], 3) + .10/(1+age/5)
    return proximity/(1+bonus), -evidence['independent_tests'], age, -corridor['source_time']
