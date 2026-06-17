"""
TestSSL MCP Server - SSL/TLS 检测工具
使用 testssl.sh 进行 SSL/TLS 配置检测，返回标准化 JSON 格式
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
import subprocess
import json
from datetime import datetime
import time

app = FastAPI(title="TestSSL MCP Server", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExecuteRequest(BaseModel):
    """执行请求"""
    tool: str
    params: Dict[str, Any]


class SSLCheckResult(BaseModel):
    """SSL 检查结果"""
    target: str
    port: int
    tls_version: Optional[str] = None
    cipher_suites: List[str] = []
    certificate: Optional[Dict[str, Any]] = None
    issues: List[str] = []
    vulnerabilities: List[Dict[str, Any]] = []


def parse_testssl_output(output: str, target: str, port: int) -> SSLCheckResult:
    """解析 testssl.sh 输出"""
    result = SSLCheckResult(
        target=target,
        port=port,
    )
    
    # 解析 JSON 输出
    try:
        data = json.loads(output)
        
        # TLS 版本
        for item in data:
            if item.get("id") == "protocol_support":
                if item.get("finding"):
                    result.tls_version = item["finding"]
            
            # 加密套件
            if item.get("id") == "cipher_list":
                if item.get("finding"):
                    result.cipher_suites = item["finding"].split("\n")
            
            # 证书信息
            if item.get("id") == "cert_serialNumber":
                result.certificate = result.certificate or {}
                result.certificate["serial_number"] = item.get("finding")
            
            if item.get("id") == "cert_subject":
                result.certificate = result.certificate or {}
                result.certificate["subject"] = item.get("finding")
            
            if item.get("id") == "cert_issuer":
                result.certificate = result.certificate or {}
                result.certificate["issuer"] = item.get("finding")
            
            if item.get("id") == "cert_notAfter":
                result.certificate = result.certificate or {}
                result.certificate["not_after"] = item.get("finding")
            
            # 漏洞
            if item.get("severity") in ["HIGH", "CRITICAL"]:
                result.vulnerabilities.append({
                    "id": item.get("id"),
                    "severity": item.get("severity"),
                    "finding": item.get("finding"),
                    "cve": item.get("cve"),
                })
            
            # 问题
            if item.get("finding") and "WARN" in str(item.get("finding")):
                result.issues.append(item["finding"])
    
    except json.JSONDecodeError:
        # 如果不是 JSON，尝试解析文本输出
        result.issues.append("Failed to parse testssl output as JSON")
    
    return result


async def testssl_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """执行 testssl.sh 扫描"""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")
    
    port = params.get("port", 443)
    
    # 构建 testssl.sh 命令
    cmd = [
        "/testssl/testssl.sh",
        "--json",
        "--warnings", "off",
        f"{target}:{port}",
    ]
    
    # 执行 testssl.sh
    start_time = time.time()
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        
        # 解析输出
        parsed = parse_testssl_output(result.stdout, target, port)
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        # 返回标准格式
        return {
            "tool": "testssl_scan",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": parsed.target,
                "port": parsed.port,
                "tls_version": parsed.tls_version,
                "cipher_suites": parsed.cipher_suites,
                "certificate": parsed.certificate,
                "issues": parsed.issues,
                "vulnerabilities": parsed.vulnerabilities,
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
            },
        }
    
    except subprocess.TimeoutExpired:
        raise ValueError("testssl scan timeout")
    except Exception as e:
        raise ValueError(f"testssl scan error: {e}")


@app.get("/")
async def root():
    """根路径"""
    return {
        "name": "TestSSL MCP Server",
        "version": "1.0.0",
        "tools": ["testssl_scan", "ssl_check"],
    }


@app.get("/health")
async def health():
    """健康检查"""
    # 检查 testssl.sh 是否可用
    try:
        result = subprocess.run(
            ["/testssl/testssl.sh", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        testssl_available = result.returncode == 0
    except:
        testssl_available = False
    
    return {
        "status": "healthy" if testssl_available else "degraded",
        "tools": ["testssl_scan", "ssl_check"],
        "testssl_available": testssl_available,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """执行工具"""
    tool_name = request.tool
    params = request.params
    
    if tool_name in ["testssl_scan", "ssl_check"]:
        return await testssl_scan(params)
    
    raise HTTPException(
        status_code=404,
        detail=f"Unknown tool: {tool_name}"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
