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
