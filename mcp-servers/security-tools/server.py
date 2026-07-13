"""
Security Tools MCP Server - 统一安全工具服务
合并 nmap、testssl、nuclei、hydra 到一个容器
"""

import asyncio
import json
import re
import socket
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Security Tools MCP Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExecuteRequest(BaseModel):
    tool: str
    params: Dict[str, Any]


# ============== Nmap 工具 ==============

DEFAULT_TCP_VERIFY_PORTS = [
    21, 22, 23, 25, 53, 80, 110, 139, 143, 443, 445, 993, 995,
    1521, 3306, 3389, 5432, 5900, 6379, 8080, 8443, 8888, 27017,
]
HIGH_RISK_PORT_RANGE = ",".join(str(port) for port in DEFAULT_TCP_VERIFY_PORTS)
MAX_NMAP_HOST_TIMEOUT = 180
MAX_COMMAND_TIMEOUT = 300

COMMON_SERVICES = {
    21: "ftp",
    22: "ssh",
    23: "telnet",
    25: "smtp",
    53: "domain",
    80: "http",
    110: "pop3",
    139: "netbios-ssn",
    143: "imap",
    443: "https",
    445: "microsoft-ds",
    993: "imaps",
    995: "pop3s",
    1521: "oracle",
    3306: "mysql",
    3389: "ms-wbt-server",
    5432: "postgresql",
    5900: "vnc",
    6379: "redis",
    8080: "http-proxy",
    8443: "https-alt",
    8888: "sun-answerbook",
    27017: "mongodb",
}


def parse_ports_for_tcp_verify(port_range: str) -> List[int]:
    """Choose a small TCP connect verification set to catch nmap false negatives."""
    if not port_range or str(port_range).lower() in {"high-risk", "high_risk", "critical"}:
        return DEFAULT_TCP_VERIFY_PORTS
    if isinstance(port_range, str) and port_range.startswith("top-"):
        return DEFAULT_TCP_VERIFY_PORTS

    ports = set()
    try:
        for part in str(port_range).split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                start, end = map(int, part.split("-", 1))
                if end - start <= 200:
                    ports.update(range(start, end + 1))
                else:
                    ports.update(p for p in DEFAULT_TCP_VERIFY_PORTS if start <= p <= end)
            else:
                ports.add(int(part))
    except Exception:
        return DEFAULT_TCP_VERIFY_PORTS

    return sorted(ports)


async def verify_tcp_open_ports(target: str, ports: List[int], timeout: float = 2.0) -> List[Dict[str, Any]]:
    """Verify important ports with TCP connect; nmap can false-negative on filtered targets."""
    def connect_once(port: int) -> bool:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            return sock.connect_ex((target, port)) == 0
        finally:
            sock.close()

    async def probe(port: int) -> Optional[Dict[str, Any]]:
        for attempt in range(2):
            try:
                if not await asyncio.to_thread(connect_once, port):
                    continue
                return {
                    "port": port,
                    "protocol": "tcp",
                    "state": "open",
                    "service": COMMON_SERVICES.get(port),
                    "verified_by": "tcp_connect",
                }
            except Exception:
                pass
            if attempt == 0:
                await asyncio.sleep(0.5)
        return None

    results = await asyncio.gather(*(probe(port) for port in ports))
    return [result for result in results if result]


def parse_ignored_filtered_count(output: str) -> int:
    match = re.search(r"Ignored State:\s+filtered\s+\((\d+)\)", output)
    if not match:
        return 0
    try:
        return int(match.group(1))
    except ValueError:
        return 0

