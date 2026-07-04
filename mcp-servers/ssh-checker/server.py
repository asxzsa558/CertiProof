"""
SSH Checker MCP Server - Linux 白盒配置核查
通过 SSH 远程登录执行配置检查命令，覆盖等保安全计算环境核心要求
"""

import asyncio
import time
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import asyncssh

app = FastAPI(title="SSH Checker MCP Server", version="1.0.0")

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


# ============== 检查项定义 ==============

# 密码策略检查命令
PASSWORD_POLICY_CHECKS = {
    "pass_max_days": {
        "cmd": "grep '^PASS_MAX_DAYS' /etc/login.defs 2>/dev/null || echo 'NOT_FOUND'",
        "description": "密码最大使用天数",
        "compliant": lambda v: v and v.isdigit() and int(v) <= 90,
        "requirement": "PASS_MAX_DAYS <= 90",
    },
    "pass_min_days": {
        "cmd": "grep '^PASS_MIN_DAYS' /etc/login.defs 2>/dev/null || echo 'NOT_FOUND'",
        "description": "密码最小修改间隔",
        "compliant": lambda v: v and v.isdigit() and int(v) >= 1,
        "requirement": "PASS_MIN_DAYS >= 1",
    },
    "pass_min_len": {
        "cmd": "grep '^PASS_MIN_LEN' /etc/login.defs 2>/dev/null || echo 'NOT_FOUND'",
        "description": "密码最小长度",
        "compliant": lambda v: v and v.isdigit() and int(v) >= 8,
        "requirement": "PASS_MIN_LEN >= 8",
    },
    "pass_warn_age": {
        "cmd": "grep '^PASS_WARN_AGE' /etc/login.defs 2>/dev/null || echo 'NOT_FOUND'",
        "description": "密码过期警告天数",
        "compliant": lambda v: v and v.isdigit() and int(v) >= 7,
        "requirement": "PASS_WARN_AGE >= 7",
    },
    "encrypt_method": {
        "cmd": "grep '^ENCRYPT_METHOD' /etc/login.defs 2>/dev/null || echo 'NOT_FOUND'",
        "description": "密码加密算法",
        "compliant": lambda v: v and v.upper() in ("SHA512", "YESCRYPT"),
        "requirement": "ENCRYPT_METHOD = SHA512 或 YESCRYPT",
    },
    "pam_pwquality": {
        "cmd": "cat /etc/pam.d/common-password 2>/dev/null | grep -E 'pam_pwquality|pam_cracklib' || echo 'NOT_FOUND'",
        "description": "PAM 密码质量模块",
        "compliant": lambda v: v and "NOT_FOUND" not in v,
        "requirement": "配置 pam_pwquality 或 pam_cracklib",
    },
    "empty_passwords": {
        "cmd": "awk -F: '($2 == \"\" || $2 == \"!\") {print $1}' /etc/shadow 2>/dev/null || echo 'NONE'",
        "description": "空口令账户",
        "compliant": lambda v: v and v.strip() in ("NONE", ""),
        "requirement": "无空口令账户",
    },
}

# SSH 配置检查命令
SSH_CONFIG_CHECKS = {
    "permit_root_login": {
        "cmd": "grep '^PermitRootLogin' /etc/ssh/sshd_config 2>/dev/null || echo 'NOT_FOUND'",
        "description": "root 远程登录",
        "compliant": lambda v: v and v.strip().lower() in ("permitrootlogin no", "permitrootlogin prohibit-password"),
        "requirement": "PermitRootLogin no 或 prohibit-password",
    },
    "password_authentication": {
        "cmd": "grep '^PasswordAuthentication' /etc/ssh/sshd_config 2>/dev/null || echo 'NOT_FOUND'",
        "description": "密码认证",
        "compliant": lambda v: v and v.strip().lower() == "passwordauthentication no",
        "requirement": "PasswordAuthentication no（推荐密钥认证）",
    },
    "max_auth_tries": {
        "cmd": "grep '^MaxAuthTries' /etc/ssh/sshd_config 2>/dev/null || echo 'NOT_FOUND'",
        "description": "最大认证尝试次数",
        "compliant": lambda v: v and v.replace("maxauthtries", "").strip().isdigit() and int(v.replace("maxauthtries", "").strip()) <= 5,
        "requirement": "MaxAuthTries <= 5",
    },
    "protocol_version": {
        "cmd": "grep '^Protocol' /etc/ssh/sshd_config 2>/dev/null || echo '2'",
        "description": "SSH 协议版本",
        "compliant": lambda v: v and "2" in v,
        "requirement": "Protocol 2",
    },
    "login_grace_time": {
        "cmd": "grep '^LoginGraceTime' /etc/ssh/sshd_config 2>/dev/null || echo 'NOT_FOUND'",
        "description": "登录宽限时间",
        "compliant": lambda v: v and v.replace("logingracetime", "").strip().isdigit() and int(v.replace("logingracetime", "").strip()) <= 60,
        "requirement": "LoginGraceTime <= 60",
    },
}

