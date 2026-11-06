#!/usr/bin/env python3
"""Restyle existing owned drawings on the selected chart without recalculating."""
import argparse
import copy
import json
from pathlib import Path
from daily_levels import MCP, save_details
from level_explanations import explain_level
from level_styles import drawing_style


def apply_drawing_theme(client, theme, expected_scope=None):
    if theme not in ('dark','light'):
        raise ValueError('Unknown drawing theme')
    if hasattr(client,'bind_selected'):
        client=client.bind_selected()
    try:
        state=client.call('chart_get_state')
        scope=client.info['url']+'|'+state['symbol']+'|pane:'+client.info['pane_id']
        if expected_scope and expected_scope!=scope:
            raise RuntimeError('Selected chart changed before applying the drawing theme')
        path=client.details_path
        data=json.loads(path.read_text()).get(scope) if path and path.exists() else None
        if not data or not data.get('levels'):
            return dict(scope=scope,symbol=state['symbol'],changed=0,drawing_theme=theme)
        owned_path=client.ownership_path
        ownership=json.loads(owned_path.read_text()) if owned_path and owned_path.exists() else {}
        legacy=client.info['url']+'|'+state['symbol']
        owned=set(ownership.get(scope,[])+ownership.get(legacy,[]))
        live={s['id'] for s in client.call('draw_list')['shapes']}
        result=copy.deepcopy(data)
        patches=[]
        for level in result['levels']:
            # Style against the original Draw quote: no price/role recalculation.
            style=drawing_style(level,data['reference']['price'],theme=theme)
            ids=[m['entity_id'] for m in level['marks']] if level.get('marks') else [level['entity_id']]
            # A partial deletion is retained; absent or unowned drawings are untouched.
            eligible=set(ids)&live&owned
            if not eligible:
                continue
            level.update(style)
            if level.get('marks'):
                for mark in level['marks']:
                    if mark['entity_id'] not in eligible:continue
                    colors=(dict(color=style['border_color'],backgroundColor=style['color'])
                            if mark['shape']=='ellipse' else dict(linecolor=style['color'],textcolor=style['color']) if mark['shape']=='trend_line' else dict(color=style['color']))
                    overrides=json.loads(mark['overrides']);overrides.update(colors)
                    mark['overrides']=json.dumps(overrides)
                    patches.append(dict(entity_id=mark['entity_id'],properties=colors))
            else:
                patches.append(dict(entity_id=level['entity_id'],properties=dict(
                    linecolor=style['color'],textcolor=style['color'])))
            level['explanation']=explain_level(level,data['reference']['price'],level['label_sources'],data.get('context'))
        previous=client.call('draw_restyle',patches=patches)['previous'] if patches else []
        try:
            result['drawing_theme']=theme
            # Detect another Draw replacing this scope rather than overwriting its metadata.
            current=json.loads(path.read_text()).get(scope)
            if current!=data:
                raise RuntimeError('Chart levels changed while applying the drawing theme')
            save_details(path,scope,result)
        except Exception:
            if previous:
                client.allow_inactive=True
                client.call('draw_restyle',patches=previous)
            raise
        return dict(scope=scope,symbol=state['symbol'],changed=len(patches),drawing_theme=theme)
    finally:
        if hasattr(client,'release'):client.release()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--theme',choices=('dark','light'),required=True)
    parser.add_argument('--scope')
    args=parser.parse_args()
    client=MCP(Path(__file__).resolve().parents[1])
    try:
        client.call('tv_health_check')
        print(json.dumps(apply_drawing_theme(client,args.theme,args.scope)))
    finally:client.close()


if __name__=='__main__':main()
