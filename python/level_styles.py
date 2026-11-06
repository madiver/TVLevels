"""Shared drawing, inspector and legend styles; rally ovals have stronger outlines."""
# TradingView OverrideLineStyle: Solid=0, Dotted=1, Dashed=2.
# https://www.tradingview.com/charting-library-docs/latest/api/enums/Charting_Library.OverrideLineStyle/
ROLE_COLORS = {'support': {'standard':'#66bb6a', 'prior':'#00e676'},
               'resistance': {'standard':'#d18b32', 'prior':'#ffb74d'}}
PREMARKET_COLOR = '#ff00ff'
SESSION_COLOR = '#26c6da'
CLOSE_COLOR = '#b0bec5'
RALLY_COLOR = '#ff7043'
RECLAIMED_RALLY_COLOR = '#90a4ae'
RALLY_BORDER_COLOR = '#f48266'
RECLAIMED_RALLY_BORDER_COLOR = '#c39889'
SUPPORT_ZONE_COLOR = '#66bb6a'
SUPPORT_ZONE_BORDER_COLOR = '#81c784'
RALLY_FILL_TRANSPARENCY = 84
RALLY_OUTLINE_WIDTH = 2
# At most five ceilings are selected. Keep each ceiling's marks together, with
# colors assigned in peak-time order rather than distance from the moving quote.
RALLY_PALETTE = [
    ('coral', '#ff9a80', '#f48266', '#e59a86', '#ca826f'),
    ('blue', '#78bdff', '#6aaaff', '#69b7e8', '#60a5d4'),
    ('violet', '#cda0ff', '#b88aef', '#dca0e8', '#c087cd'),
    ('teal', '#62dfc9', '#51bdaa', '#6bcbb5', '#58af9c'),
    ('gold', '#ffdc72', '#dec055', '#e0c473', '#c6ab5e'),
]

# Deeper shades preserve the same semantic hue on a white chart background.
LIGHT_COLORS = {
    '#66bb6a':'#2e8332', '#00e676':'#168247', '#d18b32':'#ad5d00', '#ffb74d':'#b85d00',
    '#ff00ff':'#b800b8', '#26c6da':'#007b8a', '#b0bec5':'#646f7b',
    '#ff7043':'#b85037', '#90a4ae':'#64727c', '#f48266':'#a9432c', '#c39889':'#8c594c',
    '#81c784':'#287b32',
    '#ff9a80':'#b85037', '#e59a86':'#9a6557', '#ca826f':'#875547',
    '#78bdff':'#246fba', '#6aaaff':'#1b61a7', '#69b7e8':'#4c7391', '#60a5d4':'#3d637f',
    '#cda0ff':'#8550b6', '#b88aef':'#75449f', '#dca0e8':'#865d8d', '#c087cd':'#754d7d',
    '#62dfc9':'#007e6d', '#51bdaa':'#006b5c', '#6bcbb5':'#47796b', '#58af9c':'#37665a',
    '#ffdc72':'#946d00', '#dec055':'#805c00', '#e0c473':'#806d36', '#c6ab5e':'#6d5c2a',
}


def theme_color(color, theme='dark'):
    if theme not in ('dark','light'):
        raise ValueError('Unknown drawing theme')
    return LIGHT_COLORS.get(color.lower(),color) if theme=='light' else color


def theme_legend(theme='dark'):
    return [dict(entry,colors=[theme_color(c,theme) for c in entry['colors']]) for entry in STYLE_LEGEND]


def assign_rally_colors(levels):
    rallies = sorted((level for level in levels if level['kind'] == 'failed_rally'),
                     key=lambda level: (level['failures'][0]['peak_time'],
                                        level['failures'][0]['peak']))
    for index, level in enumerate(rallies):
        level['rally_color_index'] = index


