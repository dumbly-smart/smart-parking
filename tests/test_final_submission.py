from __future__ import annotations

import pytest

docx = pytest.importorskip("docx")


def test_final_report_is_single_column_and_uses_real_project_results(tmp_path) -> None:
    from scripts.build_final_submission import build_report

    repository = __import__("pathlib").Path(__file__).resolve().parents[1]
    report_path = build_report(repository, tmp_path, convert_pdf=False)
    document = docx.Document(report_path)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    text += "\n" + "\n".join(
        cell.text for table in document.tables for row in table.rows for cell in row.cells
    )

    assert "Smart Parking System" in text
    assert "4,032" in text
    assert "0.098055" in text
    assert "model=gru" in text
    assert "fallback_reason=null" in text
    assert "vit.ac.in" in text
    assert "NOT TESTED" in text
    assert len(document.sections) == 1
    assert document.sections[0]._sectPr.xml.count("<w:cols") == 1
    assert 'w:num="1"' in document.sections[0]._sectPr.xml
    assert len(document.inline_shapes) >= 8