# 审计配置检查命令
AUDIT_CONFIG_CHECKS = {
    "auditd_status": {
        "cmd": "systemctl is-active auditd 2>/dev/null || echo 'inactive'",
        "description": "auditd 服务状态",
        "compliant": lambda v: v and v.strip() == "active",
        "requirement": "auditd 服务运行中",
    },
    "audit_rules": {
        "cmd": "auditctl -l 2>/dev/null | wc -l || echo '0'",
        "description": "审计规则数量",
        "compliant": lambda v: v and v.strip().isdigit() and int(v.strip()) > 0,
        "requirement": "至少配置 1 条审计规则",
    },
    "rsyslog_status": {
        "cmd": "systemctl is-active rsyslog 2>/dev/null || echo 'inactive'",
        "description": "rsyslog 服务状态",
        "compliant": lambda v: v and v.strip() == "active",
        "requirement": "rsyslog 服务运行中",
    },
    "remote_logging": {
        "cmd": "grep -r '^*.*[^I][^I]*@' /etc/rsyslog.conf /etc/rsyslog.d/ 2>/dev/null || echo 'NOT_FOUND'",
        "description": "远程日志配置",
        "compliant": lambda v: v and "NOT_FOUND" not in v,
        "requirement": "配置远程日志服务器",
    },
    "log_permissions": {
        "cmd": "ls -la /var/log/ 2>/dev/null | grep -E 'auth|secure|messages' | head -5",
        "description": "日志文件权限",
        "compliant": lambda v: v and "600" in v or "640" in v,
        "requirement": "日志文件权限 <= 640",
    },
}

# 服务/端口检查命令
SERVICE_PORT_CHECKS = {
    "listening_ports": {
        "cmd": "ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null",
        "description": "监听端口列表",
        "compliant": None,  # 信息收集，不做合规判定
        "requirement": "审查监听端口",
    },
    "danger_ports": {
        "cmd": "ss -tlnp 2>/dev/null | grep -E ':21 |:23 |:513 |:514 |:111 |:2049 ' || echo 'NONE'",
        "description": "高危端口（telnet/ftp/rlogin/rsh/nfs）",
        "compliant": lambda v: v and v.strip() == "NONE",
        "requirement": "关闭 telnet/ftp/rlogin/rsh 等不安全服务",
    },
    "unnecessary_services": {
        "cmd": "systemctl list-units --type=service --state=running 2>/dev/null | grep -E 'telnet|ftp|rsh|rlogin' || echo 'NONE'",
        "description": "不必要服务",
        "compliant": lambda v: v and v.strip() == "NONE",
        "requirement": "关闭不必要服务",
    },
}

# 文件权限检查命令
FILE_PERMISSION_CHECKS = {
    "suid_sgid": {
        "cmd": "find / -perm -4000 -o -perm -2000 2>/dev/null | head -20 || echo 'NONE'",
        "description": "SUID/SGID 文件",
        "compliant": None,  # 信息收集
        "requirement": "审查 SUID/SGID 文件",
    },
    "world_writable": {
        "cmd": "find /etc -type f -perm -o+w 2>/dev/null | head -10 || echo 'NONE'",
        "description": "关键目录全局可写文件",
        "compliant": lambda v: v and v.strip() == "NONE",
        "requirement": "关键目录无全局可写文件",
    },
    "shadow_permissions": {
        "cmd": "ls -la /etc/shadow 2>/dev/null || echo 'NOT_FOUND'",
        "description": "/etc/shadow 权限",
        "compliant": lambda v: v and ("600" in v or "640" in v),
        "requirement": "/etc/shadow 权限 <= 640",
    },
    "passwd_permissions": {
        "cmd": "ls -la /etc/passwd 2>/dev/null || echo 'NOT_FOUND'",
        "description": "/etc/passwd 权限",
        "compliant": lambda v: v and "644" in v,
        "requirement": "/etc/passwd 权限 = 644",
    },
}

