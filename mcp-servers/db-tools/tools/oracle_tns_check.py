#!/usr/bin/env python3
import socket
import sys
import json
from typing import Dict, Any

def check_oracle_tns(host: str, port: int = 1521, timeout: int = 5) -> Dict[str, Any]:
    result = {"host": host, "port": port, "status": "unknown", "version": None, "service_name": None, "error": None}
    
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((host, port))
        
        tns_connect = bytes([0x00, 0x58, 0x00, 0x00, 0x00, 0x00, 0x01, 0x36, 0x01, 0x2b] + [0x00] * 78)
        sock.send(tns_connect)
        
        response = sock.recv(1024)
        sock.close()
        
        if len(response) > 0:
            result["status"] = "open"
            if len(response) > 10:
                result["version"] = "Oracle TNS Listener detected"
    except socket.timeout:
        result["status"] = "timeout"
        result["error"] = "Connection timeout"
    except socket.error as e:
        result["status"] = "closed"
        result["error"] = str(e)
    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)
    
    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: oracle_tns_check <host> [port]")
        sys.exit(1)
    
    host = sys.argv[1]
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 1521
    result = check_oracle_tns(host, port)
    print(json.dumps(result, indent=2))
