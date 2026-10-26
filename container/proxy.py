"""CONNECT-only proxy: TLS remains end to end and sockets are pinned to tun0."""
import asyncio
import os
import socket

async def relay(reader, writer):
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
        if writer.can_write_eof(): writer.write_eof()
    except (ConnectionError, OSError): pass

async def handle(reader, writer):
    upstream=None
    try:
        header=await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),10)
        method,target,version=header.split(b'\r\n',1)[0].decode('ascii').split()
        if method!='CONNECT' or target.lower()!=os.environ['API_HOST'].lower()+':443':
            writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
            await writer.drain()
            return
        loop=asyncio.get_running_loop()
        infos=await asyncio.wait_for(loop.getaddrinfo(os.environ['API_HOST'],443,family=socket.AF_INET,type=socket.SOCK_STREAM),15)
        sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET,socket.SO_BINDTODEVICE,b'tun0\0')
            sock.setblocking(False)
            await asyncio.wait_for(loop.sock_connect(sock,infos[0][4]),15)
            ur,upstream=await asyncio.open_connection(sock=sock)
        except BaseException:
            sock.close()
            raise
        writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
        await writer.drain()
        tasks=[asyncio.create_task(relay(reader,upstream)),asyncio.create_task(relay(ur,writer))]
        try:
            await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    except (OSError,ValueError,TimeoutError,asyncio.IncompleteReadError,asyncio.LimitOverrunError):
        writer.write(b'HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n')
        try: await writer.drain()
        except ConnectionError: pass
    finally:
        if upstream: upstream.close()
        writer.close()
        try: await writer.wait_closed()
        except ConnectionError: pass

async def main():
    server=await asyncio.start_server(handle,'0.0.0.0',8080,limit=16384)
    async with server: await server.serve_forever()
if __name__=='__main__': asyncio.run(main())
