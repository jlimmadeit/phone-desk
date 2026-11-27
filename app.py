import asyncio
import contextlib
import json
import os
import sqlite3
import time

from aiohttp import web
from server.devices import ROOT, Phone, discover
from server.agent import Run

PORT = int(os.getenv('PORT','8766'))

class Desk:
    def __init__(self, db):
        self.db=db
        self.db.execute('CREATE TABLE IF NOT EXISTS messages (uid TEXT, role TEXT, text TEXT)')
        self.phones={}
        self.runs={}
        self.info='Checking USB devices…'
        self.add(Phone('sandbox','Sandbox iPhone',demo=True))

    def save(self,uid,role,msg):
        with self.db:
            self.db.execute('INSERT INTO messages VALUES (?,?,?)',(uid,role,msg))

    def add(self,p):
        history=self.db.execute('SELECT role,text FROM messages WHERE uid=? ORDER BY rowid DESC LIMIT 60',(p.uid,)).fetchall()
        self.phones[p.uid]=p
        self.runs[p.uid]=Run(p,self.save,[dict(role=r,text=t) for r,t in reversed(history)])

    async def remove(self,uid):
        p=self.phones.pop(uid)
        p.connected=False
        p.frame_event.set()
        self.runs.pop(uid).stop('Phone disconnected')
        if p.capture_task:
            p.capture_task.cancel()
            with contextlib.suppress(Exception,asyncio.CancelledError):
                await p.capture_task

    async def scan(self):
        while True:
            try:
                diagnostics=[]
                active={uid:p.source for uid,p in self.phones.items() if p.source and p.fresh()}
                found=await discover(active, diagnostics)
                self.info = ' '.join(diagnostics)
                if not found and not self.info:
                    self.info = 'Connect your iPhone with a USB data cable.'
                for uid,p in list(self.phones.items()):
                    if p.demo:
                        continue
                    if uid not in found or (found[uid][1] and found[uid][1]!=p.source):
                        await self.remove(uid)
                for uid,(name,source) in found.items():
                    if uid in self.phones:
                        continue
                    p=Phone(uid,name,source)
                    self.add(p)
                    if source:
                        p.capture_task=asyncio.create_task(p.capture())
                    else:
                        p.error=self.info or 'Waiting for a matching wired capture source.'
            except Exception as exc:
                self.info=str(exc) or type(exc).__name__
                # A discovery error is inconclusive. Existing streams track their own liveness.
            await asyncio.sleep(4)

def application(db):
    desk=Desk(db)
    @web.middleware
    async def local(req,handler):
        if req.host not in {f'127.0.0.1:{PORT}',f'localhost:{PORT}'}:
            raise web.HTTPForbidden()
        if req.method=='POST' and (req.headers.get('Origin')!=f'http://{req.host}' or req.content_type!='application/json'):
            raise web.HTTPForbidden()
        try:
            return await handler(req)
        except (ValueError,KeyError,TypeError,asyncio.TimeoutError) as exc:
            return web.json_response({'error':str(exc) or 'Device command timed out.'},status=400)
    app=web.Application(middlewares=[local],client_max_size=16000)
    async def state(req):
        phones=[]
        for p in desk.phones.values():
            run=desk.runs[p.uid]
            phones.append(dict(id=p.uid,name=p.name,session=p.session,demo=p.demo,live=p.fresh(),
                touch=p.touch_state,touchBlocker=p.touch_blocker,error=p.error,status=run.status,history=run.history,
                remaining=max(0,round(run.deadline-time.monotonic())) if run.deadline else None))
        return web.json_response(dict(phones=phones,info=desk.info,vision=False),headers={'Cache-Control':'no-store'})
    def selected(req):
        p=desk.phones.get(req.match_info['uid'])
        if not p or req.query.get('session')!=p.session:
            raise ValueError('Phone session changed. Select the phone again.')
        return p
    async def frame(req):
        p=selected(req)
        if not p.fresh():
            raise web.HTTPServiceUnavailable()
        return web.Response(body=p.frame,content_type='image/jpeg',headers={'Cache-Control':'no-store'})
    async def action(req):
        p=selected(req)
        run=desk.runs[p.uid]
        body=await req.json()
        op=req.match_info['op']
        if op=='chat':
            if not p.demo:
                raise ValueError('Give this instruction in your Codex chat with Phone Desk open in the browser.')
            prompt=str(body.get('message','')).strip()
            if not 0<len(prompt)<=3000:
                raise ValueError('Enter a message of up to 3000 characters.')
            run.start(prompt)
        elif op=='stop':
            run.stop('Stopped')
        elif op=='takeover':
            if run.task and not run.task.done():
                run.stop('Paused for manual control')
        elif op=='touch':
            if run.task and not run.task.done():
                run.stop('Paused for manual control')
            if p.lock.locked():
                raise ValueError('A gesture is finishing. Try again.')
            async with p.lock:
                await p.control(body['action'],body['points'],body.get('duration',.3))
        else:
            raise web.HTTPNotFound()
        return web.json_response({'ok':True})
    async def index(req):
        return web.FileResponse(ROOT/'web/index.html')
    async def lifecycle(app):
        task=asyncio.create_task(desk.scan())
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        for uid in list(desk.phones):
            await desk.remove(uid)
    app.cleanup_ctx.append(lifecycle)
    app.router.add_get('/',index)
    app.router.add_get('/api/phones',state)
    app.router.add_get('/api/{uid}/frame',frame)
    app.router.add_post('/api/{uid}/{op}',action)
    app.router.add_static('/assets',ROOT/'web')
    return app

if __name__=='__main__':
    (ROOT/'build').mkdir(exist_ok=True)
    web.run_app(application(sqlite3.connect(ROOT/'build/history.sqlite')),host='127.0.0.1',port=PORT)