# SELinux/AppArmor 检查
MAC_CHECKS = {
    "selinux_status": {
        "cmd": "getenforce 2>/dev/null || echo 'NOT_INSTALLED'",
        "description": "SELinux 状态",
        "compliant": lambda v: v and v.strip() in ("Enforcing", "Permissive"),
        "requirement": "SELinux Enforcing 或 Permissive",
    },
    "apparmor_status": {
        "cmd": "aa-status 2>/dev/null | head -5 || echo 'NOT_INSTALLED'",
        "description": "AppArmor 状态",
        "compliant": lambda v: v and "NOT_INSTALLED" not in v,
        "requirement": "AppArmor 已安装并启用",
    },
}


# ============== SSH 执行函数 ==============

async def ssh_execute(
    host: str,
    username: str,
    password: Optional[str] = None,
    key_file: Optional[str] = None,
    port: int = 22,
    commands: Dict[str, Dict] = None,
    timeout: int = 30,
) -> Dict[str, Any]:
    """通过 SSH 执行远程命令"""
    
    if commands is None:
        commands = {}
    
    results = {}
    connect_kwargs = {
        "host": host,
        "port": port,
        "username": username,
    }
    
    if password:
        connect_kwargs["password"] = password
    elif key_file:
        connect_kwargs["client_keys"] = [key_file]
    else:
        raise ValueError("必须提供 password 或 key_file")
    
    try:
        async with asyncssh.connect(
            **connect_kwargs,
            known_hosts=None,
            connect_timeout=10,
        ) as conn:
            for check_name, check_config in commands.items():
                cmd = check_config.get("cmd", "")
                try:
                    result = await asyncio.wait_for(
                        conn.run(cmd, check=False),
                        timeout=timeout,
                    )
                    output = result.stdout.strip() if result.stdout else ""
                    if not output and result.stderr:
                        output = result.stderr.strip()
                    
                    # 合规判定
                    compliant_func = check_config.get("compliant")
                    if compliant_func:
                        is_compliant = compliant_func(output)
                    else:
                        is_compliant = None
                    
                    results[check_name] = {
                        "description": check_config.get("description", ""),
                        "requirement": check_config.get("requirement", ""),
                        "output": output,
                        "compliant": is_compliant,
                        "status": "success",
                    }
                except asyncio.TimeoutError:
                    results[check_name] = {
                        "description": check_config.get("description", ""),
                        "output": "Command timeout",
                        "status": "timeout",
                    }
                except Exception as e:
                    results[check_name] = {
                        "description": check_config.get("description", ""),
                        "output": str(e),
                        "status": "error",
                    }
    
    except asyncssh.Error as e:
        raise ValueError(f"SSH connection error: {e}")
    except Exception as e:
        raise ValueError(f"Connection error: {e}")
    
    return results


# ============== 工具函数 ==============

async def linux_baseline(params: Dict[str, Any]) -> Dict[str, Any]:
    """安全基线全量检查，先通过 SSH 自动识别操作系统。"""
    host = params.get("target")
    if not host:
        raise ValueError("Missing required parameter: target")
    
    username = params.get("username", "root")
    password = params.get("password")
    key_file = params.get("key_file")
    port = params.get("port", 22)
    check_categories = params.get("categories", ["password", "ssh", "audit", "service", "file_perm", "mac"])
    start_time = time.time()
    os_probe = await ssh_execute(
        host=host,
        username=username,
        password=password,
        key_file=key_file,
        port=port,
        commands={
            "os_detect": {
                "cmd": "uname -s 2>/dev/null || ver 2>/dev/null || echo unknown",
                "description": "操作系统识别",
                "requirement": "自动识别目标操作系统",
            }
        },
        timeout=10,
    )
    os_output = (os_probe.get("os_detect", {}).get("output") or "").lower()
    if "linux" in os_output:
        os_type = "linux"
    elif "windows" in os_output or "microsoft" in os_output:
        os_type = "windows"
    elif "darwin" in os_output:
        os_type = "macos"
    else:
        os_type = "unknown"

    if os_type != "linux":
        duration_ms = int((time.time() - start_time) * 1000)
        return {
            "tool": "linux_baseline",
            "version": "1.0",
            "status": "success",
            "data": {
                "target": host,
                "os_type": os_type,
                "supported": False,
                "skipped": True,
                "skip_reason": "当前基线规则仅支持 Linux SSH 主机",
                "results": os_probe,
                "summary": {
                    "total_checks": 0,
                    "compliant": 0,
                    "non_compliant": 0,
                    "info_only": 0,
                    "compliance_rate": 0,
                },
            },
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
            },
        }

    # 合并所有检查项
    all_checks = {}
    if "password" in check_categories:
        all_checks.update(PASSWORD_POLICY_CHECKS)
    if "ssh" in check_categories:
        all_checks.update(SSH_CONFIG_CHECKS)
    if "audit" in check_categories:
        all_checks.update(AUDIT_CONFIG_CHECKS)
    if "service" in check_categories:
        all_checks.update(SERVICE_PORT_CHECKS)
    if "file_perm" in check_categories:
        all_checks.update(FILE_PERMISSION_CHECKS)
    if "mac" in check_categories:
        all_checks.update(MAC_CHECKS)
    
    results = await ssh_execute(
        host=host,
        username=username,
        password=password,
        key_file=key_file,
        port=port,
        commands=all_checks,
    )
    
    duration_ms = int((time.time() - start_time) * 1000)
    
    # 统计合规情况
    total = len(results)
    compliant = sum(1 for r in results.values() if r.get("compliant") is True)
    non_compliant = sum(1 for r in results.values() if r.get("compliant") is False)
    info_only = sum(1 for r in results.values() if r.get("compliant") is None)
    
    return {
        "tool": "linux_baseline",
        "version": "1.0",
        "status": "success",
        "data": {
            "target": host,
            "os_type": os_type,
            "supported": True,
            "skipped": False,
            "categories": check_categories,
            "results": results,
            "summary": {
                "total_checks": total,
                "compliant": compliant,
                "non_compliant": non_compliant,
                "info_only": info_only,
                "compliance_rate": round(compliant / max(total - info_only, 1) * 100, 1),
            },
        },
        "metadata": {
            "duration_ms": duration_ms,
            "scan_time": datetime.utcnow().isoformat(),
        },
    }


