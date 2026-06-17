"""
Real Scan Service - CertiProof
Robust port scanner with service detection.
Uses subprocess to call nmap if available, falls back to native socket scan.
"""

import socket
import ssl
import subprocess
import shutil
import asyncio
import re
import struct
from datetime import datetime
from typing import List, Dict, Any, Optional
from concurrent.futures import ThreadPoolExecutor


# Common ports and their services (used when nmap service detection is not available)
COMMON_PORTS = {
    21: ("FTP", "file transfer"),
    22: ("SSH", "remote access"),
    23: ("Telnet", "remote access (insecure)"),
    25: ("SMTP", "email"),
    53: ("DNS", "domain name"),
    80: ("HTTP", "web"),
    110: ("POP3", "email"),
    111: ("RPC", "remote procedure call"),
    135: ("MSRPC", "windows rpc"),
    139: ("NetBIOS", "windows networking"),
    143: ("IMAP", "email"),
    443: ("HTTPS", "secure web"),
    445: ("SMB", "windows file sharing"),
    993: ("IMAPS", "secure email"),
    995: ("POP3S", "secure email"),
    1433: ("MSSQL", "database"),
    1521: ("Oracle", "database"),
    3306: ("MySQL", "database"),
    3389: ("RDP", "remote desktop"),
    5432: ("PostgreSQL", "database"),
    5900: ("VNC", "remote desktop"),
    6379: ("Redis", "cache/database"),
    8080: ("HTTP-Proxy", "web proxy"),
    8443: ("HTTPS-Alt", "secure web alt"),
    9200: ("Elasticsearch", "search"),
    11211: ("Memcached", "cache"),
    27017: ("MongoDB", "database"),
}

# High risk ports
HIGH_RISK_PORTS = {
    23: "critical",   # Telnet
    135: "critical",  # MSRPC
    139: "critical",  # NetBIOS
    445: "critical",  # SMB
    1433: "critical", # MSSQL
    1521: "critical", # Oracle
    3306: "critical", # MySQL
    3389: "critical", # RDP
    5432: "critical", # PostgreSQL
    5900: "critical", # VNC
    6379: "critical", # Redis
    9200: "critical", # Elasticsearch
    11211: "critical",# Memcached
    27017: "critical",# MongoDB
}

MEDIUM_RISK_PORTS = {
    21: "medium",   # FTP
    22: "medium",   # SSH
    25: "medium",   # SMTP
    80: "low",      # HTTP
    443: "low",     # HTTPS
    8080: "medium", # HTTP-Proxy
    8443: "medium", # HTTPS-Alt
}

LOW_RISK_PORTS = {53: "info", 110: "medium", 143: "medium"}


def check_nmap_available() -> bool:
    """Check if nmap is installed and available."""
    return shutil.which("nmap") is not None


def parse_nmap_output(xml_output: str) -> Dict[str, Any]:
    """Parse nmap XML output into structured data."""
    import xml.etree.ElementTree as ET
    
    result = {
        "host": "",
        "scan_time": datetime.utcnow().isoformat(),
        "open_ports": [],
        "os_guess": None,
        "host_status": "unknown",
        "scanner": "nmap",
    }
    
    try:
        root = ET.fromstring(xml_output)
    except ET.ParseError:
        return None
    
    for host in root.findall(".//host"):
        status_elem = host.find("status")
        if status_elem is not None:
            result["host_status"] = status_elem.get("state", "unknown")
        
        address_elem = host.find("address[@addrtype='ipv4']")
        if address_elem is not None:
            result["host"] = address_elem.get("addr", "")
        
        for port_elem in host.findall(".//port"):
            port_id = int(port_elem.get("portid", 0))
            protocol = port_elem.get("protocol", "tcp")
            
            state_elem = port_elem.find("state")
            state = state_elem.get("state", "unknown") if state_elem is not None else "unknown"
            
            if state != "open":
                continue
            
            service = None
            version = None
            product = None
            
            service_elem = port_elem.find("service")
            if service_elem is not None:
                service = service_elem.get("name")
                product = service_elem.get("product", "")
                ver = service_elem.get("version", "")
                if product or ver:
                    version = f"{product} {ver}".strip()
            
            # Determine risk
            if port_id in HIGH_RISK_PORTS:
                risk = HIGH_RISK_PORTS[port_id]
            elif port_id in MEDIUM_RISK_PORTS:
                risk = MEDIUM_RISK_PORTS[port_id]
            elif port_id in LOW_RISK_PORTS:
                risk = LOW_RISK_PORTS[port_id]
            else:
                risk = "info"
            
            result["open_ports"].append({
                "port": port_id,
                "protocol": protocol,
                "state": state,
                "service": service,
                "version": version,
                "product": product,
                "risk": risk,
            })
        
        for os_elem in host.findall(".//osmatch"):
            result["os_guess"] = os_elem.get("name")
            break
    
    return result