STYLE_NAMES = {0:'solid',1:'dotted',2:'dashed'}
STYLE_LEGEND = [
    dict(id='daily',title='Daily support / resistance',explanation='Green below the Draw quote; orange at or above. Dashed.',colors=['#66bb6a','#d18b32'],linestyle=2),
    dict(id='prior',title='Prior support / resistance',explanation='Brighter green or orange, relative to the Draw quote. Dashed.',colors=['#00e676','#ffb74d'],linestyle=2),
    dict(id='corridor',title='Gap / window boundaries',explanation='Green or orange, relative to the Draw quote. Dotted.',colors=['#66bb6a','#d18b32'],linestyle=1),
    dict(id='previous_range',title='Previous-session high / low',explanation='Cyan and dashed.',colors=[SESSION_COLOR],linestyle=2),
    dict(id='day_range',title='Today’s regular high / low',explanation='Cyan and solid.',colors=[SESSION_COLOR],linestyle=0),
    dict(id='previous_close',title='Previous close',explanation='Gray and dotted.',colors=[CLOSE_COLOR],linestyle=1),
    dict(id='previous_open',title='Previous open',explanation='Gray and dashed.',colors=[CLOSE_COLOR],linestyle=2),
    dict(id='event',title='Historical event references',explanation='Green below the Draw quote; orange at or above. Thin and dashed. Dates and original event sources stay in labels; intraday state appears in Details.',colors=['#66bb6a','#d18b32'],linestyle=2),
    dict(id='premarket',title='Premarket high / low',explanation='Fuchsia and solid.',colors=[PREMARKET_COLOR],linestyle=0),
    dict(id='rally',title='Failed-rally zones',explanation='One distinct color per ceiling, shared by its lightly shaded peak ovals and label. Two-pixel outlines improve visibility. Reclaimed ceilings use a softer shade of their group color.',colors=[x[1] for x in RALLY_PALETTE],linestyle=0),
    dict(id='descending_resistance',title='Descending resistance · 5m',explanation='Thin orange ray: dotted with two anchors, solid after a third rejection. Broken rays are green and dashed. Anchors stay fixed.',colors=['#d18b32','#66bb6a'],linestyle=1),
    dict(id='ascending_support',title='Ascending support · 5m',explanation='Thin green ray: dotted with two anchors, solid after a third reaction. Broken rays are orange and dashed. Anchors stay fixed.',colors=['#66bb6a','#d18b32'],linestyle=1),
    dict(id='support_zone',title='Support holds',explanation='Green trough ovals show confirmed rebounds. Repeated holds share one label. Ovals, 2px.',colors=[SUPPORT_ZONE_COLOR],linestyle=0),
]
FAMILY_BY_KIND = dict(resistance='daily',support='daily',former_support='prior',former_resistance='prior',
    gap='corridor',window='corridor',previous_high='previous_range',previous_low='previous_range',
    day_high='day_range',day_low='day_range',previous_close='previous_close',previous_open='previous_open',event_close='event',event_high='event',prior_premarket_high='event',premarket_high='premarket',premarket_low='premarket',failed_rally='rally',support_zone='support_zone',ascending_support='ascending_support',descending_resistance='descending_resistance')


def drawing_style(level,quote,sources=None,theme=None):
    """Resolve merged references by source family, independently of price anchoring."""
    kinds={s['kind'] for s in (sources if sources is not None else level.get('label_sources',[]))}
    kinds.add(level['kind'])
    kinds.update(level.get('prior_times',{}))
    families={FAMILY_BY_KIND[k] for k in kinds if k in FAMILY_BY_KIND}
    family=next((f for f in ('ascending_support','descending_resistance','rally','support_zone','premarket','prior','daily','corridor','event','day_range','previous_range','previous_close','previous_open') if f in families),'daily')
    entry=next(x for x in STYLE_LEGEND if x['id']==family)
    if family in ('daily','prior','corridor','event'):
        role='support' if level['price']<quote else 'resistance'
        color=ROLE_COLORS[role]['prior' if family=='prior' else 'standard']
    elif family == 'rally':
        color = RECLAIMED_RALLY_COLOR if level.get('state') == 'reclaimed' else RALLY_COLOR
    elif family in ('ascending_support','descending_resistance'):
        is_support=(family=='ascending_support') != (level.get('state')=='broken')
        color=ROLE_COLORS['support' if is_support else 'resistance']['standard']
    elif family == 'support_zone':
        color = SUPPORT_ZONE_COLOR
    else:
        color=entry['colors'][0]
    style = dict(color=color,linestyle=entry['linestyle'],line_style=STYLE_NAMES[entry['linestyle']],
                 style_family=family,linewidth=1)
    if family in ('ascending_support','descending_resistance'):
        style['linestyle']={'provisional':1,'confirmed':0,'broken':2}[level.get('state','provisional')]
        style['line_style']=STYLE_NAMES[style['linestyle']]
    if family == 'rally':
        style['linewidth'] = RALLY_OUTLINE_WIDTH
        style['border_color'] = RECLAIMED_RALLY_BORDER_COLOR if level.get('state') == 'reclaimed' else RALLY_BORDER_COLOR
        if 'rally_color_index' in level:
            name, active, border, reclaimed, reclaimed_border = RALLY_PALETTE[level['rally_color_index']]
            is_reclaimed = level.get('state') == 'reclaimed'
            style.update(color=reclaimed if is_reclaimed else active,
                         border_color=reclaimed_border if is_reclaimed else border,
                         rally_color_name=name)
    elif family == 'support_zone':
        style['linewidth'] = RALLY_OUTLINE_WIDTH
        style['border_color'] = SUPPORT_ZONE_BORDER_COLOR
    theme = theme or level.get('drawing_theme','dark')
    style['color'] = theme_color(style['color'],theme)
    if 'border_color' in style:
        style['border_color'] = theme_color(style['border_color'],theme)
    style['drawing_theme'] = theme
    return style


def category_appearance(kind):
    family=FAMILY_BY_KIND[kind]
    return next(x['explanation'] for x in STYLE_LEGEND if x['id']==family)
