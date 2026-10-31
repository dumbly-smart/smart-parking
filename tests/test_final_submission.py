from __future__ import annotations

import csv
import json
import re

import pytest

docx = pytest.importorskip("docx")


def test_final_report_is_single_column_and_uses_real_project_results(tmp_path) -> None:
    from scripts.build_final_submission import build_report

    repository = __import__("pathlib").Path(__file__).resolve().parents[1]
    optimizer_directory = repository / "review_outputs/2026-10-15/optimization_results"
    optimizer_summary = json.loads(
        (optimizer_directory / "optimizer_summary.json").read_text(encoding="utf-8")
    )
    assert optimizer_summary["source"] == "executed_sumo_parking_allocations"
    assert (
        optimizer_summary["actual_persisted_parking_sessions"]
        == optimizer_summary["scenario_count"]
    )
    with (optimizer_directory / "optimizer_comparison.csv").open(
        newline="", encoding="utf-8"
    ) as stream:
        optimizer_rows = {row["algorithm"]: row for row in csv.DictReader(stream)}
    with (optimizer_directory / "sumo_observed_scenarios.jsonl").open(
        encoding="utf-8"
    ) as stream:
        scenario_evidence = [json.loads(line) for line in stream]
    assert len(scenario_evidence) == optimizer_summary["scenario_count"]
    assert all(
        len(item["candidates"]) == optimizer_summary["candidate_capacity"]
        for item in scenario_evidence
    )
    report_path = build_report(repository, tmp_path, convert_pdf=False)
    document = docx.Document(report_path)
    from PIL import Image

    for figure_name in (
        "execution_time.png",
        "cost_by_occupancy.png",
        "mae_comparison.png",
        "actual_vs_predicted.png",
        "average_allocation_cost.png",
        "optimality_gap_distribution.png",
        "objective_components.png",
        "hardware_timing_comparison.png",
    ):
        with Image.open(tmp_path / "figures" / figure_name) as figure:
            colors = figure.convert("RGB").getcolors(maxcolors=figure.width * figure.height)
            assert colors is not None
            assert any(max(rgb) - min(rgb) > 20 for _, rgb in colors)

    assert "31 OCTOBER 2026" in document.sections[0].header.paragraphs[0].text
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    text += "\n" + "\n".join(
        cell.text for table in document.tables for row in table.rows for cell in row.cells
    )

    assert "Smart Parking System" in text
    paragraphs = [paragraph.text for paragraph in document.paragraphs]
    abstract = paragraphs[paragraphs.index("Abstract") + 1]
    assert len(abstract.split()) == 250
    assert "NSGA-II" in abstract
    assert f"{float(optimizer_rows['NSGA-II']['mean_cost']):.6f}" in abstract
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
    assert any(
        relationship.target_ref == "https://github.com/dumbly-smart/smart-parking"
        for relationship in document.part.rels.values()
    )
    assert any(
        relationship.target_ref
        == "https://drive.google.com/drive/folders/1dXCsveCgbfZuCycWEzJs6WHaMlbOEg-G"
        for relationship in document.part.rels.values()
    )
    assert "vit.ac.in" in text
    assert "NOT TESTED" in text
    bill_of_materials = (repository / "docs/hardware/bill_of_materials.csv").read_text(
        encoding="utf-8"
    )
    assert "User provided" not in bill_of_materials
    captions = [
        paragraph.text for paragraph in document.paragraphs if paragraph.style.name == "Caption"
    ]
    figure_numbers = [
        int(match.group(1))
        for caption in captions
        if (match := re.match(r"Figure (\d+)(?:\([a-z]\))?\.", caption))
    ]
    table_numbers = [
        int(match.group(1))
        for caption in captions
        if (match := re.match(r"Table (\d+)\.", caption))
    ]
    assert list(dict.fromkeys(figure_numbers)) == list(range(1, 23))
    assert table_numbers == list(range(1, 11))
    assert "Figure 19. 28 October scene capture of the fictional Parkflow Central district" in text
    assert "Figure 22. 28 October overhead parking-map capture" in text
    for algorithm in ("NSGA-II", "GA", "PSO", "ACO", "first_available", "exhaustive_optimum"):
        assert algorithm in text
    assert "SUMO-observed allocation states" in text
    assert "SUMO-observed parking admissions" in text
    assert "configuration, network, and route SHA-256 hashes" in text
    assert "Compare GA, PSO, ACO, and NSGA-II allocation" in text
    assert "API returned GA, PSO, ACO, and NSGA-II benchmark results" in text
    assert "synthetic objective scenarios" not in text.lower()
    for feature in (
        "SUMO start, stop, pause, resume, and reset controls",
        "two arrivals per simulation step",
        "browser refreshes SUMO vehicle snapshots and the parking event stream",
        "manual vehicle-ID simulator or an RFID/keyboard reader",
        "first-person view",
        "QR code that opens the full receipt on a phone",
        "no payment gateway or settlement is implemented",
        "stable pseudonymous parking identity across simulation runs",
        "personalized fairness",
        "equal-weighted mean of each other vehicle's historical mean walking distance",
        "Stable SUMO identities let repeat simulated vehicles retain this history across runs",
        "full software test suite passed 249 tests",
    ):
        assert feature in text
    for attribution_tag in (
        "user-supplied",
        "user supplied",
        "user-reported",
        "user provided",
        "the user reports",
        "the user reported",
    ):
        assert attribution_tag not in text.lower()
    diagram_source = (repository / "docs/hardware/system_architecture.dot").read_text(
        encoding="utf-8"
    )
    assert "NSGA-II" in diagram_source
    assert "GitHub project repository" in text
    assert "Project folder and demonstration video (Google Drive)" in text
    assert "esp32-cam" not in text.lower()
    assert "Table 9. Recorded physical measurements and untested quantities" in text
    assert "Table 10. Rough engineering estimates (not measured)" in text
    assert "4,032" in text
    hardware_evidence = repository / "output/hardware/controller_validation.json"
    if hardware_evidence.exists():
        assert "ESP32-D0WD-V3" in text
        assert "authenticated parking-status responses" in text
        assert "RC522 VersionReg" in text
        assert "0xFF" in text
        assert "2/2 post-rewire RFID test scans succeeded" in text
        assert "no post-rewire trial logs or quantitative measurements were captured" not in text
        assert "quantitative per-component validation remains uncaptured" not in text
        assert "Entry transaction latency: 1431 ms" in text
        assert "Exit transaction latency: 1220 ms" in text
        assert "S1 changed to occupied at entry and free at exit" in text
        assert "LED physical output was not visually verified" in text
        assert (
            "Servo values are command timing; physical movement was not independently measured"
            in text
        )
        assert "no flashing or board execution claimed" not in text
        assert "marks all physical behaviors NOT TESTED" not in text
    else:
        assert "no physical controller validation evidence" in text
    assert len(document.sections) == 1
    assert document.sections[0]._sectPr.xml.count("<w:cols") == 1
    assert 'w:num="1"' in document.sections[0]._sectPr.xml
    assert len(document.inline_shapes) >= 22

    from PIL import Image, ImageChops

    for name in (
        "average_allocation_cost.png",
        "execution_time.png",
        "cost_by_occupancy.png",
        "optimality_gap_distribution.png",
        "objective_components.png",
    ):
        with (
            Image.open(repository / "review_outputs/2026-10-15/optimization_results/figures" / name)
            as expected,
            Image.open(tmp_path / "figures" / name) as actual,
        ):
            difference = ImageChops.difference(expected.convert("RGB"), actual.convert("RGB"))
            assert difference.getbbox() is None
    for source, name in (
        (repository / "docs/hardware/system_block_diagram.png", "system_block_diagram.png"),
        (repository / "docs/hardware/system_architecture.png", "current_system_architecture.png"),
    ):
        with Image.open(source) as expected, Image.open(tmp_path / "figures" / name) as actual:
            difference = ImageChops.difference(expected.convert("RGB"), actual.convert("RGB"))
            assert difference.getbbox() is None
    for source_name, report_name in (
        ("city_district_overview.png", "city_district_overview.png"),
        ("six_floor_garage.png", "six_floor_garage.png"),
        ("first_person_route.png", "first_person_route.png"),
        ("parking_navigation_map.png", "parking_navigation_map.png"),
    ):
        with (
            Image.open(
                repository / "review_outputs/2026-10-15/final_submission/figures" / source_name
            ) as expected,
            Image.open(tmp_path / "figures" / report_name) as actual,
        ):
            difference = ImageChops.difference(expected.convert("RGB"), actual.convert("RGB"))
            assert difference.getbbox() is None
    for name in (
        "hardware_overview.png",
        "rfid_reader_closeup.png",
        "controller_board_front.png",
        "controller_wiring_detail.png",
        "hardware_dashboard_evidence.png",
        "optimizer_comparison.png",
        "dashboard_capture.png",
    ):
        assert not (tmp_path / "figures" / name).exists()


