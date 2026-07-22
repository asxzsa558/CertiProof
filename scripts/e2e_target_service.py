"""Private Docker-network target used by CertiProof end-to-end acceptance tests."""

from __future__ import annotations

import asyncio
import json
import ssl
import struct
import subprocess
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import asyncssh


USERNAME = "audit"
PASSWORD = "CertiProof-E2E-2026!"
WEAK_USERNAME = "root"
WEAK_PASSWORD = "P@ssw0rd"
HOST_KEY = Path("/tmp/certiproof_e2e_host_key")
CERT = Path("/tmp/certiproof_e2e_cert.pem")
CERT_KEY = Path("/tmp/certiproof_e2e_cert_key.pem")

LAB_SERVICES = {
    "ssh": 22,
    "http": 80,
    "https": 443,
    "snmp": 161,
    "oracle": 1521,
    "mysql": 3306,
    "redis": 6379,
    "memcached": 11211,
    "mongodb": 27017,
}


class TestSSHServer(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return (username, password) in {
            (USERNAME, PASSWORD),
            (WEAK_USERNAME, WEAK_PASSWORD),
        }


COMMAND_OUTPUTS = {
    "uname -a": "Linux certiproof-e2e-target 6.1.0 x86_64 GNU/Linux\n",
    "uname -s 2>/dev/null || ver 2>/dev/null || echo unknown": "Linux\n",
    "cat /etc/os-release": 'NAME="Debian GNU/Linux"\nVERSION="12 (bookworm)"\nID=debian\n',
    "id": "uid=1000(audit) gid=1000(audit) groups=1000(audit),27(sudo)\n",
}


async def handle_ssh_process(process: asyncssh.SSHServerProcess) -> None:
    command = (process.command or "").strip()
    output = COMMAND_OUTPUTS.get(command)
    if output is None:
        if "PASS_MAX_DAYS" in command:
            output = "90\n"
        elif "PASS_MIN_DAYS" in command:
            output = "1\n"
        elif "PASS_MIN_LEN" in command:
            output = "12\n"
        elif "PASS_WARN_AGE" in command:
            output = "7\n"
        elif "ENCRYPT_METHOD" in command:
            output = "YESCRYPT\n"
        elif "pam_pwquality" in command or "pam_cracklib" in command:
            output = "password requisite pam_pwquality.so retry=3\n"
        elif "/etc/shadow" in command and "awk" in command:
            output = "NONE\n"
        elif "PermitRootLogin" in command:
            output = "PermitRootLogin no\n"
        elif "PasswordAuthentication" in command:
            output = "PasswordAuthentication yes\n"
        elif "MaxAuthTries" in command:
            output = "MaxAuthTries 3\n"
        elif "^Protocol" in command:
            output = "2\n"
        elif "LoginGraceTime" in command:
            output = "LoginGraceTime 60\n"
        elif "is-active auditd" in command or "is-active rsyslog" in command:
            output = "active\n"
        elif "auditctl -l" in command:
            output = "4\n"
        elif "rsyslog.conf" in command:
            output = "NOT_FOUND\n"
        elif "/var/log/" in command:
            output = "600 /var/log/auth.log\n"
        elif "ss -tlnp" in command and "grep -E" in command:
            output = "NONE\n"
        elif "ss -tlnp" in command or "netstat -tlnp" in command:
            output = "LISTEN 0 128 0.0.0.0:22\nLISTEN 0 128 0.0.0.0:80\nLISTEN 0 128 0.0.0.0:443\n"
        elif "list-units" in command:
            output = "NONE\n"
        elif "find / -perm" in command:
            output = "/usr/bin/passwd\n"
        elif "find /etc" in command:
            output = "NONE\n"
        elif "/etc/shadow" in command:
            output = "600 /etc/shadow\n"
        elif "/etc/passwd" in command:
            output = "644 /etc/passwd\n"
        elif "getenforce" in command:
            output = "NOT_INSTALLED\n"
        elif "aa-status" in command:
            output = "apparmor module is loaded\n12 profiles are loaded\n"
        else:
            output = "check completed\n"
    process.stdout.write(output)
    process.exit(0)


async def handle_http(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request_line = (await reader.readline()).decode("latin-1", errors="replace").strip()
        parts = request_line.split()
        requested = parts[1] if len(parts) > 1 else "/"
        parsed = urlsplit(requested)
        path = parsed.path
        while True:
            line = await reader.readline()
            if line in {b"\r\n", b"\n", b""}:
                break
        content_type = "text/plain; charset=utf-8"
        if path == "/health":
            status, body = "200 OK", b"healthy\n"
        elif path == "/manifest":
            content_type = "application/json; charset=utf-8"
            body = json.dumps({
                "name": "CertiProof isolated acceptance target",
                "services": LAB_SERVICES,
                "purpose": "tool-chain validation only",
            }).encode("utf-8")
            status = "200 OK"
        elif path in {"/", "/admin", "/api", "/login", "/backup", "/security.txt", "/robots.txt"}:
            status, body = "200 OK", f"CertiProof controlled path: {path}\n".encode()
        elif path == "/.git/config":
            status, body = "200 OK", b"[core]\nrepositoryformatversion = 0\n"
        elif path == "/.env":
            status, body = "200 OK", b"APP_ENV=acceptance\nAPP_SECRET=not-a-real-secret\n"
        elif path == "/server-status":
            status, body = "200 OK", b"Apache Server Status for certiproof-e2e-target\n"
        elif path == "/item":
            item_id = parse_qs(parsed.query).get("id", [""])[0]
            lowered = item_id.lower()
            if "'" in item_id or '"' in item_id:
                status, body = "500 Internal Server Error", b"SQL syntax error near supplied identifier\n"
            elif any(marker in lowered for marker in ("1=2", "2=3", "false")):
                status, body = "200 OK", b"No matching item\n"
            else:
                status, body = "200 OK", b"Item found: acceptance fixture\n"
        else:
            status, body = "404 Not Found", b"Not Found\n"
        response = (
            f"HTTP/1.1 {status}\r\n"
            "Server: CertiProof-E2E-Vulnerable/1.0\r\n"
            f"Content-Type: {content_type}\r\n"
            "X-CertiProof-Lab: intentionally-vulnerable\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        ).encode("ascii") + body
        writer.write(response)
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


async def _close_writer(writer: asyncio.StreamWriter) -> None:
    writer.close()
    await writer.wait_closed()


async def handle_redis(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        request = await asyncio.wait_for(reader.read(4096), timeout=3)
        payload = (
            b"# Server\r\nredis_version:7.2.0\r\n"
            b"redis_mode:standalone\r\nos:Linux acceptance\r\n"
        )
        if b"INFO" in request.upper():
            writer.write(f"${len(payload)}\r\n".encode() + payload + b"\r\n")
        else:
            writer.write(b"+PONG\r\n")
        await writer.drain()
    finally:
        await _close_writer(writer)


async def handle_memcached(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        await asyncio.wait_for(reader.read(4096), timeout=3)
        writer.write(b"STAT version 1.6.21\r\nSTAT curr_connections 1\r\nEND\r\n")
        await writer.drain()
    finally:
        await _close_writer(writer)


async def handle_mongodb(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        await asyncio.wait_for(reader.read(4096), timeout=3)
        writer.write(b'{"version":"7.0.0","ok":1,"fixture":"certiproof"}\n')
        await writer.drain()
    finally:
        await _close_writer(writer)


async def handle_oracle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        await asyncio.wait_for(reader.read(1024), timeout=3)
        writer.write(b"\x00\x20\x00\x00\x02\x00\x00\x00Oracle TNS Listener acceptance")
        await writer.drain()
    finally:
        await _close_writer(writer)


def mysql_packet(payload: bytes, sequence: int) -> bytes:
    length = len(payload)
    return length.to_bytes(3, "little") + bytes([sequence]) + payload


async def read_mysql_packet(reader: asyncio.StreamReader) -> bytes:
    header = await asyncio.wait_for(reader.readexactly(4), timeout=5)
    length = int.from_bytes(header[:3], "little")
    return await asyncio.wait_for(reader.readexactly(length), timeout=5)


async def handle_mysql(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Minimal MySQL 4.1 responder for the empty-password acceptance probe."""
    salt = b"certiproof-lab-salt!!"
    capabilities = 0x0008A201
    handshake = (
        b"\x0a8.0.36-CertiProof-Lab\x00"
        + struct.pack("<I", 1)
        + salt[:8]
        + b"\x00"
        + struct.pack("<H", capabilities & 0xFFFF)
        + b"\x21\x02\x00"
        + struct.pack("<H", capabilities >> 16)
        + b"\x15"
        + b"\x00" * 10
        + salt[8:20]
        + b"\x00mysql_native_password\x00"
    )
    try:
        writer.write(mysql_packet(handshake, 0))
        await writer.drain()
        await read_mysql_packet(reader)
        writer.write(mysql_packet(b"\x00\x00\x00\x02\x00\x00\x00", 2))
        await writer.drain()

        command = await read_mysql_packet(reader)
        if command[:1] != b"\x03":
            return
        column = (
            b"\x03def\x00\x00\x00\x09VERSION()\x00\x0c"
            b"\x21\x00\x20\x00\x00\x00\xfd\x00\x00\x00\x00\x00"
        )
        writer.write(mysql_packet(b"\x01", 1))
        writer.write(mysql_packet(column, 2))
        writer.write(mysql_packet(b"\xfe\x00\x00\x02\x00", 3))
        value = b"8.0.36-CertiProof-Lab"
        writer.write(mysql_packet(bytes([len(value)]) + value, 4))
        writer.write(mysql_packet(b"\xfe\x00\x00\x02\x00", 5))
        await writer.drain()
    except (asyncio.IncompleteReadError, ConnectionError):
        pass
    finally:
        await _close_writer(writer)


def ensure_keys() -> ssl.SSLContext:
    if not HOST_KEY.exists():
        HOST_KEY.write_bytes(asyncssh.generate_private_key("ssh-rsa").export_private_key())
    if not CERT.exists() or not CERT_KEY.exists():
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(CERT_KEY), "-out", str(CERT), "-days", "2",
            "-subj", "/CN=certiproof-e2e-target",
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(CERT, CERT_KEY)
    return context


async def main() -> None:
    tls_context = ensure_keys()
    snmpd = await asyncio.create_subprocess_exec(
        "snmpd", "-f", "-Lo", "-C", "-c", "/app/snmpd.conf",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    await asyncssh.create_server(
        TestSSHServer,
        "0.0.0.0",
        22,
        server_host_keys=[str(HOST_KEY)],
        process_factory=handle_ssh_process,
    )
    await asyncio.start_server(handle_http, "0.0.0.0", 80)
    await asyncio.start_server(handle_http, "0.0.0.0", 443, ssl=tls_context)
    await asyncio.start_server(handle_oracle, "0.0.0.0", 1521)
    await asyncio.start_server(handle_mysql, "0.0.0.0", 3306)
    await asyncio.start_server(handle_redis, "0.0.0.0", 6379)
    await asyncio.start_server(handle_memcached, "0.0.0.0", 11211)
    await asyncio.start_server(handle_mongodb, "0.0.0.0", 27017)
    await asyncio.sleep(0.2)
    if snmpd.returncode is not None:
        raise RuntimeError("snmpd failed to start")
    print(f"CertiProof E2E target ready: {LAB_SERVICES}", flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        snmpd.terminate()
        await snmpd.wait()


if __name__ == "__main__":
    asyncio.run(main())
