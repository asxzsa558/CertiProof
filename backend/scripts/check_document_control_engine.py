import sys
from pathlib import Path
import importlib.util
import yaml

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "app" / "services" / "document_control_engine.py"
spec = importlib.util.spec_from_file_location("document_control_engine", MODULE)
module = importlib.util.module_from_spec(spec)
sys.modules["document_control_engine"] = module
spec.loader.exec_module(module)
DocumentControlEngine = module.DocumentControlEngine


def main():
    library = yaml.safe_load((ROOT.parent / "reference" / "compliance" / "document_controls.yaml").read_text(encoding="utf-8"))
    engine = DocumentControlEngine(library)
    docs = engine.documents
    assert len(docs) == 10, f"expected 10 core documents, got {len(docs)}"

    control_ids = set()
    for key, doc in docs.items():
        controls = doc.get("controls") or []
        points = [
            point
            for control in controls
            for point in control.get("required_points", [])
        ]
        assert len(controls) >= 4, f"{key} has too few controls"
        assert len(points) >= 8, f"{key} has too few required points"

        for control in controls:
            assert control["id"] not in control_ids, f"duplicate control id {control['id']}"
            control_ids.add(control["id"])
            assert control.get("title"), f"{control['id']} missing title"
            for point in control.get("required_points", []):
                assert point.get("text"), f"{control['id']} missing point text"
                assert point.get("evidence_keywords"), f"{control['id']} missing keywords"
                assert point.get("missing_judgement"), f"{control['id']} missing missing_judgement"

        sample_lines = [doc["name"]]
        for point in points:
            sample_lines.append(" ".join(point["evidence_keywords"][:2]))
        result = engine.analyze("\n".join(sample_lines), f"{doc['name']}.txt", doc["name"])
        assert result["document_name"] == doc["name"], f"{key} standard selection failed"
        assert result["status"] == "pass", f"{key} expected pass, got {result['status']}"

    sample = """
信息安全管理制度
一、适用范围
本制度适用于公司所有业务系统、网络设备、服务器和相关人员。
二、安全目标
建立统一的信息安全管理目标，保障业务连续性和数据安全。
三、安全职责
安全管理员负责日常管理，各责任部门落实岗位职责。
"""
    result = engine.analyze(sample, "信息安全管理制度.docx", "信息安全管理制度")
    assert result["document_name"] == "信息安全管理制度"
    assert result["status"] in {"fail", "partial"}
    assert result["gaps"], "样本文档缺多项要求，应产生差距"

    arbitrary_name = engine.analyze(sample, "随便命名-V2-终稿.docx", "信息安全事件应急预案")
    assert arbitrary_name["document_name"] == "信息安全事件应急预案"
    assert arbitrary_name["controls"], "文件名不得影响任务标准选择"

    empty = engine.analyze("", "任意名称.docx", "信息安全管理制度")
    assert empty["status"] == "unable"
    assert "正文" in empty["message"]

    versioned = engine.classify_blocks(
        "安全事件管理制度V2-2026.docx",
        [{"type": "heading", "page": 1, "text": "安全事件管理制度"}, {"type": "text", "page": 1, "text": "安全事件报告、处置、复盘和改进"}],
    )
    assert versioned["status"] == "classified"
    assert versioned["document_name"] == "安全事件管理制度"
    assert versioned["naming_status"] == "matched"

    recovered = engine.classify_blocks(
        "随便写的文件.docx",
        [{"type": "heading", "page": 1, "text": "信息安全管理机构设置文件"}, {"type": "text", "page": 1, "text": "安全委员会领导小组负责人及职责分工"}],
    )
    assert recovered["status"] == "classified"
    assert recovered["document_name"] == "信息安全管理机构设置文件"
    assert recovered["naming_status"] == "filename_warning"

    unrelated = engine.classify_blocks(
        "普通会议纪要.docx",
        [{"type": "heading", "page": 1, "text": "周例会记录"}, {"type": "text", "page": 1, "text": "本周完成项目沟通和行政安排"}],
    )
    assert unrelated["status"] == "unclassified"

    wrapped = engine._parse_llm_json(
        '<think>先核对证据完整性</think>\n```json\n{"decisions":[{"control_id":"C1","point_id":"P1","decision":"partial"}]}\n```'
    )
    assert wrapped[0]["decision"] == "partial"
    classified_payload = engine._parse_llm_object(
        '分析完成：```json\n{"primary_key":"security_management_policy","confidence":0.91,"reason":"标题与正文一致"}\n```'
    )
    assert classified_payload["primary_key"] == "security_management_policy"

    merged = engine._merge_candidates(
        [{"block_id": 1, "text": "审计日志", "retrieval_sources": ["exact"], "matched_keywords": ["审计"]}],
        [{"block_id": 1, "text": "审计日志", "retrieval_sources": ["vector"]}],
    )
    assert merged[0]["retrieval_sources"] == ["exact", "vector"]
    assert merged[0]["matched_keywords"] == ["审计"]
    print("document control engine check passed")


if __name__ == "__main__":
    main()
