"""Small deterministic check for the standards graph import contract."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "reference" / "compliance" / "document_controls.yaml"


def main() -> None:
    library = yaml.safe_load(BUNDLE.read_text(encoding="utf-8"))
    defaults = library.get("requirement_defaults") or {}
    documents = library.get("documents") or {}
    controls = [control for document in documents.values() for control in document.get("controls") or []]
    requirements = [
        (control["id"], point)
        for control in controls
        for point in control.get("required_points") or []
    ]
    control_ids = [control["id"] for control in controls]
    requirement_ids = [f"{control_id}:{point['id']}" for control_id, point in requirements]

    assert library.get("version"), "standard bundle must be versioned"
    assert len(documents) == 10, f"expected 10 core document types, got {len(documents)}"
    assert len(requirements) >= 80, f"expected at least 80 requirements, got {len(requirements)}"
    assert len(control_ids) == len(set(control_ids)), "control IDs must be unique"
    assert len(requirement_ids) == len(set(requirement_ids)), "requirement IDs must be unique"
    for document_key, document in documents.items():
        assert document.get("name"), f"{document_key} is missing a display name"
        assert document.get("aliases"), f"{document_key} is missing classification aliases"
        for control in document.get("controls") or []:
            assert control.get("title"), f"{control['id']} is missing a title"
            for point in control.get("required_points") or []:
                assert point.get("text"), f"{control['id']}:{point['id']} is missing evidence text"
                assert point.get("evidence_keywords"), f"{control['id']}:{point['id']} is missing exact-search terms"
                assert point.get("missing_judgement"), f"{control['id']}:{point['id']} is missing a failure rule"
                assert point.get("required_evidence") or defaults.get("required_evidence")
                assert point.get("completeness") or defaults.get("completeness")
                assert point.get("negative_conditions") or defaults.get("negative_conditions")
                assert point.get("severity") or defaults.get("severity")
                assert point.get("remediation") or defaults.get("remediation_template")

    expected_nodes = 1 + len(documents) + len(controls) + len(requirements) * 3
    expected_edges = len(documents) + len(controls) + len(requirements) * 3
    print(
        f"knowledge graph bundle ok: version={library['version']} "
        f"documents={len(documents)} controls={len(controls)} "
        f"requirements={len(requirements)} nodes={expected_nodes} edges={expected_edges}"
    )


if __name__ == "__main__":
    main()
