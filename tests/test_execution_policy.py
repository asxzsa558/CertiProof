import asyncio

from app.services.execution_policy import validate_execution_parameters


def test_execution_policy_normalizes_safe_port_and_url_inputs():
    async def run():
        params = await validate_execution_parameters(
            "scan_ports",
            {"target": "example.com", "port_range": "30-3000", "rate": "2000"},
            project_id=None,
            db=None,
        )
        assert params["port_range"] == "30-3000"
        assert params["rate"] == 2000

        params = await validate_execution_parameters(
            "sqlmap_scan",
            {"url": "https://example.com/search?q=a&lang=zh", "level": 2, "risk": 1},
            project_id=None,
            db=None,
        )
        assert params["url"].startswith("https://example.com/")

    asyncio.run(run())


def test_execution_policy_rejects_shell_like_targets_and_invalid_ports():
    async def run():
        for parameters in (
            {"target": "example.com;id"},
            {"target": "example.com", "port_range": "1-70000"},
            {"target": "example.com", "port": 0},
        ):
            try:
                await validate_execution_parameters("scan_ports", parameters, project_id=None, db=None)
            except ValueError:
                continue
            raise AssertionError(f"unsafe parameters were accepted: {parameters}")

    asyncio.run(run())
