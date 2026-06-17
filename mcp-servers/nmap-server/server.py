"""
Nmap MCP Server - 端口扫描工具
使用 nmap 进行端口扫描，返回标准化 JSON 格式
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
import time

app = FastAPI(title="Nmap MCP Server", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 高危端口定义
CRITICAL_PORTS = {
    3306: "MySQL",
    5432: "PostgreSQL",
    1433: "MSSQL",
    1521: "Oracle",
    6379: "Redis",
    27017: "MongoDB",
    9200: "Elasticsearch",
    11211: "Memcached",
    23: "Telnet",
    21: "FTP",
    135: "MSRPC",
    139: "NetBIOS",
    445: "SMB",
    5900: "VNC",
}

HIGH_RISK_PORTS = {
    22: "SSH",
    25: "SMTP",
    53: "DNS",
    110: "POP3",
    143: "IMAP",
    3389: "RDP",
    8080: "HTTP-Proxy",
    8443: "HTTPS-Alt",
}


class ExecuteRequest(BaseModel):
    """执行请求"""
    tool: str
    params: Dict[str, Any]


class PortInfo(BaseModel):
    """端口信息"""
    port: int
    protocol: str
    state: str
    service: Optional[str] = None
    version: Optional[str] = None
    risk_level: str = "info"


class NmapScanResult(BaseModel):
    """nmap 扫描结果"""
    target: str
    host_status: str
    open_ports: List[PortInfo] = []
    os_guess: Optional[str] = None


def classify_port_risk(port: int) -> str:
    """分类端口风险等级"""
    if port in CRITICAL_PORTS:
        return "critical"
    if port in HIGH_RISK_PORTS:
        return "high"
    if port in [80, 443]:
        return "low"
    return "medium"


def parse_nmap_xml(xml_content: str, target: str) -> NmapScanResult:
    """解析 nmap XML 输出"""
    result = NmapScanResult(
        target=target,
        host_status="unknown",
        open_ports=[],
    )
    
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as e:
        raise ValueError(f"Failed to parse nmap XML: {e}")
    
    for host in root.findall(".//host"):
        # 主机状态
        status_elem = host.find("status")
        if status_elem is not None:
            result.host_status = status_elem.get("state", "unknown")
        
        # 端口信息
        for port_elem in host.findall(".//port"):
            port_id = int(port_elem.get("portid", 0))
            protocol = port_elem.get("protocol", "tcp")
            
            state_elem = port_elem.find("state")
            state = state_elem.get("state", "unknown") if state_elem is not None else "unknown"
            
            if state != "open":
                continue
            
            # 服务信息
            service = None
            version = None
            service_elem = port_elem.find("service")
            if service_elem is not None:
                service = service_elem.get("name")
                product = service_elem.get("product", "")
                ver = service_elem.get("version", "")
                if product or ver:
                    version = f"{product} {ver}".strip()
            
            # 风险等级
            risk_level = classify_port_risk(port_id)
            
            result.open_ports.append(PortInfo(
                port=port_id,
                protocol=protocol,
                state=state,
                service=service,
                version=version,
                risk_level=risk_level,
            ))
        
        # OS 识别
        for os_elem in host.findall(".//osmatch"):
            result.os_guess = os_elem.get("name")
            break
    
    return result


async def nmap_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 nmap 扫描"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port_range = params.get("port_range", "1-1000")
    service_detection = params.get("service_detection", True)
    os_detection = params.get("os_detection", False)
    
    # 构建 nmap 命令
    cmd = ["nmap", "-oX", "-", "-sT"]  # TCP connect scan, XML output
    
    if service_detection:
        cmd.append("-sV")
    
    if os_detection:
        cmd.append("-O")
    
    cmd.extend(["-p", port_range, target])
    
    # 执行 nmap
    start_time = time.time()
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        
        if result.returncode != 0:
            raise ValueError(f"nmap error: {result.stderr}")
        
        # 解析 XML
        parsed = parse_nmap_xml(result.stdout, target)
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 返回标准格式
        return {
            "tool": "nmap_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": parsed.target,
                "host_status": parsed.host_status,
                "open_ports": [p.model_dump() for p in parsed.open_ports],
                "os_guess": parsed.os_guess,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
                "port_range": port_range,
            },
        }
    
    except subprocess.TimeoutExpired:
        raise ValueError("nmap scan timeout")
    except Exception as e:
        raise ValueError(f"nmap scan error: {e}")


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "Nmap MCP Server",
        "version": "1.0.0",
        "tools": ["nmap_scan", "port_scan"],
    }


@app.get("/health")
async def health():
    """健康检查"""
    # 检查 nmap 是否可用
    try:
        result = subprocess.run(
            ["nmap", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        nmap_available = result.returncode == 0
    except:
        nmap_available = False
    
    return {
        "status": "healthy" if nmap_available else "degraded",
        "tools": ["nmap_scan", "port_scan"],
        "nmap_available": nmap_available,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """执行工具"""
    tool_name = request.tool
    params = request.params
    
    if tool_name in ["nmap_scan", "port_scan"]:
        return await nmap_scan(params)
    
    raise HTTPException(
        status_code=404,
        detail=f"Unknown tool: {tool_name}"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