async def nmap_scan(params: Dict[str, Any], progress_callback: Optional[callable] = None) -> Dict[str, Any]:
    """执行 nmap 端口扫描"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port_range = params.get("port_range", "high-risk")
    if str(port_range).lower() in {"high-risk", "high_risk", "critical"}:
        port_range = HIGH_RISK_PORT_RANGE
    service_detection = params.get("service_detection", False)  # 默认禁用服务检测以提高速度
    host_timeout = max(15, min(int(params.get("host_timeout", 120)), MAX_NMAP_HOST_TIMEOUT))
    
    cmd = [
        "nmap",
        "-PN",           # 跳过主机发现，直接扫描端口
        "-sT",           # TCP connect 扫描（不需要 root）
        "-T4",           # 使用更快的时间模板
        "-oG", "-",      # 输出格式
        "--host-timeout", f"{host_timeout}s",  # 限制主机扫描时间
        "--max-retries", "2",  # 限制重试次数
        "--min-rate", "100",   # 最小发包速率
    ]
    
    if service_detection:
        cmd.append("-sV")
    
    if isinstance(port_range, str) and port_range.startswith("top-"):
        top_count = port_range.split("-", 1)[1]
        cmd.extend(["--top-ports", top_count, target])
    else:
        cmd.extend(["-p", port_range, target])
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        # 基于时间的进度估算（nmap 在无 TTY 时不输出 --stats-every 进度）
        # 经验值：1000 端口约 33 秒，按端口数线性估算
        def parse_port_count(port_range: str) -> int:
            """解析端口范围返回端口数量"""
            try:
                if port_range.startswith("top-"):
                    return int(port_range.split("-", 1)[1])
                if "," in port_range:
                    return len([p for p in port_range.split(",") if p.strip()])
                if '-' in port_range:
                    start, end = map(int, port_range.split('-'))
                    return end - start + 1
                return 1
            except:
                return 1000
        
        estimated_duration = max(parse_port_count(port_range) * 0.033, 5)  # 约 0.033秒/端口，最少5秒
        max_duration = min(estimated_duration * 3, host_timeout)  # 给 3 倍余量，但不超过 host_timeout
        
        async def estimate_progress():
            if not progress_callback:
                return
            while True:
                elapsed = time.time() - start_time
                # 估算进度：按时间线性，最多到 90%
                progress = min(int((elapsed / max_duration) * 90), 89)
                await progress_callback(progress)
                await asyncio.sleep(1)
        
        # 并行执行进度估算和等待完成
        progress_task = asyncio.create_task(estimate_progress())
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=host_timeout + 30)
        progress_task.cancel()
        
        # 完成时回调 100%
        if progress_callback:
            await progress_callback(100)
        
        output = stdout.decode("utf-8", errors="replace")
        open_ports = []
        filtered_ports = []
        ignored_filtered_count = parse_ignored_filtered_count(output)
        host_status = "unknown"
        
        for line in output.split("\n"):
            if line.startswith("Host:") and "Status:" in line:
                if "Up" in line:
                    host_status = "up"
                elif "Down" in line:
                    host_status = "down"
            if line.startswith("Host:") and "Ports:" in line:
                ports_part = line.split("Ports:", 1)[1]
                for port_entry in ports_part.split(","):
                    port_entry = port_entry.strip()
                    if "/open/" in port_entry:
                        parts = port_entry.split("/")
                        if len(parts) >= 5:
                            open_ports.append({
                                "port": int(parts[0]),
                                "protocol": parts[2],
                                "state": parts[1],
                                "service": parts[4] if len(parts) > 4 else None,
                                "confirmed_open": True,
                            })
                    elif "/filtered/" in port_entry:
                        parts = port_entry.split("/")
                        if len(parts) >= 5:
                            filtered_ports.append({
                                "port": int(parts[0]),
                                "protocol": parts[2],
                                "state": parts[1],
                                "service": parts[4] if len(parts) > 4 else None,
                                "confirmed_open": False,
                                "meaning": "filtered/no-response，未确认开放",
                            })

        tcp_verified_ports = await verify_tcp_open_ports(
            target,
            parse_ports_for_tcp_verify(port_range),
            timeout=params.get("tcp_verify_timeout", 2.0),
        )
        existing_open = {p["port"] for p in open_ports}
        for port in tcp_verified_ports:
            if port["port"] not in existing_open:
                open_ports.append(port)
                existing_open.add(port["port"])
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return {
            "tool": "nmap_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "host_status": host_status,
                "open_ports": open_ports,
                "filtered_ports": filtered_ports,
                "filtered_count": len(filtered_ports) or ignored_filtered_count,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "port_range": port_range,
                "tcp_verified_ports": [p["port"] for p in tcp_verified_ports],
            },
        }
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


# ============== Ping 工具 ==============

async def ping_host(params: Dict[str, Any]) -> Dict[str, Any]:
    """Ping 主机检测可达性"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    count = params.get("count", 3)
    timeout = params.get("timeout", 2)
    
    cmd = ["ping", "-c", str(count), "-W", str(timeout), target]
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
        
        output = stdout.decode("utf-8", errors="replace")
        
        # 解析 ping 结果
        reachable = process.returncode == 0
        packet_loss = 100
        avg_latency = None
        
        # 解析 packet loss
        for line in output.split("\n"):
            if "packet loss" in line:
                # 格式: "3 packets transmitted, 3 received, 0% packet loss"
                parts = line.split(",")
                for part in parts:
                    if "packet loss" in part:
                        loss_str = part.strip().split()[0]
                        packet_loss = int(loss_str.replace("%", ""))
            
            # 解析 avg latency
            if "min/avg/max" in line:
                # 格式: "rtt min/avg/max/mdev = 10.5/10.8/11.2/0.3 ms"
                parts = line.split("=")
                if len(parts) > 1:
                    values = parts[1].strip().split("/")
                    if len(values) >= 2:
                        avg_latency = float(values[1])
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return {
            "tool": "ping_host",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "reachable": reachable,
                "packet_loss": packet_loss,
                "avg_latency_ms": avg_latency,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "ping_time": datetime.utcnow().isoformat(),
                "count": count,
            },
        }
    except asyncio.TimeoutError:
        raise ValueError("ping timeout")
    except Exception as e:
        raise ValueError(f"ping error: {e}")


