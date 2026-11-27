'use strict';
const $ = id => document.getElementById(id);
let userPicked=false;
let phone, selection, session, gesture, imageURL, frameTime = 0, historyKey, deviceKey;
const api = (p, op) => '/api/'+encodeURIComponent(p.id)+'/'+op+'?session='+encodeURIComponent(p.session);
function issue(message='') { $('error').textContent=message; }
async function send(p, op, data={}) {
  const r=await fetch(api(p,op),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
  if (!r.ok) throw new Error((await r.json().catch(()=>({}))).error || 'Request failed');
}
function resetPreview() {
  gesture=null; frameTime=0; $('preview').hidden=true; $('unavailable').hidden=false;
}
function pick(p) {
  resetPreview(); selection=p.id; session=p.session; phone=p; historyKey=null; deviceKey=null; issue();
  $('name').textContent=p.name; $('hint').textContent='Tap or drag on the phone';
}
function history(p) {
  const key=JSON.stringify(p.history);
  if (key===historyKey) return;
  historyKey=key;
  $('history').replaceChildren(...p.history.map(entry=>{
    const row=document.createElement('p'), by=document.createElement('b');
    by.textContent=entry.role+'  '; row.append(by,document.createTextNode(entry.text)); return row;
  }));
  $('history').scrollTop=$('history').scrollHeight;
}
async function state() {
  try {
    const result=await (await fetch('/api/phones',{cache:'no-store'})).json();
    const p=(userPicked && result.phones.find(x=>x.id===selection)) || result.phones.find(x=>!x.demo) || result.phones[0];
    if(p.id!==selection || p.session!==session) pick(p);
    phone=p;
    $('home').disabled=!p.live;
    if(p.touchBlocker) $('hint').textContent=p.touchBlocker;
    const key=JSON.stringify([selection,...result.phones.map(x=>[x.id,x.session,x.live,x.touch])]);
    if(key!==deviceKey) {
      deviceKey=key;
      $('devices').replaceChildren(...result.phones.map(item=>{
        const b=document.createElement('button'), s=document.createElement('small');
        b.className='device'; b.setAttribute('aria-pressed',String(item.id===selection)); b.textContent=item.name;
        s.textContent=item.demo?'Simulator':(item.live?'Video live':'Awaiting video')+' · Click '+item.touch;
        b.append(s); b.onclick=()=>{userPicked=true;pick(item);}; return b;
      }));
    }
    $('info').textContent=result.info || 'USB discovery is active.';
    $('live').textContent=p.demo?'Sandbox':p.live?'● Live':'USB connected';
    $('status').textContent=p.status+(p.remaining===null?'':' · '+Math.floor(p.remaining/60)+':'+String(p.remaining%60).padStart(2,'0'));
    $('stop').disabled=!['Working','Playback paused','Reconnecting screen'].includes(p.status);
    $('ask').textContent=p.demo?'Ask agent':'Codex browser control';
    document.querySelector('#drawer form').hidden=!p.demo;
    $('examples').hidden=!p.demo;
    $('stop').hidden=!p.demo;
    $('privacy').textContent=p.demo?'Sandbox commands run locally.':'Give your instruction in the active Codex chat. Codex can watch this preview and click it using browser control.';
    $('unavailable').textContent=p.error || 'Waiting for a fresh preview…';
    if(!p.live && $('preview').hidden) resetPreview();
    if(!p.live && !$('preview').hidden) $('live').textContent='Reconnecting · last frame';
    history(p);
  } catch(e) { resetPreview(); issue('Local server unavailable.'); }
  setTimeout(state,550);
}
async function frames() {
  const p=phone;
  try {
    if(p?.live) {
      const r=await fetch(api(p,'frame'),{cache:'no-store',signal:AbortSignal.timeout(2500)});
      if(!r.ok) throw new Error();
      const url=URL.createObjectURL(await r.blob());
      if(p.session===session) {
        $('preview').src=url; $('preview').hidden=false; $('unavailable').hidden=true; frameTime=performance.now();
        if(imageURL) URL.revokeObjectURL(imageURL); imageURL=url;
      } else URL.revokeObjectURL(url);
    }
  } catch { if(session===p?.session) { gesture=null; frameTime=0; $('live').textContent='Reconnecting screen'; } }
  setTimeout(frames,p?.demo?250:110);
}
function point(e) {
  const b=$('preview').getBoundingClientRect();
  return [(e.clientX-b.left)/b.width,(e.clientY-b.top)/b.height];
}
$('preview').onpointerdown=e=>{
  if(phone?.touchBlocker) { issue(phone.touchBlocker); return; }
  if(!e.isPrimary || e.button!==0 || !phone.live || performance.now()-frameTime>1800) return;
  const g={phone,points:point(e),time:performance.now(),id:e.pointerId};
  gesture=g; e.currentTarget.setPointerCapture(e.pointerId);
  g.takeover=send(phone,'takeover').then(()=>true,err=>{issue(err.message);return false;});
};
$('preview').onpointercancel=()=>{gesture=null;};
$('preview').onpointerup=async e=>{
  const g=gesture; gesture=null;
  if(!g || e.pointerId!==g.id || session!==g.phone.session || performance.now()-frameTime>1800) return;
  const end=point(e);
  if(end.some(x=>x<0||x>1)) return;
  const distance=Math.hypot(end[0]-g.points[0],end[1]-g.points[1]);
  const data=distance<.018?{action:'tap',points:g.points}:{action:'drag',points:g.points.concat(end),duration:Math.min(2,Math.max(.08,(performance.now()-g.time)/1000))};
  if (!(await g.takeover) || session!==g.phone.session) return;
  const label=data.action==='tap'?'Tap':'Drag';
  issue(); $('hint').textContent='Sending '+label.toLowerCase()+'…';
  try {
    await send(g.phone,'touch',data);
    if(session===g.phone.session) $('hint').textContent=label+' sent to '+g.phone.name;
  } catch(err) {
    if(session===g.phone.session) { $('hint').textContent=label+' failed'; issue(err.message); }
  }
};
function drawer(open) {
  $('drawer').hidden=!open; $('ask').setAttribute('aria-expanded',String(open)); if(open) $('msg').focus();
}
$('ask').onclick=()=>drawer($('drawer').hidden); $('close').onclick=()=>drawer(false);
$('home').onclick=async ()=>{
  const p=phone;
  try { issue(); await send(p,'touch',{action:'home',points:[]}); }
  catch(err){if(session===p.session) issue(err.message);}
};
$('stop').onclick=()=>send(phone,'stop').catch(err=>issue(err.message));
for(const prompt of ['Scroll Shorts for 5 minutes','Watch the first video for 2.5 minutes then click out']) {
  const b=document.createElement('button'); b.textContent=prompt; b.onclick=()=>{$('msg').value=prompt;$('msg').focus();}; $('examples').append(b);
}
document.querySelector('form').onsubmit=async e=>{
  e.preventDefault(); const msg=$('msg'), p=phone; issue();
  try { await send(p,'chat',{message:msg.value}); if(p.session===session) msg.value=''; } catch(err){issue(err.message);}
};
state(); frames();
