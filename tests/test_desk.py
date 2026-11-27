import asyncio
import json
import sqlite3
import unittest
from aiohttp.test_utils import make_mocked_request
from app import application
from server.agent import Run, demo_action
from server.devices import Phone, gesture

class DeskTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.phone=Phone('sandbox','Sandbox',demo=True)
        self.run=Run(self.phone,lambda *args:None,[])

    async def test_watch_and_exit(self):
        self.run.start('Watch the first video for 0.1 seconds then click out')
        await self.run.task
        self.assertEqual((self.phone.screen,self.run.status),('Home','Complete'))
        self.assertIn('Timer completed.',[x['text'] for x in self.run.history])

    async def test_stop_during_timed_scroll(self):
        self.run.start('Scroll Shorts for 5 minutes')
        await asyncio.sleep(1.1)
        before=self.phone.index
        self.run.stop()
        await asyncio.sleep(.1)
        self.assertEqual(self.phone.index,before)
        self.assertGreater(before,1)
        self.assertIsNone(self.run.deadline)

    async def test_followup(self):
        self.run.start('Scroll Shorts for 5 minutes')
        await asyncio.sleep(1)
        self.run.start('Actually stay here for 0.15 seconds')
        await self.run.task
        self.assertEqual(self.run.status,'Complete')
        self.assertEqual(self.phone.index,2)

    async def test_invalid_and_stale(self):
        for points in ([1,2],[0,float('nan')],[False,.2]):
            with self.assertRaises(ValueError): gesture('tap',points)
        self.phone.connected=False
        with self.assertRaises(ValueError): await self.phone.control('tap',[.4,.4])

    async def test_agent_resumes_same_request_when_capture_recovers(self):
        import time
        from unittest.mock import AsyncMock, patch
        p=Phone('usb', 'Physical phone')
        run=Run(p,lambda *args:None,[])
        with patch('server.agent.agent_config',return_value=('test','test')), patch(
            'server.agent.vision',new_callable=AsyncMock,return_value={'action':'done','note':'Ready.'}
        ) as think:
            run.start('Look at the screen')
            await asyncio.sleep(0)
            self.assertEqual(run.status,'Reconnecting screen')
            think.assert_not_awaited()
            p.frame,p.frame_at=b'current',time.monotonic()
            p.frame_event.set()
            await asyncio.wait_for(run.task,1)
            self.assertEqual(run.status,'Complete')
            think.assert_awaited_once()

    async def test_failed_click_and_stale_launch_request_retry_by_clicking(self):
        import time
        from unittest.mock import AsyncMock, patch
        phone = Phone('usb-42', 'iPhone', 'source-42')
        phone.frame, phone.frame_at = b'home screen', time.monotonic()
        run = Run(phone, lambda *args: None, [])
        replies = [
            dict(action='tap', points=[.25, .4]),
            dict(action='launch_app', bundle='com.burbn.instagram'),
            dict(action='tap', points=[.3, .4]),
            dict(action='done', note='Instagram is visible.'),
        ]
        with patch.object(phone, 'observe', new_callable=AsyncMock), \
             patch('server.agent.vision', new=AsyncMock(side_effect=replies)), \
             patch('server.devices.command', new=AsyncMock(side_effect=[ValueError('Click missed.'), b''])) as send:
            await run.work('Open Instagram')
        self.assertEqual(run.status, 'Complete')
        self.assertEqual(len(send.await_args_list), 2)
        for call, x in zip(send.await_args_list, ['16384', '19660']):
            self.assertEqual(call.args[1].name, 'hid_input.py')
            self.assertEqual(call.args[2:4], ('usb-42', 'tap'))
            self.assertEqual(call.args[-2:], (x, '26214'))

    async def test_units(self):
        self.phone.screen='Video'
        self.assertEqual(demo_action(self.phone,'Watch for 2.5 minutes',[])['seconds'],150)

    async def test_http_contract(self):
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        app=application(db)
        async def call(method,path,body=None):
            from unittest.mock import AsyncMock
            req=make_mocked_request(method,path,headers={'Host':'127.0.0.1:8766','Origin':'http://127.0.0.1:8766','Content-Type':'application/json'},app=app)
            req.json=AsyncMock(return_value=body or {})
            route=await app.router.resolve(req)
            req._match_info=route
            res=await app.middlewares[0](req,route.handler)
            return res
        state=json.loads((await call('GET','/api/phones')).body)
        session=state['phones'][0]['session']
        path='/api/sandbox/'
        self.assertEqual((await call('GET',path+'frame?session='+session)).content_type,'image/jpeg')
        self.assertEqual((await call('POST',path+'touch?session='+session,{'action':'tap','points':[.5,.7]})).status,200)
        self.assertEqual((await call('POST',path+'touch?session=old',{'action':'tap','points':[.5,.7]})).status,400)
        for op,data in [('chat',{'message':'Scroll Shorts for 5 minutes'}),('takeover',{}),('stop',{})]:
            self.assertEqual((await call('POST',path+op+'?session='+session,data)).status,200)
