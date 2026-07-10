import sys
from pathlib import Path
import importlib.util

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "app" / "services" / "document_control_engine.py"
spec = importlib.util.spec_from_file_location("document_control_engine", MODULE)
module = importlib.util.module_from_spec(spec)
sys.modules["document_control_engine"] = module
spec.loader.exec_module(module)
DocumentControlEngine = module.DocumentControlEngine


def main():
    engine = DocumentControlEngine()
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
    print("document control engine check passed")


if __name__ == "__main__":
    main()
