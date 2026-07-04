# 修复 nmap 扫描超时问题

## 问题分析
- 默认扫描所有 65535 个端口，速度很慢
- 使用 TCP connect 扫描（-sT），比 SYN 扫描慢
- 没有设置主机超时限制
- 如果目标不可达，会等待很久

## 修改文件
`mcp-servers/security-tools/server.py`

## 修改内容

### 1. 修改 nmap_scan 函数（第35-106行）

**当前代码：**
```python
port_range = params.get("port_range", "1-65535")
service_detection = params.get("service_detection", True)
if port_range == "1-65535":
    service_detection = False

cmd = ["nmap", "-sT", "-T3", "-oG", "-"]
if service_detection:
    cmd.append("-sV")
cmd.extend(["-p", port_range, target])
```

**修改为：**
```python
port_range = params.get("port_range", "1-1000")  # 默认只扫描前1000个常用端口
service_detection = params.get("service_detection", False)  # 默认禁用服务检测以提高速度
host_timeout = params.get("host_timeout", 300)  # 主机超时300秒

cmd = [
    "nmap",
    "-sS",           # 使用 SYN 扫描（更快，但需要 root）
    "-T4",           # 使用更快的时间模板
    "-oG", "-",      # 输出格式
    "--host-timeout", f"{host_timeout}s",  # 限制主机扫描时间
    "--max-retries", "2",  # 限制重试次数
    "--min-rate", "100",   # 最小发包速率
]

if service_detection:
    cmd.append("-sV")

cmd.extend(["-p", port_range, target])
```

### 2. 添加错误处理改进

在异常处理中添加更详细的错误信息：

```python
except asyncio.TimeoutError:
    raise ValueError(f"nmap scan timeout after {host_timeout}s")
except Exception as e:
    error_msg = str(e)
    if "timeout" in error_msg.lower():
        raise ValueError(f"nmap scan timeout: {error_msg}")
    elif "permission" in error_msg.lower():
        raise ValueError(f"nmap permission denied (try running as root): {error_msg}")
    else:
        raise ValueError(f"nmap scan error: {error_msg}")
```

## 实施步骤

1. 修改 `mcp-servers/security-tools/server.py`
2. 重新构建 security-tools：`docker-compose build security-tools`
3. 重启容器：`docker-compose up -d security-tools`
4. 测试扫描功能

## 测试计划

### 测试用例

1. **快速扫描**
   - 输入：`扫描 121.40.95.31 端口`
   - 预期：在 300 秒内完成，显示开放端口

2. **指定端口范围**
   - 输入：`扫描 121.40.95.31 端口 22,80,443`
   - 预期：只扫描指定端口，速度更快

3. **全端口扫描**
   - 输入：`全端口扫描 121.40.95.31`
   - 预期：扫描所有端口，但受 300 秒超时限制

### 验证点

- [ ] 扫描在合理时间内完成
- [ ] 超时错误信息清晰
- [ ] 权限错误提示友好
- [ ] 不同端口范围的扫描正常

## 回滚方案

如果出现问题，可以回滚到上一个版本：
```bash
git checkout HEAD~1 mcp-servers/security-tools/server.py
docker-compose build security-tools
docker-compose up -d security-tools
```
