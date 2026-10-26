import asyncio
import importlib.util
import os
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('proxy',Path(__file__).resolve().parents[1]/'container/proxy.py')
proxy=importlib.util.module_from_spec(spec)
spec.loader.exec_module(proxy)
class ProxyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        os.environ['API_HOST']='api.example'
        self.server=await asyncio.start_server(proxy.handle,'127.0.0.1',0)
        self.port=self.server.sockets[0].getsockname()[1]
    async def asyncTearDown(self):
        self.server.close()
        await self.server.wait_closed()
    async def request(self,header):
        r,w=await asyncio.open_connection('127.0.0.1',self.port)
        w.write(header); await w.drain()
        result=await r.read()
        w.close(); await w.wait_closed()
        return result
    async def test_unrelated_destination_is_rejected(self):
        self.assertIn(b'403 Forbidden',await self.request(b'CONNECT other.example:443 HTTP/1.1\r\n\r\n'))
    async def test_plain_http_is_rejected(self):
        self.assertIn(b'403 Forbidden',await self.request(b'GET http://api.example/ HTTP/1.1\r\n\r\n'))
    async def test_wrong_port_is_rejected(self):
        self.assertIn(b'403 Forbidden',await self.request(b'CONNECT api.example:80 HTTP/1.1\r\n\r\n'))