# ============== TestSSL 工具 ==============

async def testssl_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 testssl.sh SSL/TLS 检测"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port = params.get("port", 443)
    timeout = max(10, min(int(params.get("timeout", 120)), 300))
    
    import tempfile
    import os
    
    # 使用临时文件输出 JSON
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json_file = f.name
    
    cmd = [
        "/testssl/testssl.sh",
        "--jsonfile", json_file,
        "--warnings", "off",
        f"{target}:{port}",
    ]
    
    start_time = time.time()
    process = None
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
        # 读取 JSON 文件
        output = ""
        if os.path.exists(json_file):
            with open(json_file, 'r') as f:
                output = f.read()
            os.remove(json_file)
        
        # 解析 JSON 输出 - testssl.sh 输出扁平 JSON 数组
        tls_version = None
        offered_protocols = []
        certificate = {}
        issues = []
        vulnerabilities = []
        scan_completed = process.returncode == 0
        tool_error = None
        interrupted = False
        
        try:
            # testssl.sh 输出是 JSON 数组
            data = json.loads(output)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        item_id = item.get("id", "")
                        finding = item.get("finding", "")
                        severity = item.get("severity", "")
                        item_id_lower = item_id.lower()
                        finding_lower = str(finding).lower()

                        if item_id_lower in {"engine_problem"}:
                            continue
                        if item_id_lower == "scantime" and "interrupted" in finding_lower:
                            interrupted = True
                            tool_error = "SSL/TLS 扫描被中断，通常表示目标端口不可达、不是 TLS 服务或连接被过滤"
                            continue
                        
                        # 提取 TLS 版本
                        if item_id in {"SSLv2", "SSLv3", "TLS1", "TLS1_1", "TLS1_2", "TLS1_3"}:
                            if "offered" in finding_lower and "not offered" not in finding_lower:
                                offered_protocols.append(item_id)
                            if severity in ["LOW", "WARN", "MEDIUM"] and finding:
                                issues.append(f"{item_id}: {finding}")
                            elif severity in ["HIGH", "CRITICAL"]:
                                vulnerabilities.append({
                                    "id": item_id,
                                    "severity": severity,
                                    "finding": finding,
                                })
                        
                        # 提取证书信息
                        elif "cert" in item_id_lower:
                            if "subject" in item_id_lower:
                                certificate["subject"] = finding
                            elif "issuer" in item_id_lower:
                                certificate["issuer"] = finding
                            elif "expiration" in item_id_lower or "valid" in item_id_lower:
                                certificate["validity"] = finding
                        
                        # 提取问题
                        elif severity in ["LOW", "WARN", "MEDIUM"]:
                            if finding:
                                issues.append(f"{item_id}: {finding}")
                        
                        # 提取漏洞
                        elif severity in ["HIGH", "CRITICAL"]:
                            vulnerabilities.append({
                                "id": item_id,
                                "severity": severity,
                                "finding": finding,
                            })
        except json.JSONDecodeError:
            tool_error = "testssl 未返回可解析的 JSON 结果"
        
        if interrupted:
            scan_completed = False

        def unique_list(items):
            seen = set()
            unique = []
            for item in items:
                key = json.dumps(item, sort_keys=True) if isinstance(item, dict) else str(item)
                if key not in seen:
                    seen.add(key)
                    unique.append(item)
            return unique

        offered_protocols = unique_list(offered_protocols)
        issues = unique_list(issues)
        vulnerabilities = unique_list(vulnerabilities)

        if offered_protocols:
            tls_version = ", ".join(offered_protocols)

        if not tls_version and not certificate and not issues and not vulnerabilities:
            scan_completed = False
            tool_error = tool_error or "未获取到 TLS 协议或证书信息，目标端口可能不可达或不是 HTTPS/TLS 服务"
        elif not scan_completed:
            tool_error = tool_error or "TLS 握手未完成，目标端口可能不是 HTTPS/TLS 服务或连接被中断"
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return {
            "tool": "testssl_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "port": port,
                "reachable": scan_completed,
                "scan_completed": scan_completed,
                "tls_version": tls_version,
                "certificate": certificate if certificate else None,
                "issues": issues,
                "vulnerabilities": vulnerabilities,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "returncode": process.returncode,
            },
        }
    except asyncio.TimeoutError:
        if process and process.returncode is None:
            process.kill()
            await process.communicate()
        if os.path.exists(json_file):
            os.remove(json_file)
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "tool": "testssl_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "port": port,
                "reachable": False,
                "scan_completed": False,
                "tls_version": None,
                "certificate": None,
                "issues": [],
                "vulnerabilities": [],
                "tool_error": f"SSL/TLS 扫描在 {timeout} 秒后超时，目标可能限速、被过滤或响应过慢",
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "timed_out": True,
            },
        }
    except Exception as e:
        if os.path.exists(json_file):
            os.remove(json_file)
        raise ValueError(f"testssl scan error: {e}")


