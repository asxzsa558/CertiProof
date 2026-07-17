"""Private Docker-network target used by CertiProof end-to-end acceptance tests."""

from __future__ import annotations

import asyncio
import ssl
import subprocess
from pathlib import Path

import asyncssh


USERNAME = "audit"
PASSWORD = "CertiProof-E2E-2026!"
HOST_KEY = Path("/tmp/certiproof_e2e_host_key")
CERT = Path("/tmp/certiproof_e2e_cert.pem")
CERT_KEY = Path("/tmp/certiproof_e2e_cert_key.pem")


class TestSSHServer(asyncssh.SSHServer):
    def begin_auth(self, username: str) -> bool:
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return username == USERNAME and password == PASSWORD


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
        path = parts[1] if len(parts) > 1 else "/"
        while True:
            line = await reader.readline()
            if line in {b"\r\n", b"\n", b""}:
                break
        if path in {"/", "/health", "/security.txt"}:
            status, body = "200 OK", b"CertiProof controlled acceptance target\n"
        else:
            status, body = "404 Not Found", b"Not Found\n"
        response = (
            f"HTTP/1.1 {status}\r\n"
            "Server: CertiProof-E2E/1.0\r\n"
            "Content-Type: text/plain; charset=utf-8\r\n"
            "X-Content-Type-Options: nosniff\r\n"
            "X-Frame-Options: DENY\r\n"
            "Content-Security-Policy: default-src 'none'\r\n"
            f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
        ).encode("ascii") + body
        writer.write(response)
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


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
    await asyncssh.create_server(
        TestSSHServer,
        "0.0.0.0",
        22,
        server_host_keys=[str(HOST_KEY)],
        process_factory=handle_ssh_process,
    )
    await asyncio.start_server(handle_http, "0.0.0.0", 80)
    await asyncio.start_server(handle_http, "0.0.0.0", 443, ssl=tls_context)
    print("CertiProof E2E target ready on 22/80/443", flush=True)
    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