def scan_port(host: str, port: int, timeout: float = 1.5) -> Dict[str, Any]:
    """Scan a single port with service detection."""
    result = {
        "port": port,
        "protocol": "tcp",
        "state": "closed",
        "service": None,
        "version": None,
        "product": None,
        "risk": "info",
    }
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        connect_result = sock.connect_ex((host, port))
        
        if connect_result == 0:
            result["state"] = "open"
            
            # Service detection
            if port in COMMON_PORTS:
                result["service"] = COMMON_PORTS[port][0]
            
            # Try to grab banner
            try:
                sock.send(b"\r\n")
                sock.settimeout(0.5)
                banner = sock.recv(256).decode("utf-8", errors="ignore").strip()
                if banner:
                    result["version"] = banner[:150]
                    # Try to parse banner for service info
                    banner_lower = banner.lower()
                    if "ssh" in banner_lower:
                        result["service"] = "ssh"
                        result["product"] = banner.split("\n")[0][:100]
                    elif "http" in banner_lower:
                        result["service"] = "http"
                    elif "mysql" in banner_lower:
                        result["service"] = "mysql"
                    elif "redis" in banner_lower:
                        result["service"] = "redis"
                    elif "mongodb" in banner_lower:
                        result["service"] = "mongodb"
            except:
                pass
            
            # Check SSL/TLS
            if port in (443, 8443, 993, 995, 636, 3269):
                try:
                    context = ssl.create_default_context()
                    context.check_hostname = False
                    context.verify_mode = ssl.CERT_NONE
                    ssock = context.wrap_socket(sock, server_hostname=host)
                    result["service"] = "https" if port == 443 else result["service"] or "ssl"
                    ssock.close()
                except:
                    pass
            
            # Determine risk level
            if port in HIGH_RISK_PORTS:
                result["risk"] = HIGH_RISK_PORTS[port]
            elif port in MEDIUM_RISK_PORTS:
                result["risk"] = MEDIUM_RISK_PORTS[port]
            elif port in LOW_RISK_PORTS:
                result["risk"] = LOW_RISK_PORTS[port]
            else:
                result["risk"] = "medium"
        
        sock.close()
    except socket.timeout:
        result["state"] = "filtered"
    except Exception as e:
        result["state"] = "error"
        result["error"] = str(e)
    
    return result


def scan_with_nmap(host: str, ports: Optional[List[int]] = None, timeout: int = 60) -> Dict[str, Any]:
    """Scan using real nmap binary."""
    if not check_nmap_available():
        return None
    
    port_range = "1-1000" if ports is None else ",".join(str(p) for p in ports)
    
    try:
        # Run nmap with service version detection
        cmd = [
            "nmap",
            "-sT",  # TCP connect scan (works without root)
            "-sV",  # Service version detection
            "--version-intensity", "5",
            "-p", port_range,
            "--host-timeout", f"{timeout}s",
            "-oX", "-",  # XML output to stdout
            host
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout + 10
        )
        
        if result.returncode == 0 and result.stdout:
            return parse_nmap_output(result.stdout)
        else:
            return None
    except Exception as e:
        print(f"Nmap scan failed: {e}")
        return None


