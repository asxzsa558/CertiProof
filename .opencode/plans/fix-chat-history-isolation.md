# 修复对话历史项目隔离问题

## 问题根因

**真正的根因**：前端代理服务器 (`serve.py`) 没有传递查询字符串。

当前端发送 `GET /api/v1/chat/history?project_id=5` 时：
1. 前端代理 (`serve.py`) 接收到请求
2. 代理函数只提取了 `path`（`v1/chat/history`），**丢弃了查询字符串** `?project_id=5`
3. 代理向后端发送 `GET http://backend:8000/api/v1/chat/history`（没有查询参数）
4. 后端 FastAPI 接收到 `project_id=None`
5. 后端返回所有项目的对话历史（没过滤）

## 修复方案

### 修改 `frontend/serve.py` 的 `proxy_api` 函数

**当前代码**（第 13-32 行）：
```python
async def proxy_api(request):
    path = request.match_info.get('path', '')
    url = f"{BACKEND_URL}/api/{path}"
    
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
```

**修复后**：
```python
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
```

**关键改动**：
- 第 15 行：提取查询字符串 `query_string = request.query_string`
- 第 17-18 行：如果有查询字符串，附加到 URL

## 验证步骤

1. 重建前端容器：
   ```bash
   docker-compose build frontend
   docker-compose up -d frontend
   ```

2. 硬刷新浏览器（Cmd+Shift+R）

3. 检查后端日志，确认 `project_id` 被正确解析：
   ```bash
   docker logs certiproof-backend --tail 50 | grep "get_chat_history"
   ```
   应该看到 `project_id=5` 而不是 `project_id=None`

4. 测试项目隔离：
   - 切换到项目 A（ID=5），发送消息
   - 切换到项目 B（ID=6），应该看不到项目 A 的消息
   - 切换回项目 A，应该能看到之前的消息

## 预期结果

- 后端正确接收 `project_id` 参数
- 对话历史按项目隔离
- 每个项目只显示自己的对话记录
