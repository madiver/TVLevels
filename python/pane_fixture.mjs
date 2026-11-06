// Synthetic chart API for exercising the actual generated pane-bound expressions.
import readline from 'node:readline';
const widgets = [0,1].map(i=>({ id:()=>String(i+1), symbol:'NASDAQ:TEST', resolution:'5', session:'regular', shapes:new Map(), writes:[] }));
let selected=0, seq=0, switchDuringCreate=false, switchDuringSession=false, switchDuringRestyle=false, failRestyle=0;
for(const w of widgets){
 const values=()=>{
   if(['1','5','30'].includes(w.resolution) && w.intraday)return w.intraday;
   const defaults=[[1,8,10,8,9,10],[86401,4,5,4,4.5,10],[172801,4,6,4,5,10]];
   // Real minute candles are minute-aligned even when generic pane tests use
   // this sparse default history. Daily timestamps remain unchanged.
   return ['1','5'].includes(w.resolution) ? defaults.map(v=>[Math.floor(v[0]/(Number(w.resolution)*60))*Number(w.resolution)*60,...v.slice(1)]) : defaults;
 };
 const bars={size:()=>values().length,firstIndex:()=>0,lastIndex:()=>values().length-1,valueAt:i=>values()[i]};
 const model={dataSourceForId:id=>({linkKey:()=>({setValue:v=>w.shapes.get(id).link=v})}),withoutLineToolsSyncAction:async f=>{w.block=true;try{await f()}finally{w.block=false}}};
 w.model=()=>({mainSeries:()=>({bars:()=>bars,isLoading:()=>false,endOfData:()=>w.end??!w.intraday,requestMoreDataAvailable:()=>true,
 requestMoreData:n=>{w.writes.push(['history',n]);if(w.earlier){w.intraday=[...w.earlier,...w.intraday];w.earlier=null;}},
 properties:()=>({childs:()=>({sessionId:{value:()=>w.session,setValue:s=>{w.session=s;w.writes.push(['session',s]);if(switchDuringSession){selected=1;switchDuringSession=false;}}}})}),
 symbolInfo:()=>({type:w.symbolType??'stock',timezone:'America/New_York',subsessions:[{id:'extended'}]}),
 quotes:()=>({original_name:w.symbol,last_price:5,lp_time:172801})}),model:()=>model});
 w.setResolution=r=>{w.resolution=r;w.writes.push(['resolution',r]);};
 const create=async(p,o)=>{await Promise.resolve();const id=String(++seq);w.shapes.set(id,{props:{...o.overrides,text:o.text},points:Array.isArray(p)?p:[p],link:'shared'});w.writes.push(['create',id]);if(!o.disableUndo || !w.block)widgets[1-widgets.indexOf(w)].shapes.set(id,{props:{text:o.text}});if(switchDuringCreate){selected=1;switchDuringCreate=false;}return id;};
 w.api={_chartWidget:w,symbol:()=>w.symbol,resolution:()=>w.resolution,chartType:()=>1,getAllShapes:()=>[...w.shapes].map(([id])=>({id,name:'Horizontal Line'})),getShapeById:id=>({getProperties:()=>w.shapes.get(id).props,getPoints:()=>w.shapes.get(id).points,setProperties:(p,saveDefaults)=>{
 if(saveDefaults)throw Error('Theme must not change drawing defaults');
 if(failRestyle && --failRestyle===0)throw Error('injected restyle failure');
 Object.assign(w.shapes.get(id).props,p);w.writes.push(['style',id,p]);
 if(!w.block && widgets[1-widgets.indexOf(w)].shapes.has(id))Object.assign(widgets[1-widgets.indexOf(w)].shapes.get(id).props,p);
 if(switchDuringRestyle){selected=1;switchDuringRestyle=false;}
 } }),
 createShape:create,createMultipointShape:create,
 removeEntity:id=>{w.shapes.delete(id);w.writes.push(['remove',id]);}};
}
globalThis.document={visibilityState:'visible'};
globalThis.window={location:{href:'https://fixture/chart/one'},TradingViewApi:{_activeChartWidgetWV:{value:()=>widgets[selected].api},_chartWidgetCollection:{getAll:()=>widgets}}};
for await(const line of readline.createInterface({input:process.stdin})){
 try{const q=JSON.parse(line);let result;
 if(q.op==='evaluate')result=await eval(q.expression);
 if(q.op==='select')selected=q.index;
 if(q.op==='visibility')document.visibilityState=q.state;
 if(q.op==='switchDuringRestyle')switchDuringRestyle=true;
 if(q.op==='failRestyle')failRestyle=q.at;
 if(q.op==='switchDuringCreate')switchDuringCreate=true;
 if(q.op==='switchDuringSession')switchDuringSession=true;
 if(q.op==='intraday'){widgets[selected].intraday=q.bars;widgets[selected].earlier=q.earlier;widgets[selected].end=q.end;}
 if(q.op==='symbolType')widgets[selected].symbolType=q.type;
 if(q.op==='snapshot')result={selected,panes:widgets.map(w=>({resolution:w.resolution,session:w.session,shapes:[...w.shapes],writes:w.writes}))};
 process.stdout.write(JSON.stringify({result:result??null})+'\n');
 }catch(e){process.stdout.write(JSON.stringify({error:e.message})+'\n');}
}
