import io
import zipfile

import pytest

from app.services.document_pipeline import (
    DocumentExtractionError,
    expand_document_upload,
    safe_document_name,
)


def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_folder_name_and_zip_members_preserve_safe_relative_paths():
    assert safe_document_name("制度包/人员/人员安全管理制度V2.txt") == "制度包/人员/人员安全管理制度V2.txt"

    documents, skipped = expand_document_upload(
        "制度包.zip",
        _zip_bytes({
            "制度/信息安全管理制度.txt": "制度正文".encode(),
            "附件/说明.csv": b"ignored",
            "__MACOSX/._metadata": b"ignored",
        }),
    )

    assert documents == [("制度/信息安全管理制度.txt", "制度正文".encode())]
    assert skipped == ["附件/说明.csv"]


@pytest.mark.parametrize("member", ["../escape.txt", "/absolute.txt", "docs/../../escape.txt"])
def test_zip_rejects_path_traversal(member):
    with pytest.raises(DocumentExtractionError, match="不安全的文件路径"):
        expand_document_upload("unsafe.zip", _zip_bytes({member: b"blocked"}))


def test_zip_rejects_nested_archives():
    with pytest.raises(DocumentExtractionError, match="嵌套压缩包"):
        expand_document_upload("nested.zip", _zip_bytes({"docs/materials.7z": b"blocked"}))