# ============== Nuclei 工具 ==============

async def nuclei_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 nuclei 漏洞扫描"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    templates = params.get("templates")
    severity = params.get("severity")
    
    cmd = ["nuclei", "-target", target, "-t", "/root/nuclei-templates", "-jsonl", "-silent"]
    
    if templates:
        cmd.extend(["-tags", templates])
    if severity:
        cmd.extend(["-severity", severity])
    
    cmd.extend(["-timeout", "30", "-retries", "2"])
    
    start_time = time.time()
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        timeout = max(30, min(int(params.get("timeout", 180)), MAX_COMMAND_TIMEOUT))
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
        output = stdout.decode("utf-8", errors="replace")
        stderr_text = stderr.decode("utf-8", errors="replace").strip()
        findings = []
        
        for line in output.strip().split("\n"):
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                info = data.get("info") or {}
                template_id = data.get("template-id") or data.get("template_id")
                if template_id or info:
                    findings.append({
                        "template_id": template_id,
                        "name": info.get("name") or template_id,
                        "severity": info.get("severity") or "info",
                        "host": data.get("host"),
                        "matched_at": data.get("matched-at") or data.get("matched_at"),
                        "type": data.get("type"),
                        "matcher_name": data.get("matcher-name") or data.get("matcher_name"),
                        "extracted_results": data.get("extracted-results") or data.get("extracted_results") or [],
                        "description": info.get("description"),
                        "tags": info.get("tags") or [],
                        "reference": info.get("reference") or [],
                    })
            except json.JSONDecodeError:
                continue
        
        duration_ms = int((time.time() - start_time) * 1000)
        scan_completed = process.returncode == 0
        tool_error = stderr_text or None
        if "no templates provided" in stderr_text.lower():
            scan_completed = False
            tool_error = "nuclei 模板缺失，漏洞扫描未实际执行；请更新 nuclei templates"
        elif "could not run nuclei" in stderr_text.lower():
            scan_completed = False
        
        return {
            "tool": "nuclei_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": target,
                "findings": findings,
                "total_findings": len(findings),
                "scan_completed": scan_completed,
                "templates": templates,
                "severity_filter": severity,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "returncode": process.returncode,
            },
        }
    except asyncio.TimeoutError:
        if "process" in locals() and process.returncode is None:
            process.kill()
            await process.wait()
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "tool": "nuclei_scan",
            "version": "1.0",
            "status": "failed",
            "error": f"nuclei 扫描超过 {timeout} 秒仍未完成，已停止；可缩小目标范围或提高 timeout 后重试",
            "data": {
                "target": target,
                "findings": [],
                "total_findings": 0,
                "scan_completed": False,
                "templates": templates,
                "severity_filter": severity,
                "tool_error": "nuclei scan timeout",
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "timeout_seconds": timeout,
            },
        }
    except Exception as e:
        raise ValueError(f"nuclei scan error: {e}")