def scan_host(host: str, ports: Optional[List[int]] = None, timeout: float = 1.5, use_nmap: bool = True) -> Dict[str, Any]:
    """Scan a host with port scanning and service detection."""
    
    # Try nmap first if available and requested
    if use_nmap and check_nmap_available():
        nmap_result = scan_with_nmap(host, ports)
        if nmap_result is not None:
            # Calculate summary
            summary = {
                "total_scanned": len(nmap_result.get("open_ports", [])) if ports is None else len(ports),
                "open": len(nmap_result.get("open_ports", [])),
                "critical": sum(1 for p in nmap_result.get("open_ports", []) if p["risk"] == "critical"),
                "high": sum(1 for p in nmap_result.get("open_ports", []) if p["risk"] == "high"),
                "medium": sum(1 for p in nmap_result.get("open_ports", []) if p["risk"] == "medium"),
                "low": sum(1 for p in nmap_result.get("open_ports", []) if p["risk"] == "low"),
                "scanner": "nmap",
            }
            nmap_result["summary"] = summary
            return nmap_result
    
    # Fallback to socket scan
    if ports is None:
        ports = sorted(COMMON_PORTS.keys())
    
    result = {
        "host": host,
        "scan_time": datetime.utcnow().isoformat(),
        "open_ports": [],
        "closed_ports": [],
        "os_guess": None,
        "host_status": "unknown",
        "scanner": "socket",
        "summary": {
            "total_scanned": len(ports),
            "open": 0,
            "critical": 0,
            "high": 0,
            "medium": 0,
            "low": 0,
        },
    }
    
    # Parallel port scanning
    with ThreadPoolExecutor(max_workers=100) as executor:
        futures = {executor.submit(scan_port, host, port, timeout): port for port in ports}
        
        for future in futures:
            scan_result = future.result()
            if scan_result["state"] == "open":
                result["open_ports"].append(scan_result)
                result["summary"]["open"] += 1
                
                if scan_result["risk"] == "critical":
                    result["summary"]["critical"] += 1
                elif scan_result["risk"] == "high":
                    result["summary"]["high"] += 1
                elif scan_result["risk"] == "medium":
                    result["summary"]["medium"] += 1
                elif scan_result["risk"] == "low":
                    result["summary"]["low"] += 1
            else:
                result["closed_ports"].append(scan_result["port"])
    
    # Determine host status
    if result["summary"]["open"] > 0:
        result["host_status"] = "up"
    
    return result


def check_ssl(host: str, port: int = 443) -> Dict[str, Any]:
    """Check SSL/TLS configuration."""
    result = {
        "host": host,
        "port": port,
        "ssl_enabled": False,
        "certificate": None,
        "issues": [],
    }
    
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        with socket.create_connection((host, port), timeout=5) as sock:
            with context.wrap_socket(sock, server_hostname=host) as ssock:
                result["ssl_enabled"] = True
                cert = ssock.getpeercert()
                
                if cert:
                    subject = {}
                    for item in cert.get("subject", ()):
                        key, value = item[0]
                        subject[key] = value
                    
                    issuer = {}
                    for item in cert.get("issuer", ()):
                        key, value = item[0]
                        issuer[key] = value
                    
                    result["certificate"] = {
                        "subject": subject,
                        "issuer": issuer,
                        "version": cert.get("version"),
                        "serialNumber": str(cert.get("serialNumber", "")),
                        "notBefore": cert.get("notBefore"),
                        "notAfter": cert.get("notAfter"),
                    }
                    
                    # Check expiration
                    try:
                        not_after_str = cert.get("notAfter")
                        not_after = datetime.strptime(not_after_str, "%b %d %H:%M:%S %Y %Z")
                        days_left = (not_after - datetime.utcnow()).days
                        result["certificate"]["days_until_expiry"] = days_left
                        
                        if days_left < 0:
                            result["issues"].append(f"证书已过期 {-days_left} 天")
                        elif days_left < 30:
                            result["issues"].append(f"证书将在 {days_left} 天后过期")
                        elif days_left < 90:
                            result["issues"].append(f"证书将在 {days_left} 天后过期，建议提前续期")
                    except Exception:
                        pass
                    
                    # Check protocol version
                    protocol = ssock.version()
                    if protocol in ("TLSv1", "TLSv1.1"):
                        result["issues"].append(f"使用了不安全的 {protocol} 协议")
                    
                    # Check cipher
                    cipher = ssock.cipher()
                    if cipher and cipher[1] in ("RC4", "DES", "3DES", "MD5"):
                        result["issues"].append(f"使用了弱加密算法 {cipher[1]}")
    except ssl.SSLError as e:
        result["issues"].append(f"SSL 错误: {str(e)}")
    except socket.timeout:
        result["issues"].append("连接超时")
    except ConnectionRefusedError:
        result["issues"].append("连接被拒绝")
    except Exception as e:
        result["issues"].append(f"连接错误: {str(e)}")
    
    return result


