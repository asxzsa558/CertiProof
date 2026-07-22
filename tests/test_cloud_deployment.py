from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_all_production_builds_have_publishable_images():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    for name, service in services.items():
        if "build" in service and name != "e2e-target":
            assert service.get("image"), f"{name} has no published image name"


def test_cpu_and_gpu_packages_select_distinct_inference_policies():
    cpu = (ROOT / "deploy/cloud/.env.cpu.example").read_text(encoding="utf-8")
    gpu = (ROOT / "deploy/cloud/.env.gpu.example").read_text(encoding="utf-8")
    assert "LLM_RUNTIME_POLICY=cloud" in cpu
    assert "LLM_RUNTIME_POLICY=vllm" in gpu
    assert "VLLM_MODEL=Qwen/Qwen3-14B" in gpu
    assert "CERTIPROOF_VERSION=latest" not in cpu + gpu


def test_nuclei_image_is_not_pinned_to_one_cpu_architecture():
    dockerfile = (ROOT / "mcp-servers/security-tools/Dockerfile").read_text(encoding="utf-8")
    assert "linux_arm64.zip" not in dockerfile
    assert "${TARGETARCH" in dockerfile


def test_tool_dockerfiles_use_valid_apt_mirror_substitution():
    for dockerfile in (ROOT / "mcp-servers").glob("*/Dockerfile"):
        assert "|g| /etc" not in dockerfile.read_text(encoding="utf-8"), dockerfile


def test_publish_workflow_uses_standalone_bake_definition():
    workflow = (ROOT / ".github/workflows/publish-cloud-images.yml").read_text(encoding="utf-8")
    assert "docker buildx bake -f docker-bake.hcl --push" in workflow
    assert "sha-${GITHUB_SHA::12}" in workflow
    assert "aquasecurity/trivy-action@a9c7b0f06e461e9d4b4d1711f154ee024b8d7ab8" in workflow
    assert "anchore/sbom-action@e22c389904149dbc22b58101806040fa8d37a610" in workflow
    assert "sigstore/cosign-installer@6f9f17788090df1f26f669e9d70d6ae9567deba6" in workflow


def test_runtime_services_have_real_healthchecks():
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    expected = {
        "frontend", "backend", "mcp-gateway", "security-tools", "ssh-checker",
        "fast-scanner", "web-tools", "network-tools", "db-tools", "windows-tools",
        "ocr-server", "embedding-server", "interactive-worker", "document-worker",
        "assessment-worker", "verification-worker", "maintenance-worker",
    }
    missing = sorted(name for name in expected if not compose["services"][name].get("healthcheck"))
    assert not missing


def test_cloud_package_contains_verification_and_rollback_scripts():
    package_script = (ROOT / "scripts/package-cloud-deployment.sh").read_text(encoding="utf-8")
    assert "verify-deployment.sh" in package_script
    assert "rollback-production.sh" in package_script


def test_remote_node_package_is_outbound_only_and_versioned():
    compose = yaml.safe_load((ROOT / "deploy/scan-node/docker-compose.remote-node.yml").read_text(encoding="utf-8"))
    assert all("ports" not in service for service in compose["services"].values())
    assert compose["services"]["node"]["command"] == ["python", "-m", "app.remote_node_worker"]
    assert "CERTIPROOF_VERSION" in (ROOT / "scripts/package-remote-node.sh").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/publish-cloud-images.yml").read_text(encoding="utf-8")
    assert "linux/amd64,linux/arm64" in workflow
    assert "package-remote-node.sh online" in workflow