async def password_policy_check(params: Dict[str, Any]) -> Dict[str, Any]:
    """密码策略检查"""
    params["categories"] = ["password"]
    result = await linux_baseline(params)
    result["tool"] = "password_policy_check"
    return result


async def ssh_config_check(params: Dict[str, Any]) -> Dict[str, Any]:
    """SSH 配置检查"""
    params["categories"] = ["ssh"]
    result = await linux_baseline(params)
    result["tool"] = "ssh_config_check"
    return result


async def audit_config_check(params: Dict[str, Any]) -> Dict[str, Any]:
    """审计配置检查"""
    params["categories"] = ["audit"]
    result = await linux_baseline(params)
    result["tool"] = "audit_config_check"
    return result


async def service_port_check(params: Dict[str, Any]) -> Dict[str, Any]:
    """服务端口检查"""
    params["categories"] = ["service"]
    result = await linux_baseline(params)
    result["tool"] = "service_port_check"
    return result


async def file_permission_check(params: Dict[str, Any]) -> Dict[str, Any]:
    """文件权限检查"""
    params["categories"] = ["file_perm"]
    result = await linux_baseline(params)
    result["tool"] = "file_permission_check"
    return result


async def mac_check(params: Dict[str, Any]) -> Dict[str, Any]:
    """强制访问控制检查（SELinux/AppArmor）"""
    params["categories"] = ["mac"]
    result = await linux_baseline(params)
    result["tool"] = "mac_check"
    return result


# ============== API 端点 ==============

@app.get("/")
async def root():
    return {
        "name": "SSH Checker MCP Server",
        "version": "1.0.0",
        "tools": [
            "linux_baseline",
            "password_policy_check",
            "ssh_config_check",
            "audit_config_check",
            "service_port_check",
            "file_permission_check",
            "mac_check",
        ],
    }


@app.get("/health")
async def health():
    try:
        import asyncssh
        ssh_available = True
    except ImportError:
        ssh_available = False
    
    return {
        "status": "healthy" if ssh_available else "degraded",
        "tools": [
            "linux_baseline",
            "password_policy_check",
            "ssh_config_check",
            "audit_config_check",
            "service_port_check",
            "file_permission_check",
            "mac_check",
        ],
        "ssh_available": ssh_available,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """执行工具（同步模式）"""
    tool_name = request.tool
    params = request.params
    
    tool_map = {
        "linux_baseline": linux_baseline,
        "password_policy_check": password_policy_check,
        "ssh_config_check": ssh_config_check,
        "audit_config_check": audit_config_check,
        "service_port_check": service_port_check,
        "file_permission_check": file_permission_check,
        "mac_check": mac_check,
    }
    
    if tool_name not in tool_map:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {tool_name}")
    
    try:
        return await tool_map[tool_name](params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8016)
