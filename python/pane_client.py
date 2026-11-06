"""Pin daily-level operations to one TradingView chart widget through MCP."""
import json
import time
import uuid


class PaneClient:
    def __init__(self, client):
        self.client = client
        self.ownership_path = getattr(client, 'ownership_path', None)
        self.details_path = getattr(client, 'details_path', None)
        self.key = '__dailyLevels_' + uuid.uuid4().hex
        self.allow_inactive = False
        self.info = client.call('ui_evaluate', expression=f'''(()=>{{
            const c=window.TradingViewApi._chartWidgetCollection;
            const api=window.TradingViewApi._activeChartWidgetWV.value();
            const widget=api._chartWidget;
            const index=c.getAll().indexOf(widget);
            if(index<0 || typeof widget.id!=='function') throw Error('Cannot identify selected chart');
            window[{json.dumps(self.key)}]={{api,widget,url:window.location.href,symbol:api.symbol()}};
            return {{pane_id:String(widget.id()),pane_index:index,url:window.location.href}};
        }})()''')['result']

    def evaluate(self, body):
        return self.client.call('ui_evaluate', expression=f'''(async()=>{{
            const b=window[{json.dumps(self.key)}];
            if(!b || b.url!==window.location.href ||
               !window.TradingViewApi._chartWidgetCollection.getAll().includes(b.widget))
                throw Error('Original chart pane no longer exists');
            const api=b.api, widget=b.widget;
            function checkSelected() {{
                if(api.symbol()!==b.symbol) throw Error('Original pane symbol changed');
                if(!{json.dumps(self.allow_inactive)} && document.visibilityState==='hidden')
                    throw Error('TradingView tab changed; daily-level run stopped');
                if(!{json.dumps(self.allow_inactive)} &&
                   window.TradingViewApi._activeChartWidgetWV.value()._chartWidget!==widget)
                    throw Error('Selected chart pane changed; daily-level run stopped');
            }}
            checkSelected();
            {body}
        }})()''')['result']

    def call(self, name, **args):
        if name == 'ui_evaluate':
            # The workflow only requests its chart URL here.
            if args['expression'] != 'window.location.href':
                raise ValueError('Unsupported bound UI expression')
            return {'result': self.info['url']}
        if name == 'chart_get_state':
            return self.evaluate('return {symbol:api.symbol(),resolution:api.resolution(),chartType:api.chartType()};')
        if name == 'quote_snapshot':
            return self.evaluate("""const q=widget.model().mainSeries().quotes();
                if(!q)throw Error('Selected chart quotes have not loaded');
                if(q.original_name && q.original_name!==api.symbol())throw Error('Selected chart quote symbol mismatch');
                return {last_price:q.last_price,lp_time:q.lp_time,rtc:q.rtc,rtc_time:q.rtc_time,
                        ntc:q.ntc,ntc_time:q.ntc_time,session:q.current_session,regular_close_time:q.regular_close_time,
                        minmov:q.minmov,pricescale:q.pricescale,variable_tick_size:q.variable_tick_size};""")
        if name == 'session_snapshot':
            return self.evaluate('''const s=widget.model().mainSeries(), info=s.symbolInfo();
                return {session:s.properties().childs().sessionId.value(),
                    premarket_supported:['stock','dr'].includes(info?.type) && info.timezone==='America/New_York' &&
                        !!info.subsessions?.some(x=>x.id==='extended')};''')
        if name == 'chart_set_session':
            session = args['session']
            self.evaluate(f'''const s=widget.model().mainSeries();
                if(s.properties().childs().sessionId.value()!=={json.dumps(session)})
                    s.properties().childs().sessionId.setValue({json.dumps(session)});
                return {{}};''')
            return self.wait_ready(session=session)
        if name == 'chart_set_timeframe':
            timeframe = args['timeframe']
            # Widget-local setter bypasses the collection's interval-sync fanout.
            self.evaluate(f'widget.setResolution({json.dumps(timeframe)}); return {{}};')
            return self.wait_ready(timeframe=timeframe)
        if name == 'data_ensure_history':
            # A missing 04:00 candle can mean no trades; require older data or
            # the provider's end-of-history flag, not an exact opening candle.
            start = float(args['start'])
            requests=min(12,max(1,int(args.get('max_requests',4))))
            for attempt in range(requests+1):
                coverage = self.evaluate(f'''const s=widget.model().mainSeries(), bars=s.bars();
                    return {{complete:!s.isLoading() && (s.endOfData() ||
                        (bars.size()>0 && bars.valueAt(bars.firstIndex())[0]<={start})),
                        available:s.requestMoreDataAvailable()}};''')
                if coverage['complete']:
                    return {'complete': True}
                if not coverage['available'] or attempt==requests:
                    break
                self.evaluate('widget.model().mainSeries().requestMoreData(500); return {};')
                self.wait_ready()
            raise RuntimeError('Full '+args.get('session_name','premarket')+' history did not load; previous levels were kept. Try Draw again.')
        if name == 'data_get_ohlcv':
            count = min(int(args['count']), 500)
            return self.evaluate(f'''const series=widget.model().mainSeries();
                if(series.isLoading()) throw Error('Selected chart data still loading');
                const bars=series.bars(), result=[];
                for(let i=Math.max(bars.firstIndex(),bars.lastIndex()-{count}+1);i<=bars.lastIndex();i++){{
                    const v=bars.valueAt(i);
                    if(v)result.push({{time:v[0],open:v[1],high:v[2],low:v[3],close:v[4],volume:v[5]||0}});
                }}
                if(!result.length)throw Error('No selected-chart daily bars');
                return {{bars:result}};''')
        if name == 'data_get_session_history':
            start,end=float(args['start']),float(args['end'])
            return self.evaluate(f'''const s=widget.model().mainSeries();
                if(api.resolution()!=='30' || s.isLoading())throw Error('Thirty-minute history not ready');
                const bs=s.bars(),result=[];
                for(let i=bs.firstIndex();i<=bs.lastIndex();i++){{const v=bs.valueAt(i);
                    if(v && v[0]>={start} && v[0]<{end})result.push({{time:v[0],open:v[1],high:v[2],low:v[3],close:v[4],volume:v[5]||0}});
                    if(result.length>5000)throw Error('Historical session range exceeded safe limit');
                }}return {{bars:result}};''')
        if name == 'data_latest_intraday_time':
            # Use actual provider candles rather than guessing exchange holidays.
            # Include a forming candle when choosing the session, but never use
            # it to qualify evidence in the bounded completed-candle read below.
            end = float(args['end'])
            timeframe = str(args.get('timeframe','1'))
            if timeframe not in ('1','5'):raise ValueError('Unsupported intraday timeframe')
            ready_name = 'One-minute' if timeframe=='1' else 'Five-minute'
            return self.evaluate(f'''const series=widget.model().mainSeries();
                if(api.resolution()!=={json.dumps(timeframe)} || series.isLoading())throw Error('{ready_name} chart not ready');
                const bars=series.bars(), hours=new Intl.DateTimeFormat('en-US',
                    {{timeZone:'America/New_York',hour:'2-digit',hourCycle:'h23'}});
                for(let i=bars.lastIndex();i>=bars.firstIndex();i--){{
                    const v=bars.valueAt(i);if(!v || v[0]>{end})continue;
                    const hour=Number(hours.format(new Date(v[0]*1000)));
                    if(hour>=4 && hour<20)return {{time:v[0]}};
                }}
                return {{time:null}};''')
        if name == 'data_get_intraday':
            # One extended session has at most 960 minute bars. Fetch by time,
            # not the generic tool's 500-bar tail, which loses morning history.
            start, end = float(args['start']), float(args['end'])
            timeframe = str(args.get('timeframe','1'))
            if timeframe not in ('1','5'):raise ValueError('Unsupported intraday timeframe')
            ready_name = 'One-minute' if timeframe=='1' else 'Five-minute'
            return self.evaluate(f'''const series=widget.model().mainSeries();
                if(api.resolution()!=={json.dumps(timeframe)} || series.isLoading())throw Error('{ready_name} chart not ready');
                const bars=series.bars(), result=[];
                for(let i=bars.lastIndex();i>=bars.firstIndex();i--){{
                    const v=bars.valueAt(i);if(!v)continue;
                    if(v[0]<{start})break;
                    if(v[0]>={end})continue;
                    if(result.length>=1000)throw Error('Intraday candle limit exceeded');
                    result.push({{time:v[0],open:v[1],high:v[2],low:v[3],close:v[4],volume:v[5]??null}});
                }}
                return {{bars:result.reverse()}};''')
        if name == 'draw_list':
            return self.evaluate('return {shapes:api.getAllShapes().map(s=>({id:s.id,name:s.name}))};')
        if name == 'draw_get_properties':
            return self.evaluate(f'return {{properties:api.getShapeById({json.dumps(args["entity_id"])}).getProperties()}};')
        if name == 'draw_restyle':
            patches=args['patches']
            # Only color properties may be changed by a theme operation.
            allowed={'color','linecolor','textcolor','textColor','backgroundColor'}
            if any(not set(p['properties']).issubset(allowed) for p in patches):
                raise ValueError('Restyling may only change drawing colors')
            return self.evaluate(f'''const patches={json.dumps(patches)}, previous=[];
                const model=widget.model().model();
                await model.withoutLineToolsSyncAction(async()=>{{
                    try{{
                        for(const patch of patches){{
                            checkSelected();
                            const shape=api.getShapeById(patch.entity_id),props=shape.getProperties(),old={{}};
                            for(const key of Object.keys(patch.properties)){{
                                if(!(key in props))throw Error('Drawing color property unavailable: '+key);
                                old[key]=props[key];
                            }}
                            previous.push({{entity_id:patch.entity_id,properties:old}});
                            shape.setProperties(patch.properties,false);
                            checkSelected();
                        }}
                    }}catch(error){{
                        for(const patch of previous.reverse()){{
                            api.getShapeById(patch.entity_id).setProperties(patch.properties,false);
                        }}
                        throw error;
                    }}
                }});
                return {{previous}};''')
        if name == 'draw_shape':
            points = args.get('points') or ([args['point'], args['point2']] if args.get('point2') else None)
            options = dict(shape=args['shape'], text=args['text'],
                           overrides=json.loads(args['overrides']), disableUndo=True)
            return self.evaluate(f'''const model=widget.model().model();
                let id;
                await model.withoutLineToolsSyncAction(async()=>{{
                    id=await {'api.createMultipointShape' if points else 'api.createShape'}({json.dumps(points if points else args['point'])},{json.dumps(options)});
                    if(!id)throw Error('Drawing returned no ID');
                    const source=model.dataSourceForId(id);
                    source.linkKey().setValue(null);
                    try{{checkSelected();}}catch(e){{api.removeEntity(id);throw e;}}
                }});
                return {{entity_id:id}};''')
        if name == 'draw_remove_one':
            return self.evaluate(f'''const id={json.dumps(args['entity_id'])};
                await widget.model().model().withoutLineToolsSyncAction(async()=>api.removeEntity(id));
                return {{removed:!api.getAllShapes().some(s=>s.id===id)}};''')
        raise ValueError('Unsupported pane-bound tool: ' + name)

    def release(self):
        self.client.call('ui_evaluate', expression=f'delete window[{json.dumps(self.key)}]')

    def wait_ready(self, timeframe=None, session=None):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            ready = self.evaluate('''const s=widget.model().mainSeries();
                return {resolution:api.resolution(),session:s.properties().childs().sessionId.value(),
                    ready:s.bars().size()>0 && !s.isLoading()};''')
            if (ready['ready'] and (timeframe is None or ready['resolution']==timeframe)
                    and (session is None or ready['session']==session)):
                return {'chart_ready': True}
            time.sleep(.2)
        raise RuntimeError('Selected chart session/timeframe data did not become ready')
