from pathlib import Path

from docx import Document
from openpyxl import Workbook

from casepilot_agent.knowledge import build_chunks, parse_document, pretokenize
from casepilot_agent.providers.mock import MockProvider
from casepilot_agent.store import lexical_search_terms


def test_markdown_structural_chunking_keeps_parent_child_and_locator(
    tmp_path: Path,
) -> None:
    path = tmp_path / "requirement.md"
    path.write_text(
        "# 账号中心\n## REQ-LOGIN-001 登录\n"
        + "\n".join(f"- 验收规则 {index}：输入合法时返回可观察状态" for index in range(180)),
        encoding="utf-8",
    )
    blocks = parse_document(path, "text/markdown")
    chunks = build_chunks(
        title="账号中心需求",
        blocks=blocks,
        provider=MockProvider(),
    )

    parents = [chunk for chunk in chunks if chunk["chunk_type"] == "parent"]
    children = [chunk for chunk in chunks if chunk["chunk_type"] == "child"]
    assert parents and children
    assert all(child["parent_key"] for child in children)
    assert all(child["token_count"] <= 650 for child in children)
    assert all(len(chunk["embedding"]) == 2048 for chunk in chunks)
    assert "账号中心需求" in children[0]["contextual_content"]


def test_docx_xlsx_and_csv_keep_native_location(tmp_path: Path) -> None:
    docx_path = tmp_path / "rules.docx"
    document = Document()
    document.add_heading("退款规则", level=1)
    document.add_paragraph("重复退款请求必须保持幂等。")
    document.save(docx_path)

    xlsx_path = tmp_path / "cases.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "验收标准"
    sheet.append(["需求编号", "规则"])
    sheet.append(["REQ-REFUND-001", "退款成功后状态可查询"])
    workbook.save(xlsx_path)

    csv_path = tmp_path / "errors.csv"
    csv_path.write_text("错误码,含义\nE1001,订单不存在\n", encoding="utf-8")

    docx_blocks = parse_document(
        docx_path,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    xlsx_blocks = parse_document(
        xlsx_path,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    csv_blocks = parse_document(csv_path, "text/csv")

    assert docx_blocks[0].section_path == "退款规则"
    assert "Sheet 验收标准" in xlsx_blocks[0].locator
    assert csv_blocks[0].locator == "行 1-2"


def test_chinese_pretokenization_preserves_requirement_and_error_codes() -> None:
    tokens = pretokenize("REQ-PAY-001 支付失败返回错误码 E1001")
    assert "REQ" in tokens
    assert "E1001" in tokens


def test_chinese_lexical_terms_remove_punctuation_and_keep_question_keywords() -> None:
    terms = lexical_search_terms(
        pretokenize("根据内部知识库，文本摘要默认保留多久，用户能否关闭保存？")
    )

    assert {"文本", "摘要", "默认", "保留", "关闭", "保存"}.issubset(terms)
    assert "，" not in terms
    assert "？" not in terms


def test_chunks_remain_searchable_without_embedding_provider(tmp_path: Path) -> None:
    path = tmp_path / "fallback.md"
    path.write_text("# 支付\nREQ-PAY-001 支付失败返回 E1001", encoding="utf-8")

    chunks = build_chunks(
        title="支付需求",
        blocks=parse_document(path, "text/markdown"),
    )

    assert chunks
    assert all(chunk["embedding"] is None for chunk in chunks)
    assert all(chunk["search_text"] for chunk in chunks)


def test_excel_markdown_is_offline_and_preserves_cells_and_coordinates(tmp_path, monkeypatch):
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("Excel conversion attempted network access")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    path = tmp_path / "requirements.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "需求"
    sheet.append(["编号", "规则"])
    sheet.append(["00123", "NA"])
    sheet.append([None, None])
    sheet.append(["NULL", "第一步\n第二步 | <script>literal</script>"])
    sheet.append(["公式", "=1+2"])
    sheet["B4"].hyperlink = "https://example.invalid/never-fetch"
    for row in range(6, 44):
        sheet.cell(row, 1, f"REQ-{row}")
    workbook.create_sheet("其他").append(["第二个工作表"])
    workbook.save(path)
    blocks = parse_document(path, "application/octet-stream")
    assert len(blocks) == 3
    assert {
        key: value for key, value in blocks[0].metadata.items() if key != "spreadsheet_rows"
    } == {"sheet": "需求", "row_start": 1, "row_end": 41}
    assert blocks[0].metadata["spreadsheet_rows"][1] == {
        "row": 2, "cells": {"A2": "00123", "B2": "NA"},
    }
    assert blocks[1].locator == "Sheet 需求，行 42-43"
    assert blocks[2].section_path == "其他"
    text = blocks[0].content
    for literal in ("00123", "NA", "NULL", "第一步", "第二步", "literal", "=1+2", "原始行号"):
        assert literal in text
    assert "| ---" in text
    assert "| 4 |" in text


def test_legacy_excel_converts_all_sheets_offline(tmp_path, monkeypatch):
    import socket

    import xlwt

    def no_network(*args, **kwargs):
        raise AssertionError("Excel conversion attempted network access")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    path = tmp_path / "requirements.xls"
    workbook = xlwt.Workbook()
    sheet = workbook.add_sheet("验收规则")
    sheet.write(0, 0, "编号")
    sheet.write(2, 0, "00007")
    sheet.write(2, 1, "NULL")
    workbook.add_sheet("补充").write(0, 0, "NA")
    workbook.save(str(path))
    blocks = parse_document(path, "application/vnd.ms-excel")
    assert len(blocks) == 2
    assert blocks[0].locator == "Sheet 验收规则，行 1-3"
    assert "00007" in blocks[0].content
    assert "NULL" in blocks[0].content
    assert "NA" in blocks[1].content


def test_corrupt_excel_fails_instead_of_reading_as_text(tmp_path):
    from zipfile import BadZipFile

    import pytest
    from xlrd import XLRDError

    for extension in ("xlsx", "xls"):
        path = tmp_path / f"broken.{extension}"
        path.write_bytes(b"not an Excel workbook")
        with pytest.raises((BadZipFile, XLRDError)):
            parse_document(path, "application/octet-stream")


def test_short_native_pdf_text_does_not_require_ocr(monkeypatch):
    import pymupdf
    from casepilot_agent import knowledge
    document = pymupdf.open()
    document.new_page().insert_text((72, 72), 'Error E731')
    monkeypatch.setattr(knowledge, '_ocr_image', lambda _: (_ for _ in ()).throw(AssertionError('unnecessary OCR')))
    blocks = knowledge._parse_pdf(document.tobytes())
    assert blocks[0].content == 'Error E731'
    document.close()


def test_ocr_failure_categories_are_safe_and_distinct(monkeypatch):
    import pytest
    import pytesseract
    from PIL import Image
    from casepilot_agent import knowledge
    for error, expected in [
        (pytesseract.TesseractNotFoundError(), knowledge.DocumentOcrUnavailable),
        (pytesseract.TesseractError(1, 'private engine diagnostic'), knowledge.DocumentOcrFailed),
        (RuntimeError('OCR process timeout'), knowledge.DocumentOcrFailed),
    ]:
        def fail(*args, **kwargs):
            assert kwargs['timeout'] == 60
            raise error
        monkeypatch.setattr(pytesseract, 'image_to_string', fail)
        with pytest.raises(expected) as captured:
            knowledge._ocr_image(Image.new('RGB', (10, 10)))
        assert str(captured.value) == ''