def test_arduino_appendix_uses_checked_in_controller_sources(tmp_path) -> None:
    from scripts.build_final_submission import _build_code_appendix_report

    repository = tmp_path / "repository"
    sources = {
        "firmware/esp32_controller/src/main.cpp": "void setup() { /* current */ }\n",
        "firmware/esp32_controller/include/pins.h": "constexpr int GateServo = 13;\n",
        "firmware/esp32_controller/include/local_config.example.h": (
            'static constexpr char WIFI_PASSWORD[] = "";\n'
        ),
        "firmware/esp32_controller/platformio.ini": "framework = arduino\n",
    }
    for relative_path, contents in sources.items():
        source = repository / relative_path
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_text(contents, encoding="utf-8")
    base_report = tmp_path / "base.docx"
    docx.Document().save(base_report)

    output = _build_code_appendix_report(base_report, tmp_path / "with_code.docx", repository)
    document = docx.Document(output)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)

    assert "Appendix A. Current ESP32 Arduino controller source" in text
    assert "void setup() { /* current */ }" in text
    assert "constexpr int GateServo = 13;" in text
    assert 'WIFI_PASSWORD[] = ""' in text
    assert "framework = arduino" in text


def test_submission_archive_sync_replaces_old_reports_and_stale_assets(tmp_path) -> None:
    from scripts.build_final_submission import _sync_archived_submission

    repository = tmp_path / "repository"
    output = repository / "output/final_submission"
    archive = repository / "review_outputs/2026-10-15/final_submission"
    (archive / "figures").mkdir(parents=True)
    (archive / "hardware").mkdir(parents=True)
    (archive / "figures/optimizer_comparison.png").write_bytes(b"stale")
    output.mkdir(parents=True)
    (output / "figures").mkdir()
    (output / "evidence").mkdir()
    (repository / "docs/hardware").mkdir(parents=True)
    for name in (
        "Smart_Parking_Final_Report.docx",
        "Smart_Parking_Final_Report.pdf",
        "README.md",
        "SUBMISSION_CHECKLIST.md",
        "REFERENCES_VERIFIED.md",
    ):
        (output / name).write_text("current", encoding="utf-8")
    (output / "figures/average_allocation_cost.png").write_bytes(b"NSGA-II chart")
    (output / "evidence/optimizer_comparison.csv").write_text("NSGA-II\n", encoding="utf-8")
    (repository / "docs/hardware/system_architecture.dot").write_text("NSGA-II", encoding="utf-8")

    _sync_archived_submission(repository, output)

    assert (archive / "Smart_Parking_Final_Report.pdf").read_text(encoding="utf-8") == "current"
    assert (archive / "figures/average_allocation_cost.png").read_bytes() == b"NSGA-II chart"
    archived_metrics = (archive / "evidence/optimizer_comparison.csv").read_text(
        encoding="utf-8"
    )
    assert archived_metrics == "NSGA-II\n"
    assert (archive / "hardware/system_architecture.dot").read_text(encoding="utf-8") == "NSGA-II"
    assert not (archive / "figures/optimizer_comparison.png").exists()