def generate_compliance_findings(scan_result: Dict[str, Any], host: str) -> List[Dict[str, Any]]:
    """Generate compliance findings from scan results."""
    findings = []
    
    # Check for exposed critical ports
    critical_ports = [p for p in scan_result.get("open_ports", []) if p["risk"] == "critical"]
    if critical_ports:
        port_items = []
        for p in critical_ports:
            service_name = p.get('service') or 'unknown'
            version = p.get('version')
            if version:
                port_items.append(f"{p['port']}({service_name}/{version})")
            else:
                port_items.append(f"{p['port']}({service_name})")
        port_list = ", ".join(port_items)
        findings.append({
            "clause_id": "8.1.3.1",
            "clause_name": "边界访问控制",
            "severity": "critical",
            "judgment": "fail",
            "description": f"发现公网暴露的高危端口: {port_list}。数据库和管理服务不应直接暴露在公网。",
            "remediation": f"立即关闭以下端口的公网访问: {port_list}。使用安全组/防火墙限制为内网访问。",
            "evidence": {
                "tool": scan_result.get("scanner", "port_scan"),
                "target": host,
                "scanner": scan_result.get("scanner", "socket"),
                "critical_ports": [{"port": p["port"], "service": p["service"], "version": p.get("version")} for p in critical_ports],
            },
        })
    
    # Check for high risk ports
    high_ports = [p for p in scan_result.get("open_ports", []) if p["risk"] == "high"]
    if high_ports:
        port_list = ", ".join([f"{p['port']}({p['service'] or 'unknown'})" for p in high_ports])
        findings.append({
            "clause_id": "8.1.3.1",
            "clause_name": "边界访问控制",
            "severity": "high",
            "judgment": "fail",
            "description": f"发现公网暴露的高风险服务端口: {port_list}。需确认是否为业务必需端口。",
            "remediation": f"审查以下端口是否需要公网访问: {port_list}。非必要端口应关闭。",
            "evidence": {
                "tool": scan_result.get("scanner", "port_scan"),
                "target": host,
                "scanner": scan_result.get("scanner", "socket"),
                "high_ports": [{"port": p["port"], "service": p["service"], "version": p.get("version")} for p in high_ports],
            },
        })
    
    # Check for insecure protocols (Telnet)
    telnet = [p for p in scan_result.get("open_ports", []) if p["port"] == 23]
    if telnet:
        findings.append({
            "clause_id": "8.1.2.2",
            "clause_name": "通信传输加密",
            "severity": "critical",
            "judgment": "fail",
            "description": "Telnet(23端口)明文传输协议开放，违反等保2.0通信传输加密要求。",
            "remediation": "立即关闭Telnet服务，使用SSH替代，并配置防火墙规则。",
            "evidence": {
                "tool": scan_result.get("scanner", "port_scan"),
                "target": host,
                "scanner": scan_result.get("scanner", "socket"),
                "insecure_protocols": ["telnet"],
            },
        })
    
    # Check for HTTP without HTTPS
    http_only = (any(p["port"] == 80 for p in scan_result.get("open_ports", [])) and
                not any(p["port"] == 443 for p in scan_result.get("open_ports", [])))
    if http_only:
        findings.append({
            "clause_id": "8.1.2.2",
            "clause_name": "通信传输加密",
            "severity": "high",
            "judgment": "fail",
            "description": "HTTP(80)开放但HTTPS(443)未开放，存在明文传输风险。",
            "remediation": "配置SSL证书，启用HTTPS（TLS 1.2+），并设置HTTP到HTTPS的301重定向。",
            "evidence": {
                "tool": scan_result.get("scanner", "port_scan"),
                "target": host,
                "scanner": scan_result.get("scanner", "socket"),
                "http_only": True,
            },
        })
    
    # Check for SSH exposure
    ssh = [p for p in scan_result.get("open_ports", []) if p["port"] == 22]
    if ssh:
        ssh_info = ssh[0]
        version = ssh_info.get("version", "")
        description = f"SSH服务(22端口)对公网开放"
        if version:
            description += f"，版本: {version}"
        description += "。需确保使用密钥认证并禁用密码登录。"
        
        findings.append({
            "clause_id": "8.1.4.1",
            "clause_name": "身份鉴别",
            "severity": "high",
            "judgment": "partial",
            "description": description,
            "remediation": "1) 禁用密码登录，仅允许密钥认证；2) 限制SSH访问IP；3) 修改默认端口；4) 启用fail2ban防暴力破解；5) 配置登录失败锁定策略。",
            "evidence": {
                "tool": scan_result.get("scanner", "port_scan"),
                "target": host,
                "scanner": scan_result.get("scanner", "socket"),
                "ssh_exposed": True,
                "ssh_version": version,
            },
        })
    
    # Check for database exposure
    db_ports = [p for p in scan_result.get("open_ports", []) 
                if p["port"] in (3306, 5432, 1433, 1521, 6379, 27017)]
    if db_ports:
        db_list = ", ".join([f"{p['port']}({p['service']})" for p in db_ports])
        findings.append({
            "clause_id": "8.1.4.2",
            "clause_name": "访问控制",
            "severity": "critical",
            "judgment": "fail",
            "description": f"数据库端口直接暴露在公网: {db_list}。数据库必须仅在内部网络或通过VPN访问。",
            "remediation": f"1) 修改防火墙规则，仅允许应用服务器访问; 2) 绑定到内网IP (127.0.0.1); 3) 使用跳板机或VPN; 4) 启用数据库认证和加密连接。",
            "evidence": {
                "tool": scan_result.get("scanner", "port_scan"),
                "target": host,
                "scanner": scan_result.get("scanner", "socket"),
                "database_ports": [{"port": p["port"], "service": p["service"]} for p in db_ports],
            },
        })
    
    # If no critical issues found, add a passing finding
    if not findings:
        open_count = len(scan_result.get("open_ports", []))
        findings.append({
            "clause_id": "8.1.3.1",
            "clause_name": "边界访问控制",
            "severity": "info",
            "judgment": "pass",
            "description": f"未发现高危端口暴露，边界访问控制基本符合要求（共扫描 {open_count} 个开放端口）。",
            "remediation": None,
            "evidence": {
                "tool": scan_result.get("scanner", "port_scan"),
                "target": host,
                "scanner": scan_result.get("scanner", "socket"),
                "open_ports_count": open_count,
            },
        })
    
    return findings


# Export scanner info
def get_scanner_info() -> Dict[str, Any]:
    """Get information about available scanners."""
    return {
        "nmap_available": check_nmap_available(),
        "active_scanner": "nmap" if check_nmap_available() else "socket",
    }