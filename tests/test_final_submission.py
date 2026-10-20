from __future__ import annotations

import re

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
    assert "Public dataset ZIP (GitHub)" in text
    assert any(
        relationship.target_ref
        == "https://github.com/dumbly-smart/smart-parking/raw/5b480d1/review_outputs/2026-10-15/dataset/parking_dataset.zip"
        for relationship in document.part.rels.values()
    )
    assert "vit.ac.in" in text
    assert "NOT TESTED" in text
    captions = [
        paragraph.text for paragraph in document.paragraphs if paragraph.style.name == "Caption"
    ]
    figure_numbers = [
        int(match.group(1))
        for caption in captions
        if (match := re.match(r"Figure (\d+)\.", caption))
    ]
    table_numbers = [
        int(match.group(1))
        for caption in captions
        if (match := re.match(r"Table (\d+)\.", caption))
    ]
    assert figure_numbers == list(range(1, 18))
    assert table_numbers == list(range(1, 9))
    assert "4,032" in text
    assert "CH340 USB serial adapter" in text
    assert "not resolved from the test host" in text
    assert len(document.sections) == 1
    assert document.sections[0]._sectPr.xml.count("<w:cols") == 1
    assert 'w:num="1"' in document.sections[0]._sectPr.xml
    assert len(document.inline_shapes) >= 8
