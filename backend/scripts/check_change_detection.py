"""Small contract check for port normalization and comparison."""

from app.services.change_detection import detect_port_changes, normalize_ports, port_scope


def main():
    previous = [{"port": "22", "service": "ssh"}, {"port": 80, "service": "http"}]
    current = [{"port": 22, "service": "openssh"}, {"port": 443, "service": "https"}]
    changes = detect_port_changes(previous, current)
    assert [item["port"] for item in changes["added_ports"]] == [443]
    assert [item["port"] for item in changes["removed_ports"]] == [80]
    assert [item["port"] for item in changes["service_changes"]] == [22]
    assert len(normalize_ports([22, {"port": "22"}])) == 1
    assert port_scope("scan_ports", {"port_range": "30-3000"}, {}) != port_scope(
        "scan_ports", {"port_range": "high-risk"}, {}
    )
    print("change detection contract ok")


if __name__ == "__main__":
    main()
