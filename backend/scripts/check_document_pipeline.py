import tempfile
from pathlib import Path
from types import SimpleNamespace

from docx import Document

from app.services.document_control_engine import DocumentControlEngine
from app.services.document_pipeline import _deduplicate, _docx_native


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "arbitrary-name-v2.docx"
    document = Document()
    document.sections[0].header.paragraphs[0].text = "受控文件"
    document.sections[0].footer.paragraphs[0].text = "第 1 页"
    document.add_heading("安全事件管理", level=1)
    document.add_paragraph("安全事件应当分级、报告并及时处置。")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "责任人"
    table.cell(0, 1).text = "安全管理员"
    table.cell(1, 0).text = "处置要求"
    table.cell(1, 1).text = "记录、复盘和改进"
    document.save(path)

    evidence = SimpleNamespace(id=1, file_name=path.name)
    blocks, images, pages = _docx_native(path, evidence)
    types = {block["type"] for block in blocks}
    assert {"heading", "text", "table", "header", "footer"} <= types
    assert not images
    assert pages == 1

    duplicate = dict(blocks[0], block_id="duplicate", source="vision")
    merged = _deduplicate([duplicate, *blocks])
    assert len(merged) == len(blocks)
    assert merged[0]["source"] == "native"

    analysis = DocumentControlEngine().analyze_blocks(blocks, "安全事件管理制度")
    assert analysis["status"] in {"pass", "partial", "fail"}
    evidence_items = [
        item
        for control in analysis["controls"]
        for point in control["points"]
        for item in point["evidence"]
    ]
    assert evidence_items
    assert all(item["evidence_id"] == 1 for item in evidence_items)
    assert all(item["file_name"] == path.name for item in evidence_items)
    report_point = analysis["controls"][0]["points"][0]
    assert report_point["evidence"], "同一内容块内的“事件…报告”应召回“事件报告”检查点"

print("document pipeline checks passed")