# ============== Hydra 工具 ==============

COMMON_USERNAMES = ["admin", "root", "administrator", "user", "test", "guest"]
COMMON_PASSWORDS = ["admin", "123456", "password", "root", "admin123", "P@ssw0rd", "test", "12345678"]

async def hydra_bruteforce(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 hydra 暴力破解（批量模式）"""
    import tempfile
    import os
    
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    service = params.get("service", "ssh")
    port = params.get("port", 22)
    usernames = [str(value) for value in (params.get("usernames") or COMMON_USERNAMES)]
    passwords = [str(value) for value in (params.get("passwords") or COMMON_PASSWORDS)]
    max_attempts = max(1, min(int(params.get("max_attempts", 48)), 100))
    credentials = [
        (username, password)
        for username in usernames
        for password in passwords
    ][:max_attempts]
    if not credentials:
        raise ValueError("至少提供一个用户名和密码组合")
    
    # 写入临时文件
    credential_file = None
    output_file = None
    
    try:
        credential_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        credential_file.write('\n'.join(f"{username}:{password}" for username, password in credentials))
        credential_file.close()
        output_file = tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.txt')
        output_file.close()
        
        # 构建 hydra 命令（批量模式）
        cmd = [
            "hydra",
            "-C", credential_file.name,
            "-s", str(port),
            "-t", "2",           # 2 个并发线程（减少以避免触发防火墙）
            "-u",                # 每个用户找到密码后停止
            "-F",                # 找到第一个成功就停止
            "-o", output_file.name,
            target,
            service,
        ]
        
        start_time = time.time()
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        
        timeout = max(30, min(int(params.get("timeout", 180)), MAX_COMMAND_TIMEOUT))
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        
        output = stdout.decode("utf-8", errors="replace")
        stderr_output = stderr.decode("utf-8", errors="replace")
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 解析结果
        found = []
        
        # 从输出中解析
        for line in output.split('\n'):
            if 'login:' in line and 'password:' in line:
                # 格式: host: 192.168.1.1   login: root   password: admin
                parts = line.split()
                username = None
                password = None
                for i, part in enumerate(parts):
                    if part == 'login:' and i + 1 < len(parts):
                        username = parts[i + 1]
                    if part == 'password:' and i + 1 < len(parts):
                        password = parts[i + 1]
                if username and password:
                    found.append({
                        "username": username,
                        "password": password,
                        "service": service,
                        "port": port,
                    })
        
        # 也尝试从输出文件读取
        if output_file and os.path.exists(output_file.name):
            with open(output_file.name, "r") as f:
                for line in f:
                    if 'login:' in line and 'password:' in line:
                        parts = line.split()
                        username = None
                        password = None
                        for i, part in enumerate(parts):
                            if part == 'login:' and i + 1 < len(parts):
                                username = parts[i + 1]
                            if part == 'password:' and i + 1 < len(parts):
                                password = parts[i + 1]
                        if username and password:
                            # 避免重复
                            if not any(f["username"] == username and f["password"] == password for f in found):
                                found.append({
                                    "username": username,
                                    "password": password,
                                    "service": service,
                                    "port": port,
                                })
        tool_error = None
        scan_completed = True
        if process.returncode not in (0, 1, 255):
            scan_completed = False
            tool_error = stderr_output.strip() or output.strip() or f"hydra exited with code {process.returncode}"
        elif any(text in (stderr_output + output).lower() for text in ["connection refused", "timeout", "could not connect", "unknown service", "no route to host"]):
            scan_completed = False
            tool_error = (stderr_output.strip() or output.strip())[:1000]
        
        return {
            "tool": "hydra_bruteforce",
            "version": "2.0",
            "status": "success",
            "data": {
                "target": target,
                "service": service,
                "port": port,
                "found": found,
                "tested_users": len({username for username, _ in credentials}),
                "tested_passwords": len({password for _, password in credentials}),
                "total_combinations": len(credentials),
                "scan_completed": scan_completed,
                "tool_error": tool_error,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "returncode": process.returncode,
            },
        }
        
    finally:
        # 清理临时文件
        if credential_file and os.path.exists(credential_file.name):
            os.remove(credential_file.name)
        if output_file and os.path.exists(output_file.name):
            os.remove(output_file.name)


# ============== API 端点 ==============

# 异步任务存储
SCAN_TASKS = {}

@app.get("/")
async def root():
    return {
        "name": "Security Tools MCP Server",
        "version": "1.0.0",
        "tools": ["nmap_scan", "testssl_scan", "nuclei_scan", "hydra_bruteforce", "ping_host"],
    }


@app.get("/health")
async def health():
    """健康检查"""
    tools_status = {}
    
    # 检查 nmap
    try:
        result = subprocess.run(["nmap", "--version"], capture_output=True, timeout=5)
        tools_status["nmap"] = result.returncode == 0
    except:
        tools_status["nmap"] = False
    
    # 检查 testssl
    try:
        result = subprocess.run(["/testssl/testssl.sh", "--version"], capture_output=True, timeout=5)
        tools_status["testssl"] = result.returncode == 0
    except:
        tools_status["testssl"] = False
    
    # 检查 nuclei
    try:
        result = subprocess.run(["nuclei", "-version"], capture_output=True, timeout=5)
        tools_status["nuclei"] = result.returncode == 0
    except:
        tools_status["nuclei"] = False
    
    # 检查 hydra
    try:
        result = subprocess.run(["hydra", "-h"], capture_output=True, timeout=5)
        tools_status["hydra"] = True  # hydra 返回非 0 但可用
    except:
        tools_status["hydra"] = False
    
    all_available = all(tools_status.values())
    
    return {
        "status": "healthy" if all_available else "degraded",
        "tools": ["nmap_scan", "testssl_scan", "nuclei_scan", "hydra_bruteforce"],
        "tools_status": tools_status,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """执行工具"""
    tool_name = request.tool
    params = request.params

    # 支持别名
    tool_aliases = {
        "scan_ports": "nmap_scan",
        "scan_ssl": "testssl_scan",
        "scan_vulnerabilities": "nuclei_scan",
        "scan_weak_passwords": "hydra_bruteforce",
        "ping_asset": "ping_host",
    }
    tool_name = tool_aliases.get(tool_name, tool_name)

    if tool_name == "nmap_scan":
        return await nmap_scan(params)
    elif tool_name == "testssl_scan":
        return await testssl_scan(params)
    elif tool_name == "nuclei_scan":
        return await nuclei_scan(params)
    elif tool_name == "hydra_bruteforce":
        return await hydra_bruteforce(params)
    elif tool_name == "ping_host":
        return await ping_host(params)
    else:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")


# ============== 异步扫描支持 ==============

import uuid
import re

async def run_async_nmap(task_id: str, params: Dict[str, Any]):
    """异步执行 nmap 扫描 - 带真实进度更新"""
    async def update_progress(progress: int):
        SCAN_TASKS[task_id]["progress"] = progress
    
    try:
        SCAN_TASKS[task_id]["status"] = "running"
        SCAN_TASKS[task_id]["progress"] = 0
        
        # 使用带进度回调的 nmap_scan
        result = await nmap_scan(params, progress_callback=update_progress)
        
        SCAN_TASKS[task_id]["status"] = "completed"
        SCAN_TASKS[task_id]["progress"] = 100
        SCAN_TASKS[task_id]["result"] = result
        
    except Exception as e:
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            SCAN_TASKS[task_id]["error"] = f"nmap scan timeout: {error_msg}"
        elif "permission" in error_msg.lower():
            SCAN_TASKS[task_id]["error"] = f"nmap permission denied (try running as root): {error_msg}"
        else:
            SCAN_TASKS[task_id]["error"] = f"nmap scan error: {error_msg}"
        SCAN_TASKS[task_id]["status"] = "failed"


async def run_async_nuclei(task_id: str, params: Dict[str, Any]):
    """异步执行 nuclei 扫描"""
    async def update_progress(progress: int):
        SCAN_TASKS[task_id]["progress"] = progress
    
    try:
        SCAN_TASKS[task_id]["status"] = "running"
        SCAN_TASKS[task_id]["progress"] = 0
        
        # 启动进度估算任务
        async def estimate_progress():
            start_time = time.time()
            estimated_duration = 120  # nuclei 通常 1-2 分钟
            while SCAN_TASKS[task_id]["status"] == "running":
                elapsed = time.time() - start_time
                progress = min(int((elapsed / estimated_duration) * 90), 89)
                SCAN_TASKS[task_id]["progress"] = progress
                await asyncio.sleep(2)
        
        progress_task = asyncio.create_task(estimate_progress())
        
        result = await nuclei_scan(params)
        
        progress_task.cancel()
        
        SCAN_TASKS[task_id]["status"] = "completed"
        SCAN_TASKS[task_id]["progress"] = 100
        SCAN_TASKS[task_id]["result"] = result
        
    except Exception as e:
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            SCAN_TASKS[task_id]["error"] = f"nuclei scan timeout: {error_msg}"
        else:
            SCAN_TASKS[task_id]["error"] = f"nuclei scan error: {error_msg}"
        SCAN_TASKS[task_id]["status"] = "failed"


async def run_async_hydra(task_id: str, params: Dict[str, Any]):
    """异步执行 hydra 暴力破解"""
    async def update_progress(progress: int):
        SCAN_TASKS[task_id]["progress"] = progress
    
    try:
        SCAN_TASKS[task_id]["status"] = "running"
        SCAN_TASKS[task_id]["progress"] = 0
        
        async def estimate_progress():
            start_time = time.time()
            estimated_duration = 180  # hydra 可能需要更久
            while SCAN_TASKS[task_id]["status"] == "running":
                elapsed = time.time() - start_time
                progress = min(int((elapsed / estimated_duration) * 90), 89)
                SCAN_TASKS[task_id]["progress"] = progress
                await asyncio.sleep(3)
        
        progress_task = asyncio.create_task(estimate_progress())
        
        result = await hydra_bruteforce(params)
        
        progress_task.cancel()
        
        SCAN_TASKS[task_id]["status"] = "completed"
        SCAN_TASKS[task_id]["progress"] = 100
        SCAN_TASKS[task_id]["result"] = result
        
    except Exception as e:
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            SCAN_TASKS[task_id]["error"] = f"hydra scan timeout: {error_msg}"
        else:
            SCAN_TASKS[task_id]["error"] = f"hydra scan error: {error_msg}"
        SCAN_TASKS[task_id]["status"] = "failed"


async def run_async_testssl(task_id: str, params: Dict[str, Any]):
    """异步执行 testssl 扫描"""
    async def update_progress(progress: int):
        SCAN_TASKS[task_id]["progress"] = progress
    
    try:
        SCAN_TASKS[task_id]["status"] = "running"
        SCAN_TASKS[task_id]["progress"] = 0
        
        async def estimate_progress():
            start_time = time.time()
            estimated_duration = 60  # testssl 通常较快
            while SCAN_TASKS[task_id]["status"] == "running":
                elapsed = time.time() - start_time
                progress = min(int((elapsed / estimated_duration) * 90), 89)
                SCAN_TASKS[task_id]["progress"] = progress
                await asyncio.sleep(1)
        
        progress_task = asyncio.create_task(estimate_progress())
        
        result = await testssl_scan(params)
        
        progress_task.cancel()
        
        SCAN_TASKS[task_id]["status"] = "completed"
        SCAN_TASKS[task_id]["progress"] = 100
        SCAN_TASKS[task_id]["result"] = result
        
    except Exception as e:
        error_msg = str(e)
        if "timeout" in error_msg.lower():
            SCAN_TASKS[task_id]["error"] = f"testssl scan timeout: {error_msg}"
        else:
            SCAN_TASKS[task_id]["error"] = f"testssl scan error: {error_msg}"
        SCAN_TASKS[task_id]["status"] = "failed"


@app.post("/scan/start")
async def start_scan(request: ExecuteRequest):
    """启动异步扫描"""
    tool_name = request.tool
    params = request.params
    
    # scan_ports 是 nmap_scan 的别名
    if tool_name == "scan_ports":
        tool_name = "nmap_scan"
    
    if tool_name not in ["nmap_scan", "nuclei_scan", "hydra_bruteforce", "testssl_scan"]:
        raise HTTPException(status_code=400, detail="Only nmap_scan, nuclei_scan, hydra_bruteforce, testssl_scan support async mode")
    
    task_id = str(uuid.uuid4())
    SCAN_TASKS[task_id] = {
        "task_id": task_id,
        "tool": tool_name,
        "params": params,
        "status": "pending",
        "result": None,
        "error": None,
        "progress": 0,
    }
    
    # 启动对应的异步任务
    if tool_name == "nmap_scan":
        asyncio.create_task(run_async_nmap(task_id, params))
    elif tool_name == "nuclei_scan":
        asyncio.create_task(run_async_nuclei(task_id, params))
    elif tool_name == "hydra_bruteforce":
        asyncio.create_task(run_async_hydra(task_id, params))
    elif tool_name == "testssl_scan":
        asyncio.create_task(run_async_testssl(task_id, params))
    
    return {
        "task_id": task_id,
        "status": "started",
        "message": "Scan started",
    }


@app.get("/scan/{task_id}/progress")
async def get_scan_progress(task_id: str):
    """获取扫描进度"""
    if task_id not in SCAN_TASKS:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = SCAN_TASKS[task_id]
    return {
        "task_id": task_id,
        "status": task["status"],
        "progress": task.get("progress", 100 if task["status"] == "completed" else 0),
    }


@app.get("/scan/{task_id}/result")
async def get_scan_result(task_id: str):
    """获取扫描结果"""
    if task_id not in SCAN_TASKS:
        raise HTTPException(status_code=404, detail="Task not found")
    
    task = SCAN_TASKS[task_id]
    if task["status"] != "completed":
        raise HTTPException(status_code=400, detail="Task not completed yet")
    
    return task["result"]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8010)
