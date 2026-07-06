import asyncio
import os
import aiohttp
from aiohttp import web

STATIC_DIR = '/app/static'
BACKEND_URL = 'http://backend:8000'
BACKEND_WS_URL = 'ws://backend:8000'

async def handle_index(request):
    return web.FileResponse(os.path.join(STATIC_DIR, 'index.html'))

async def proxy_api(request):
    path = request.match_info.get('path', '')
    query_string = request.query_string
    url = f"{BACKEND_URL}/api/{path}"
    if query_string:
        url = f"{url}?{query_string}"
    
    # 设置较长的超时时间（180秒），避免 LLM 调用超时
    timeout = aiohttp.ClientTimeout(total=180)
    
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.request(
            method=request.method,
            url=url,
            headers={k: v for k, v in request.headers.items() if k.lower() != 'host'},
            data=await request.read(),
        ) as resp:
            body = await resp.read()
            return web.Response(
                body=body,
                status=resp.status,
                headers=dict(resp.headers),
            )

async def proxy_websocket(request):
    """代理 WebSocket 连接到后端"""
    path = request.match_info.get('path', '')
    ws_url = f"{BACKEND_WS_URL}/api/v1/ws/{path}"
    
    # 创建到后端的 WebSocket 连接
    session = aiohttp.ClientSession()
    try:
        backend_ws = await session.ws_connect(ws_url)
    except Exception as e:
        await session.close()
        return web.Response(status=502, text=f"Failed to connect to backend: {e}")
    
    # 创建到客户端的 WebSocket 连接
    client_ws = web.WebSocketResponse()
    await client_ws.prepare(request)
    
    async def forward_to_backend():
        """转发客户端消息到后端"""
        try:
            async for msg in client_ws:
                if msg.type == web.WSMsgType.TEXT:
                    await backend_ws.send_str(msg.data)
                elif msg.type == web.WSMsgType.BINARY:
                    await backend_ws.send_bytes(msg.data)
                elif msg.type == web.WSMsgType.ERROR:
                    break
                elif msg.type == web.WSMsgType.CLOSE:
                    break
        except Exception as e:
            print(f"Error forwarding to backend: {e}")
        finally:
            await backend_ws.close()
            await session.close()
    
    async def forward_to_client():
        """转发后端消息到客户端"""
        try:
            async for msg in backend_ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    await client_ws.send_str(msg.data)
                elif msg.type == aiohttp.WSMsgType.BINARY:
                    await client_ws.send_bytes(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
                elif msg.type == aiohttp.WSMsgType.CLOSE:
                    break
        except Exception as e:
            print(f"Error forwarding to client: {e}")
        finally:
            await client_ws.close()
            await session.close()
    
    # 同时运行两个转发任务
    await asyncio.gather(forward_to_backend(), forward_to_client())
    
    return client_ws

async def health(request):
    return web.json_response({"status": "ok"})

app = web.Application()
app.router.add_get('/health', health)
app.router.add_get('/api/v1/ws/{path:.*}', proxy_websocket)
app.router.add_route('*', '/api/{path:.*}', proxy_api)
# /assets is an app route; /assets/* remains the built static asset directory.
app.router.add_get('/assets', handle_index)
app.router.add_static('/assets/', path=os.path.join(STATIC_DIR, 'assets'), name='assets')

async def spa_fallback(request):
    path = request.match_info.get('path', '')
    file_path = os.path.join(STATIC_DIR, path)
    if os.path.isfile(file_path):
        return web.FileResponse(file_path)
    return web.FileResponse(os.path.join(STATIC_DIR, 'index.html'))

app.router.add_get('/{path:.*}', spa_fallback)

if __name__ == '__main__':
    web.run_app(app, host='0.0.0.0', port=80)
