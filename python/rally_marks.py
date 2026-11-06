"""Historical peak ovals and one label per qualified failed-rally ceiling."""
import json
from level_styles import (RALLY_FILL_TRANSPARENCY, RALLY_OUTLINE_WIDTH,
                          SUPPORT_ZONE_COLOR, SUPPORT_ZONE_BORDER_COLOR)


def rally_marks(level):
    marks = []
    padding = level['zone']['high'] - level['peak_bounds']['high']
    for failure in level['failures']:
        price, time = failure['peak'], failure['peak_time']
        radius = max(price * .0025, padding)
        # TradingView's ellipse uses two major-axis endpoints and one minor-axis
        # radius point. All three are on the captured one-minute chart.
        points = [dict(time=time-120, price=price), dict(time=time+120, price=price),
                  dict(time=time, price=price+radius)]
        marks.append(dict(shape='ellipse', points=points, text='', overrides=json.dumps(dict(
            color=level['border_color'],backgroundColor=level['color'],
            fillBackground=True,transparency=RALLY_FILL_TRANSPARENCY,linewidth=RALLY_OUTLINE_WIDTH))))
    latest = level['failures'][-1]
    radius = max(latest['peak']*.0025, padding)
    marks.append(dict(shape='text', point=dict(time=latest['peak_time']+120,
                     price=latest['peak']+2*radius), text=level['label'],
                     overrides=json.dumps(dict(color=level['color'],fontsize=13,bold=True,
                         fillBackground=False,drawBorder=False,wordWrap=False))))
    return marks


def support_marks(level):
    """Annotate confirmed support-hold troughs with one green group label."""
    marks = []
    padding = level['trough_bounds']['low'] - level['zone']['low']
    for hold in level['holds']:
        price, time = hold['trough'], hold['trough_time']
        radius = max(price*.0025,padding)
        points = [dict(time=time-120,price=price),dict(time=time+120,price=price),
                  dict(time=time,price=price+radius)]
        marks.append(dict(shape='ellipse',points=points,text='',overrides=json.dumps(dict(
            color=level['border_color'],backgroundColor=level['color'],fillBackground=True,
            transparency=RALLY_FILL_TRANSPARENCY,linewidth=RALLY_OUTLINE_WIDTH))))
    latest = level['holds'][-1]
    radius = max(latest['trough']*.0025,padding)
    marks.append(dict(shape='text',point=dict(time=latest['trough_time']+120,
                     price=max(latest['trough']*.01,latest['trough']-2*radius)),text=level['label'],
                     overrides=json.dumps(dict(color=level['color'],fontsize=13,bold=True,
                         fillBackground=False,drawBorder=False,wordWrap=False))))
    return marks
