#!/usr/bin/env python3
"""Read-only selected-chart observer for the native Daily Levels inspector."""
import argparse
import json
from pathlib import Path
import signal
import sys
import time
from daily_levels import MCP, PREFIX
from level_catalog import CATALOG, LEVEL_NAMES
from level_explanations import money

SNAPSHOT_EXPRESSION = '''(()=>{
    if(document.visibilityState==='hidden')throw Error('TradingView tab changed; waiting for the visible chart');
    const api=window.TradingViewApi._activeChartWidgetWV.value();
    const selection=api.selection();
    return {symbol:api.symbol(),url:window.location.href,
        pane:{pane_id:String(api._chartWidget.id())},
        selected_ids:selection.allItems().filter(x=>typeof x==='string'),
        shapes:api.getAllShapes().map(s=>{
            const shape=api.getShapeById(s.id),p=shape.getProperties();
            const points=shape.getPoints();
            return {id:s.id,price:points[0]?.price,points,text:p.text||'',color:p.linecolor||p.textColor||p.color||'#888888',linestyle:p.linestyle??0,linewidth:p.linewidth??1};
        })};
})()'''


def legacy_explanation(text):
    parts=[]
    for label in text.removeprefix(PREFIX).split(' / '):
        kind=next((k for k,name in LEVEL_NAMES.items() if label==name or label.startswith(name+' ')),None)
        if kind is None and label.startswith('Retest '):kind='support' if label.startswith('Retest S') else 'resistance'
        if kind and CATALOG[kind]['explanation'] not in parts:parts.append(CATALOG[kind]['explanation'])
    parts.append('This line predates the detailed inspector snapshot. Click Draw to refresh its source prices, dates and state-specific explanation.')
    return '\n\n'.join(parts)


def inspect_chart(client):
    chart=client.call('ui_evaluate',expression=SNAPSHOT_EXPRESSION)['result']
    scope=chart['url']+'|'+chart['symbol']+'|pane:'+chart['pane']['pane_id']
    path=getattr(client,'details_path',None)
    saved=json.loads(path.read_text()).get(scope,{}) if path and path.exists() else {}
    live={s['id']:s for s in chart['shapes']}
    levels=[]
    for old in saved.get('levels',[]):
        shape=live.get(old.get('entity_id'))
        if old.get('marks'):
            present=[live[m['entity_id']] for m in old['marks'] if m['entity_id'] in live]
            if not present:continue
            item=dict(old)
            shape=shape or present[0]
            item['entity_id']=shape['id']
            changed=len(present)!=len(old['marks'])
            for mark in old['marks']:
                current=live.get(mark['entity_id'])
                if current is None:continue
                expected=mark.get('points') or [mark['point']]
                points=current.get('points',[])
                changed |= (len(points)!=len(expected) or current['text']!=mark['text']
                            or any(abs(a.get('price',0)-b['price'])>1e-9 or a.get('time')!=b['time']
                                   for a,b in zip(points,expected)))
            if changed:
                subject = 'trendline' if item.get('kind') in ('ascending_support','descending_resistance') else 'support mark' if item.get('kind') == 'support_zone' else 'rally mark'
                source = 'anchors' if item.get('kind') in ('ascending_support','descending_resistance') else 'troughs' if item.get('kind') == 'support_zone' else 'peaks'
                item['explanation']=f'You edited or removed a {subject} after Draw. The source explanation below describes its recorded {source}. Click Draw to recalculate.\n\n'+item['explanation']
            levels.append(item)
            continue
        if shape is None:continue
        item=dict(old)
        if item.get('kind') == 'failed_rally':
            points=shape.get('points',[])
            prices=sorted(p['price'] for p in points if p.get('price') is not None)
            expected=[item['zone']['low'],item['zone']['high']]
            changed=(len(prices)!=2 or any(abs(a-b)>1e-9 for a,b in zip(prices,expected))
                     or shape['text']!=item['label'])
            if changed:
                item['explanation']='You edited this zone after Draw. The source explanation below describes its recorded bounds. Click Draw to recalculate.\n\n'+item['explanation']
                if prices:
                    item['zone']=dict(low=prices[0],high=prices[-1]);item['price']=prices[-1]
                item['label']=shape['text']
        elif shape.get('price') is not None and (abs(shape['price']-item['price'])>1e-9 or shape['text']!=item['label']):
            item['explanation']='You edited this drawing after Draw. Its current line price is '+money(shape['price'])+'. The source explanation below describes the original '+money(item['price'])+' reference. Click Draw to recalculate.\n\n'+item['explanation']
            item['price']=shape['price'];item['label']=shape['text'];item['color']=shape['color']
        item['color']=shape['color'];item['linestyle']=shape.get('linestyle',item.get('linestyle',2))
        levels.append(item)
    ownership_path=getattr(client,'ownership_path',None)
    ownership=json.loads(ownership_path.read_text()) if ownership_path and ownership_path.exists() else {}
    owned=set(ownership.get(scope,[])+ownership.get(chart['url']+'|'+chart['symbol'],[]))
    known={id for x in levels for id in x.get('entity_ids',[x['entity_id']])}
    known.update(x['entity_id'] for x in levels)
    for shape in chart['shapes']:
        if shape['id'] in known or shape.get('price') is None:continue
        if shape['id'] in owned or shape['text'].startswith(PREFIX):
            levels.append(dict(entity_id=shape['id'],price=shape['price'],label=shape['text'].removeprefix(PREFIX),
                               color=shape['color'],linestyle=shape.get('linestyle',2),kind='legacy',explanation=legacy_explanation(shape['text'])))
    levels.sort(key=lambda x:x['price'],reverse=True)
    selected=next((x['entity_id'] for eid in reversed(chart['selected_ids']) for x in levels
                   if eid in x.get('entity_ids',[x['entity_id']])),None)
    return dict(connected=True,symbol=chart['symbol'],pane=chart['pane'],scope=scope,levels=levels,
                selected_id=selected,reference=saved.get('reference'),drawn_at=saved.get('drawn_at'),
                availability=saved.get('availability',{}),drawing_theme=saved.get('drawing_theme','dark'),
                has_theme_sources=bool(saved.get('levels')))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch',action='store_true')
    args=parser.parse_args()
    def stop(*_):raise SystemExit(0)
    signal.signal(signal.SIGTERM,stop)
    signal.signal(signal.SIGINT,stop)
    client=None;previous=None;last_emitted=0
    try:
        while True:
            try:
                if client is None:client=MCP(Path(__file__).resolve().parents[1])
                client.call('tab_follow_visible')
                snapshot=inspect_chart(client)
            except Exception as error:
                snapshot=dict(connected=False,error=str(error),levels=[])
                if client:client.close();client=None
            encoded=json.dumps(snapshot,ensure_ascii=False)
            if encoded!=previous or time.monotonic()-last_emitted>=3:
                print(encoded,flush=True);previous=encoded;last_emitted=time.monotonic()
            if not args.watch:break
            time.sleep(.8 if snapshot['connected'] else 4)
    finally:
        if client:client.close()


if __name__=='__main__':main()
