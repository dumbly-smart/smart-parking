"""Build an editable single-column academic report from checked-in results."""

# Academic prose, typographic punctuation, and citation URLs are deliberate.
# ruff: noqa: E501, RUF001

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image

REVIEW = Path("review_outputs/2026-10-15")
DATASET_PUBLIC_URL = "https://github.com/dumbly-smart/smart-parking/raw/5b480d1/review_outputs/2026-10-15/dataset/parking_dataset.zip"
PROJECT_GITHUB_URL = "https://github.com/dumbly-smart/smart-parking"
PROJECT_DRIVE_FOLDER_URL = "https://drive.google.com/drive/folders/1dXCsveCgbfZuCycWEzJs6WHaMlbOEg-G"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _set_cell_shading(cell: Any, fill: str) -> None:
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:fill"), fill)
    properties.append(shading)


def _set_cell_margins(
    cell: Any, top: int = 70, start: int = 80, bottom: int = 70, end: int = 80
) -> None:
    properties = cell._tc.get_or_add_tcPr()
    margins = OxmlElement("w:tcMar")
    for edge, value in (("top", top), ("start", start), ("bottom", bottom), ("end", end)):
        node = OxmlElement(f"w:{edge}")
        node.set(qn("w:w"), str(value))
        node.set(qn("w:type"), "dxa")
        margins.append(node)
    properties.append(margins)


def _keep_table_rows_together(table: Any) -> None:
    for row in table.rows:
        properties = row._tr.get_or_add_trPr()
        properties.append(OxmlElement("w:cantSplit"))


def _add_table(
    document: Document, headers: list[str], rows: list[list[str]], *, font_size: int = 8
) -> Any:
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    for index, text in enumerate(headers):
        cell = table.rows[0].cells[index]
        cell.text = text
        _set_cell_shading(cell, "F0F0F0")
        cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
        for paragraph in cell.paragraphs:
            for run in paragraph.runs:
                run.bold = True
                run.font.size = Pt(font_size)
    header_props = table.rows[0]._tr.get_or_add_trPr()
    header_props.append(OxmlElement("w:tblHeader"))
    for row in rows:
        cells = table.add_row().cells
        for index, text in enumerate(row):
            cells[index].text = str(text)
            cells[index].vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            _set_cell_margins(cells[index])
            for paragraph in cells[index].paragraphs:
                paragraph.paragraph_format.space_after = Pt(0)
                for run in paragraph.runs:
                    run.font.size = Pt(font_size)
    _keep_table_rows_together(table)
    document.add_paragraph().paragraph_format.space_after = Pt(2)
    return table


def _add_caption(document: Document, text: str) -> None:
    paragraph = document.add_paragraph(style="Caption")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.keep_with_previous = True
    paragraph.add_run(text)


def _add_table_caption(document: Document, text: str) -> None:
    paragraph = document.add_paragraph(style="Caption")
    paragraph.alignment = WD_ALIGN_PARAGRAPH.LEFT
    paragraph.paragraph_format.keep_with_next = True
    paragraph.add_run(text)


def _add_figure(document: Document, figures: Path, filename: str, caption: str) -> bool:
    path = figures / filename
    if not path.is_file():
        return False
    paragraph = document.add_paragraph()
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.paragraph_format.keep_with_next = True
    width = 4.1 if filename == "parking_transaction_flow.png" else 6.25
    paragraph.add_run().add_picture(str(path), width=Inches(width))
    _add_caption(document, caption)
    return True


def _add_hyperlink(paragraph: Any, text: str, url: str) -> None:
    relationship_id = paragraph.part.relate_to(
        url,
        "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink",
        is_external=True,
    )
    hyperlink = OxmlElement("w:hyperlink")
    hyperlink.set(qn("r:id"), relationship_id)
    run = OxmlElement("w:r")
    properties = OxmlElement("w:rPr")
    color = OxmlElement("w:color")
    color.set(qn("w:val"), "000000")
    properties.append(color)
    underline = OxmlElement("w:u")
    underline.set(qn("w:val"), "single")
    properties.append(underline)
    run.append(properties)
    content = OxmlElement("w:t")
    content.text = text
    run.append(content)
    hyperlink.append(run)
    paragraph._p.append(hyperlink)


def _add_page_number(paragraph: Any) -> None:
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.add_run("Smart Parking System  ·  ")
    field_begin = OxmlElement("w:fldChar")
    field_begin.set(qn("w:fldCharType"), "begin")
    instruction = OxmlElement("w:instrText")
    instruction.set(qn("xml:space"), "preserve")
    instruction.text = " PAGE "
    field_end = OxmlElement("w:fldChar")
    field_end.set(qn("w:fldCharType"), "end")
    run = OxmlElement("w:r")
    run.append(field_begin)
    paragraph._p.append(run)
    run = OxmlElement("w:r")
    run.append(instruction)
    paragraph._p.append(run)
    run = OxmlElement("w:r")
    run.append(field_end)
    paragraph._p.append(run)


def _style_document(document: Document) -> None:
    section = document.sections[0]
    section.different_first_page_header_footer = True
    section.page_width = Inches(8.27)
    section.page_height = Inches(11.69)
    section.top_margin = Inches(0.72)
    section.bottom_margin = Inches(0.72)
    section.left_margin = Inches(0.82)
    section.right_margin = Inches(0.82)
    # Explicit single-column setting for academic submission layout.
    for existing_columns in section._sectPr.findall(qn("w:cols")):
        section._sectPr.remove(existing_columns)
    columns = OxmlElement("w:cols")
    columns.set(qn("w:num"), "1")
    section._sectPr.append(columns)

    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(10.5)
    normal.paragraph_format.line_spacing = 1.08
    normal.paragraph_format.space_after = Pt(5)
    for style_name, size, color in (
        ("Title", 22, "000000"),
        ("Heading 1", 15, "000000"),
        ("Heading 2", 12, "000000"),
        ("Heading 3", 10.5, "000000"),
    ):
        style = document.styles[style_name]
        style.font.name = "Times New Roman"
        style.font.size = Pt(size)
        style.font.bold = True
        style.font.color.rgb = RGBColor.from_string(color)
        style.paragraph_format.keep_with_next = True
        style.paragraph_format.space_before = Pt(9)
        style.paragraph_format.space_after = Pt(4)
    title_properties = document.styles["Title"]._element.get_or_add_pPr()
    for paragraph_border in title_properties.findall(qn("w:pBdr")):
        title_properties.remove(paragraph_border)
    document.styles["Caption"].font.name = "Times New Roman"
    document.styles["Caption"].font.size = Pt(9)
    document.styles["Caption"].font.italic = True
    document.styles["Caption"].font.color.rgb = RGBColor(0, 0, 0)
    header = section.header.paragraphs[0]
    header.text = "FINAL PROJECT REPORT  ·  31 OCTOBER 2026"
    header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    for run in header.runs:
        run.font.name = "Times New Roman"
        run.font.size = Pt(8)
        run.font.color.rgb = RGBColor(0, 0, 0)
    _add_page_number(section.footer.paragraphs[0])
    section.first_page_header.paragraphs[0].clear()
    section.first_page_footer.paragraphs[0].clear()


def _paragraph(document: Document, text: str) -> None:
    document.add_paragraph(text)


def _bullet(document: Document, text: str) -> None:
    document.add_paragraph(text, style="List Bullet")


def _heading(document: Document, text: str, level: int = 1) -> None:
    document.add_heading(text, level=level)


def _add_model_results_table(document: Document, root: Path) -> list[dict[str, str]]:
    model_rows = _read_csv(root / REVIEW / "ml_results/model_comparison.csv")
    _add_table_caption(document, "Table 5. Test-set prediction performance by model")
    _add_table(
        document,
        ["Model", "MAE", "MSE", "RMSE", "Latency ms/example", "Size bytes"],
        [
            [
                row["model"],
                f"{float(row['mae']):.6f}",
                f"{float(row['mse']):.6f}",
                f"{float(row['rmse']):.6f}",
                f"{float(row['inference_latency_ms']):.6f}",
                row["model_size_bytes"],
            ]
            for row in model_rows
        ],
    )
    return model_rows


def _prepare_additional_figures(repository_root: Path, figures: Path) -> None:
    """Render editable diagrams and prepare the dashboard capture."""
    hardware_docs = repository_root / "docs/hardware"
    for stem in ("parking_transaction_flow", "parking_session_state"):
        source = hardware_docs / f"{stem}.dot"
        subprocess.run(
            ["dot", "-Tsvg", str(source), "-o", str(hardware_docs / f"{stem}.svg")],
            check=True,
        )
        subprocess.run(
            ["dot", "-Tpng", "-Gdpi=180", str(source), "-o", str(figures / f"{stem}.png")],
            check=True,
        )

    summary_path = repository_root / "output/hardware/hardware_summary.json"
    if summary_path.is_file():
        metrics = json.loads(summary_path.read_text(encoding="utf-8")).get("metrics", {})
        samples = [
            ("Entry API", metrics.get("entry_response_latency_ms", {})),
            ("Exit API", metrics.get("exit_response_latency_ms", {})),
            ("Gate command", metrics.get("servo_command_delay_ms", {})),
        ]
        measured = [(name, values["mean"]) for name, values in samples if values.get("status") == "MEASURED"]
        if measured:
            import matplotlib

            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            figure, axis = plt.subplots(figsize=(7.0, 3.4))
            bars = axis.bar(
                [name for name, _ in measured],
                [value for _, value in measured],
                color=("#2563EB", "#0F766E", "#F59E0B")[: len(measured)],
                edgecolor="black",
                linewidth=0.7,
            )
            axis.set_ylabel("Mean event latency (ms)")
            axis.set_title("Observed controller/API timing")
            axis.grid(axis="y", color="0.82", linewidth=0.5)
            axis.set_axisbelow(True)
            axis.spines[["top", "right"]].set_visible(False)
            for bar, (_, value) in zip(bars, measured, strict=True):
                axis.text(bar.get_x() + bar.get_width() / 2, value, f"{value:.0f}", ha="center", va="bottom", fontsize=8)
            figure.tight_layout()
            figure.savefig(figures / "hardware_timing_comparison.png", dpi=180, facecolor="white")
            plt.close(figure)


def _add_optimizer_results_table(document: Document, root: Path) -> list[dict[str, str]]:
    optimizer_rows = _read_csv(root / REVIEW / "optimization_results/optimizer_comparison.csv")
    _add_table_caption(document, "Table 6. Allocation performance across all repeated runs")
    _add_table(
        document,
        ["Policy", "Success / attempts", "Mean cost", "Median runtime ms", "Mean gap", "Invalid"],
        [
            [
                row["algorithm"],
                f"{row['successful_runs']} / 360",
                f"{float(row['mean_cost']):.6f}",
                f"{float(row['median_runtime_ms']):.6f}",
                f"{float(row['mean_optimality_gap']):.6f}",
                row["invalid_assignments"],
            ]
            for row in optimizer_rows
        ],
    )
    return optimizer_rows


def build_report(
    repository_root: Path, output_directory: Path, *, convert_pdf: bool = True
) -> Path:
    """Create a polished DOCX using only checked-in results and local diagrams."""
    repository_root = repository_root.resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    source_figures = repository_root / REVIEW / "final_submission/figures"
    figures = output_directory / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    for source in source_figures.glob("*.png"):
        with Image.open(source) as image:
            image.convert("RGB").save(figures / source.name)
    ml_figures = repository_root / REVIEW / "ml_results/figures"
    for filename in (
        "actual_vs_predicted.png",
        "gru_loss.png",
        "latency_comparison.png",
        "lstm_loss.png",
        "mae_comparison.png",
        "prediction_error_distribution.png",
        "rmse_comparison.png",
        "transformer_loss.png",
    ):
        source = ml_figures / filename
        if source.is_file():
            with Image.open(source) as image:
                image.convert("RGB").save(figures / filename)
    benchmark_figures = repository_root / REVIEW / "optimization_results/figures"
    for filename in (
        "average_allocation_cost.png",
        "execution_time.png",
        "cost_by_occupancy.png",
        "optimality_gap_distribution.png",
        "objective_components.png",
    ):
        source = benchmark_figures / filename
        if source.is_file():
            with Image.open(source) as image:
                image.save(figures / filename)
    architecture_image = repository_root / "docs/hardware/system_architecture.png"
    if architecture_image.is_file():
        with Image.open(architecture_image) as image:
            image.convert("RGB").save(figures / "current_system_architecture.png")
    _prepare_additional_figures(repository_root, figures)
    screenshot_sources = {
        name: name
        for name in (
            "city_district_overview.png",
            "six_floor_garage.png",
            "first_person_route.png",
            "parking_navigation_map.png",
        )
    }
    for output_name, source_name in screenshot_sources.items():
        source = source_figures / source_name
        if not source.is_file():
            raise FileNotFoundError(f"required current UI evidence is missing: {source}")
        with Image.open(source) as image:
            image.convert("RGB").save(figures / output_name)
    for filename in (
        "hardware_overview.png",
        "rfid_reader_closeup.png",
        "controller_board_front.png",
        "controller_wiring_detail.png",
        "hardware_dashboard_evidence.png",
        "optimizer_comparison.png",
        "dashboard_capture.png",
    ):
        (figures / filename).unlink(missing_ok=True)
    metadata = json.loads(
        (repository_root / REVIEW / "dataset/dataset_metadata.json").read_text(encoding="utf-8")
    )
    optimizer_summary = json.loads(
        (repository_root / REVIEW / "optimization_results/optimizer_summary.json").read_text(
            encoding="utf-8"
        )
    )
    optimizer_metrics = {
        row["algorithm"]: row
        for row in _read_csv(repository_root / REVIEW / "optimization_results/optimizer_comparison.csv")
    }
    model_rows = _read_csv(repository_root / REVIEW / "ml_results/model_comparison.csv")
    models = {row["model"]: row for row in model_rows}
    hardware_validation_path = repository_root / "output/hardware/controller_validation.json"
    hardware_summary_path = repository_root / "output/hardware/hardware_summary.json"
    hardware_validation = (
        json.loads(hardware_validation_path.read_text(encoding="utf-8"))
        if hardware_validation_path.exists()
        else None
    )
    hardware_summary = (
        json.loads(hardware_summary_path.read_text(encoding="utf-8"))
        if hardware_summary_path.exists()
        else None
    )
    hardware_metrics = hardware_summary.get("metrics", {}) if hardware_summary else {}
    rfid_metric = hardware_metrics.get("rfid_read_success_rate", {})
    api_metric = hardware_metrics.get("api_transaction_success_rate", {})
    entry_metric = hardware_metrics.get("entry_response_latency_ms", {})
    exit_metric = hardware_metrics.get("exit_response_latency_ms", {})
    gate_metric = hardware_metrics.get("servo_command_delay_ms", {})
    if (
        rfid_metric.get("status") == "MEASURED"
        and api_metric.get("status") == "MEASURED"
        and (entry_metric.get("mean") is None or exit_metric.get("mean") is None)
    ):
        raise ValueError("measured RFID transactions require entry and exit latency samples")
    document = Document()
    _style_document(document)

    title = document.add_paragraph(style="Title")
    title.paragraph_format.space_before = Pt(105)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.add_run("Smart Parking System")
    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run(
        "An IoT Architecture for Occupancy Monitoring, Allocation and Short-Horizon Forecasting"
    )
    run.bold = True
    run.font.size = Pt(12)
    authors = document.add_paragraph()
    authors.alignment = WD_ALIGN_PARAGRAPH.CENTER
    authors.add_run(
        "Akil · 25BCE2777\nJayaprakash V · 25BCE2766\nInstitution: VIT Vellore (vit.ac.in)\n"
        "Course: Embedded System Architecture\nFaculty / guide: Vivek Rajpoot\nUpdated project report · 31 October 2026"
    )
    authors.paragraph_format.space_before = Pt(28)
    document.add_page_break()

    _heading(document, "Abstract")
    abstract = (
        "Parking guidance needs current availability, vehicle records, and a clear rule for assigning spaces. "
        "This report describes a five-space prototype built around an ESP32, RFID access, a FastAPI service, SQLite, and a "
        "dashboard. A space becomes occupied after the server confirms an RFID entry and becomes free after a confirmed exit. "
        "Forecasting runs on the host computer in the current design. The synthetic dataset contains 4,032 five-minute observations and 27 features. LSTM, GRU, "
        "and Transformer regressors share a 12-step lookback, a one-step horizon, a chronological 70/15/15 split, and "
        "training-only scaling. On the synthetic test partition, GRU records MAE 0.098055 and RMSE 0.117862; persistence "
        "records 0.120875 and 0.169173, respectively. GA, PSO, ACO, and NSGA-II were evaluated with first-available and "
        "exhaustive references across "
        f"on {optimizer_summary['scenario_count']} SUMO-observed states, {optimizer_summary['repeated_seeds_per_scenario']} repeats, and "
        f"{optimizer_summary['candidate_capacity']:,} bays. NSGA-II mean cost was "
        f"{float(optimizer_metrics['NSGA-II']['mean_cost']):.6f}, with mean optimality gap "
        f"{float(optimizer_metrics['NSGA-II']['mean_optimality_gap']):.6f}; exhaustive search is the exact one-slot reference. "
        "SUMO results do not represent field performance. Software checks cover API lifecycle, failures, allocation, and inference. "
        "Controller firmware was compiled, flashed, and hash-verified. In two post-rewire tabletop trials, the reader detected "
        "both scans and the API accepted both transactions (HTTP 200). Entry and exit response times were 1,431 ms and "
        "1,220 ms. Server status showed S1 occupied and then free. Physical LED output, servo travel, current draw, and Wi-Fi "
        "recovery were not measured. The prototype and its synthetic data do not establish independent real-lot performance in the field. Larger trials and measured occupancy data are "
        "needed before deployment performance can be assessed independently."
    )
    _paragraph(document, abstract)
    document.paragraphs[-1].paragraph_format.line_spacing = 1.15
    document.paragraphs[-1].paragraph_format.space_after = Pt(12)
    _paragraph(
        document,
        "Keywords: smart parking, Internet of Things, RFID, allocation optimization, occupancy forecasting, LSTM, GRU, Transformer",
    )
    document.add_page_break()

    _heading(document, "1. Introduction")
    _paragraph(
        document,
        "Finding a parking space involves several linked decisions. Drivers need current availability, operators need a dependable arrival and departure record, and the system needs a rule for choosing among free spaces. Recent reviews identify data quality, forecast horizon, sensing method, and transfer between sites as recurring evaluation concerns [1], [2].",
    )
    _paragraph(
        document,
        "The design assigns local input/output tasks to an ESP32 and sends parking operations to a host computer. The controller reads an RFID tag and calls the vehicle-lifecycle API. FastAPI manages session records, slot allocation, forecasts, and dashboard data, while TensorFlow/Keras runs the forecasting models on the host. The ESP32 does not run neural inference.",
    )
    _paragraph(
        document,
        "This work contributes four connected pieces: an idempotent vehicle API with a shared allocation objective; a privacy-safe synthetic time series for comparing neural forecasts; a GA, PSO, ACO, and NSGA-II benchmark replayed on parking states observed during an executed SUMO/TraCI run, with first-available and exact references; and controller firmware that keeps the gate closed unless the server confirms an allocation. In the post-rewire tabletop trial, both RFID scans led to successful entry and exit transactions. That evidence shows the workflow operating, but the two trials are too few to characterize reliability. Physical outputs that were not directly observed are reported separately.",
    )
    _paragraph(
        document,
        "The Arduino framework gives the ESP32 a straightforward way to poll the RFID reader and control local outputs. Training and running the neural regressors requires more memory and processing capacity, so those tasks remain on the host computer. The split keeps device behavior bounded and leaves forecasting with the server.",
    )

    _heading(document, "2. Literature Survey")
    _paragraph(
        document,
        "Recent parking studies address occupancy forecasts, networked access, and space allocation. Table 1 summarizes eight studies published from 2023 to 2026 and relates their methods to this project. Together, they motivate two focused evaluations here: an integrated five-space physical prototype and a reproducible allocation comparison across the 2,376 modeled garage bays, alongside prediction experiments using synthetic time-series data.",
    )
    literature = [
        [
            "Channamallu et al. [1]",
            "2023 · Transportation Research Procedia",
            "Reviews 108 studies on occupancy prediction, including statistical, recurrent and hybrid approaches.",
            "Synthesizes modeling families but does not validate this project's five-slot integration or synthetic test set.",
        ],
        [
            "Bilotta et al. [2]",
            "2023 · IEEE Access",
            "Uses convolutional bidirectional LSTMs and feature-relevance analysis for free-slot forecasting from real garages.",
            "Provides a real-data comparator; its garage observations do not establish generalization of the synthetic project data.",
        ],
        [
            "Zhang et al. [3]",
            "2024 · ISPRS International Journal of Geo-Information",
            "Compares TCN and LSTM and proposes MAT-LSTM for parking-space availability.",
            "Uses real and synthetic datasets; the present evaluation uses its own synthetic generator and does not claim cross-site validation.",
        ],
        [
            "Enríquez et al. [4]",
            "2024 · Applied System Innovation",
            "Evaluates parking-flow prediction and fog/cloud response through a simulated deployment setup.",
            "Separates model and network timing; this report likewise distinguishes server inference from physical controller measurements.",
        ],
        [
            "Kuang et al. [6]",
            "2025 · Advanced Engineering Informatics",
            "Meta-learning model fuses spatial relationships, temporal history and weather across 58 parking lots.",
            "Addresses regional heterogeneity; this five-slot implementation has no cross-lot graph or measured weather data.",
        ],
        [
            "Kaltenbrunner et al. [7]",
            "2025 · EPJ Data Science",
            "Fits an explainable aggregate occupancy model to eight real park-and-ride facilities.",
            "Shows a compact real-data alternative to deep models; the current neural comparison is limited to synthetic data.",
        ],
        [
            "Vakrinou et al. [9]",
            "2026 · International Journal of Transportation Science and Technology",
            "Compares LSTM-attention and Transformer models for short- and long-term prediction at multiple Athens facilities.",
            "Finds horizon-dependent model strengths; this project reports only a one-step five-minute target.",
        ],
        [
            "Ostadi et al. [10]",
            "2026 · Datenbank-Spektrum",
            "Evaluates horizon-aware blended forecasting with sensor data from two urban parking facilities.",
            "Highlights that one predictor may not lead at every horizon; this project compares models at one shared horizon.",
        ],
    ]
    _add_table_caption(document, "Table 1. Related studies and their relevance to this project")
    _add_table(
        document,
        ["Study", "Venue", "Method / reported contribution", "Relevance and limitation"],
        literature,
        font_size=7,
    )
    _paragraph(
        document,
        "Reported forecasting results depend on the horizon, input features, and whether the data comes from an operating facility [2]–[7], [9], [10]. Other IoT studies combine classification or prediction with optimization, but use different targets and objectives [5], [8]. This report addresses a narrower engineering question: can the models and allocation policies be compared on shared inputs while keeping software results distinct from the small hardware trial? The recurrent and self-attention methods used here build on [11]–[13].",
    )
    _paragraph(
        document,
        "The reviewed work ranges from city-scale forecasts to specific allocation formulations. This project pairs an inspectable five-space physical prototype with a six-level, 2,376-bay simulated garage. The controlled allocation comparison evaluates each heuristic and NSGA-II against exhaustive enumeration over all 2,376 modeled candidates. The physical prototype remains five spaces; the larger garage and its candidate objectives are simulated and do not validate real facility demand or traffic.",
    )

    _heading(document, "3. Problem Statement and Objectives")
    _paragraph(
        document,
        "The system must maintain a consistent record of the five configured spaces, associate each entry and exit with an idempotent operation, and assign only a free space. It exposes current status and a short-horizon forecast through the API and dashboard. A space counts as occupied while its RFID vehicle session is active; the forecast is a regression estimate based on aggregated server history.",
    )
    _add_table_caption(document, "Table 2. Objectives, completion status, and available evidence")
    _add_table(
        document,
        ["Objective", "Status and evidence"],
        [
            [
                "Identify configured-slot occupancy",
                "Implemented: server-confirmed RFID entry and exit update slot occupancy transactionally in SQLite.",
            ],
            [
                "RFID entry/exit",
                "Implemented end-to-end; the latest tabletop trial recorded 2/2 tag reads and 2/2 HTTP 200 entry/exit transactions. Two trials do not establish reliability.",
            ],
            [
                "Compare GA, PSO, ACO, and NSGA-II allocation",
                f"Complete: {optimizer_summary['scenario_count']} SUMO-observed allocation states × {optimizer_summary['repeated_seeds_per_scenario']} optimizer repeats, {optimizer_summary['candidate_capacity']:,} candidate bays, common objective, first-available and exhaustive references.",
            ],
            [
                "Forecast next-interval occupancy",
                "Complete on deterministic synthetic data using LSTM, GRU, Transformer and persistence baseline.",
            ],
            [
                "Dashboard visibility",
                "Dashboard and APIs are implemented; an actual browser capture is included. The physical RFID rig has five sensor spaces; the current dashboard also tracks the 2,376-bay garage emulation and displays live optimizer comparisons.",
            ],
            [
                "Low-cost hardware integration",
                "Photographs document the tabletop ESP32/RC522/breadboard/LED assembly. Serial logs document two RFID transactions; visual LED output and physical servo motion remain unverified.",
            ],
        ],
    )

    _heading(document, "4. System Architecture")
    _paragraph(
        document,
        "The backend coordinates each parking transaction. It writes the RFID session and slot assignment together, and the controller opens the demonstration gate only after it confirms the committed result. SQLite stores the authoritative state. The dashboard reads that same state through backend routes rather than querying the controller directly.",
    )
    _add_figure(
        document,
        figures,
        "system_block_diagram.png",
        "Figure 1(a). RFID transaction data flow, allocation, forecasting and persistence run on the server.",
    )
    _add_figure(
        document,
        figures,
        "parking_transaction_flow.png",
        "Figure 1(b). RFID transaction and allocation algorithm, including fail-closed error handling.",
    )
    _add_figure(
        document,
        figures,
        "parking_session_state.png",
        "Figure 1(c). Vehicle-session state diagram; timeout recovery reuses the persisted idempotency key.",
    )
    _paragraph(
        document,
        "Figures 1(a)–1(c) show the embedded hardware and software data flow, RFID request algorithm, and vehicle-session state transitions. Controller flow: RC522 UID → GET /api/parking/status → POST /api/vehicle/entry or /api/vehicle/exit with a persisted idempotency key → response and subsequent status validation → OLED/LED update and one gate cycle. A timeout preserves the pending key and leaves the gate closed until confirmation.",
    )
    _paragraph(
        document,
        "Forecast flow uses the same PreparedDataset contract for each model. The runtime predictor loads compatible, hash-checked model artifacts and uses a deterministic fallback when unavailable. Allocation uses configured weights and excludes occupied candidates. The optimizer benchmark captures the actual allocation request at each SUMO/TraCI parking admission, including all 2,376 candidate bays, their live occupancy, zone congestion, configured distance values, and identity-based fairness values. Each algorithm is replayed on the same captured request, and exhaustive search computes the exact single-slot reference for that observed state. Full candidate snapshots are preserved in the submission evidence.",
    )
    _paragraph(
        document,
        "The backend exposes separate routes for vehicle entry/exit, parking status, allocation benchmarks, forecasts, and dashboard data. The database is the authoritative state shared by those services. A slot is occupied while its RFID vehicle session is active and becomes free after a confirmed exit.",
    )

    _heading(document, "5. Hardware Design")
    _paragraph(
        document,
        "The tabletop prototype uses an ESP32 DevKit, an RC522 reader, a solderless breadboard, indicator LEDs, and jumper wires. The firmware assigns RC522 SS to GPIO 5 and RST to GPIO 4; SPI uses GPIO 18/19/23, the OLED uses GPIO 21/22, the five LEDs use GPIO 25/26/27/32/33, and the demonstration servo signal uses GPIO 14. Figures 2 and 3 show the documented wiring. Photographs cannot establish concealed pin continuity, supply voltage, or resistor values.",
    )
    _add_figure(
        document,
        figures,
        "circuit_diagram.png",
        "Figure 2. Proposed electrical wiring with separate servo power rail and a common ground reference.",
    )
    _add_figure(
        document,
        figures,
        "wiring_diagram.png",
        "Figure 3. Proposed signal map for controller peripherals.",
    )
    _add_table_caption(document, "Table 3. Proposed controller pin assignments")
    _add_table(
        document,
        ["Component", "Signal", "ESP32 pin", "Voltage", "Connection note"],
        [
            ["RC522", "SCK / MISO / MOSI", "18 / 19 / 23", "3.3 V logic", "VSPI; dedicated bus"],
            ["RC522", "SS / RST", "5 / 4", "3.3 V logic", "Matches the current firmware pin definitions"],
            [
                "OLED",
                "SDA / SCL",
                "21 / 22",
                "3.3 V logic",
                "Use compatible pull-ups; I²C address 0x3C",
            ],
            [
                "Slot LEDs 1–5",
                "Anodes via 330 Ω",
                "25, 26, 27, 32, 33",
                "3.3 V outputs",
                "Each LED has its own resistor; cathodes to GND",
            ],
            [
                "SG90",
                "PWM signal",
                "14",
                "3.3 V signal",
                "Servo +5 V from a separate regulated supply; common GND",
            ],
        ],
        font_size=8,
    )
    _paragraph(
        document,
        "The RC522 uses the firmware's SPI pins, and the OLED uses its I²C pins. Each of the five active-high LED outputs has its own series resistor. GPIO and boot-strapping constraints are documented in the ESP32 datasheet [18]. Table 3 follows the firmware pin definitions; the photographs do not independently verify each connection.",
    )
    _paragraph(
        document,
        "Power the controller through USB and supply 3.3 V logic to the RC522 and OLED. Use a separately regulated 5 V supply for the servo, with its ground connected to the controller ground; do not connect the servo's positive supply to the controller logic rail. Fit a 330 Ω resistor in series with each LED. Servo startup or stall current can exceed the capacity of a GPIO or development-board regulator, so size the external supply for the specific SG90 variant. Keep the lightweight model supervised. A hobby servo is not a safety-rated barrier actuator, and a power loss can leave its arm in place.",
    )
    _paragraph(
        document,
        "The bill of materials, per-signal pin map, wiring sequence, and troubleshooting guide are in docs/hardware/. The 26 October controller log records two RFID transactions, the change in S1 status, and LED and gate commands. LED physical output was not visually verified; servo movement was not independently observed, and supply current was not measured.",
    )

    _heading(document, "6. Methodology: Software and Machine-Learning Design")
    _add_table_caption(document, "Table 4. Software components and responsibilities")
    _add_table(
        document,
        ["Technology", "Role in implementation"],
        [
            [
                "Python 3.14.8",
                "Backend, data preparation, benchmarking, report tooling on the measured host.",
            ],
            [
                "FastAPI and SQLite",
                "HTTP contracts, RFID lifecycle state, session-derived slot occupancy, prediction/optimizer metrics and dashboard data.",
            ],
            [
                "NumPy and Pillow",
                "Feature construction and server-side forecasting model training and inference.",
            ],
            [
                "TensorFlow/Keras",
                "Server-side LSTM, GRU, and temporal Transformer regression models.",
            ],
            [
                "Arduino framework + PlatformIO",
                "ESP32 controller build; device attachment is reported separately from compilation.",
            ],
            [
                "Graphviz and python-docx",
                "Editable architecture diagrams and generated single-column DOCX/PDF submission.",
            ],
        ],
    )

    _heading(document, "6.1 Dataset and Preprocessing", 2)
    _paragraph(
        document,
        f"The dataset is synthetic and deterministic. It contains {metadata['records']['feature_timeline']:,} five-minute intervals over 14 days, {metadata['feature_count']} input features, and {metadata['records']['raw_observations']:,} privacy-safe source observations. The timeline covers five configured spaces from {metadata['time_coverage_utc']['start']} through {metadata['time_coverage_utc']['end']} and uses seed {metadata['random_seed']}. Inputs include occupancy and its change, rolling averages, time and weekday cycles, simulated weather and event indicators, vehicle counts, active sessions, aggregated vehicle attributes, and allocation context. Each example predicts the occupancy ratio one interval ahead.",
    )
    _paragraph(
        document,
        "For each prediction, the preprocessor supplies the preceding 12 intervals (60 minutes) and forecasts the next one. It splits the timeline in chronological order into 70% training, 15% validation, and 15% test before building sequences; the resulting counts are 2,810, 592, and 594. Feature means and scales are fitted on training data only. All three neural models receive the same PreparedDataset, and no RFID UID enters the model. This setup keeps later observations out of earlier inputs and prevents test data from influencing scaling.",
    )
    _paragraph(
        document,
        "The feature builder forward-fills eligible short gaps. Longer gaps remain missing, and examples containing them are excluded from training. Bounded, cyclic, and one-hot features follow the existing input contract; all models share the same continuous-feature scaler. Because the final interval has no following target, it is not used as a labeled example. This dataset supports repeatable software comparisons, but it cannot measure real parking demand, weather effects, or performance at another site.",
    )
    _paragraph(
        document,
        "Dataset files and metadata are in review_outputs/2026-10-15/dataset. A public, version-pinned ZIP download is available from GitHub: ",
    )
    _add_hyperlink(document.paragraphs[-1], "download simulated dataset", DATASET_PUBLIC_URL)

    _heading(document, "6.2 Forecasting Architectures", 2)
    _add_figure(
        document,
        figures,
        "ml_architecture.png",
        "Figure 4. Implemented neural architectures; each receives the same scaled 12×27 sequence and predicts a bounded scalar.",
    )
    _paragraph(
        document,
        "The LSTM and GRU each use one 16-unit recurrent layer and a sigmoid output that predicts one occupancy value. For the Transformer, each 27-feature interval is projected to width 16 and combined with a learned positional embedding. Two-head self-attention (key dimension 8) feeds a residual connection and layer normalization, followed by 32- and 16-unit feed-forward layers, a second residual connection, global average pooling, and a sigmoid output. All models use mean-squared-error loss and Adam with a 0.001 learning rate. Training is capped at 12 epochs, uses batches of 32, and stops early after three validation epochs without improvement. TensorFlow/Keras deterministic operations are enabled where supported. Since occupancy is continuous, classification accuracy, F1, ROC curves, and confusion matrices do not apply.",
    )
    _paragraph(
        document,
        "Each Keras artifact is content-addressed and accompanied by a manifest recording feature order, split identity, scaler values, configuration, software versions, and SHA-256 hash. The server loads these artifacts for inference. TensorFlow Lite conversion, quantization, and pruning are outside the current design because the ESP32 does not run the neural models.",
    )

    _heading(document, "6.3 Allocation Objective", 2)
    _paragraph(
        document,
        "Each free candidate slot i receives the normalized cost J(i) = 0.35 dᵢ + 0.30 cᵢ + 0.20 wᵢ + 0.15 fᵢ. The terms represent distance, congestion, waiting, and fairness from the live allocation request. Occupied slots are removed before selection. For the benchmark, the application captures the request at each SUMO/TraCI parking admission and replays first-available, exhaustive search (the exact solution for this one-slot choice), GA, PSO, ACO, and NSGA-II against the same observed state and weights. For a heuristic choice x, its gap from the exact result is J(x) − minᵢ J(i), nonnegative apart from floating-point tolerance. The optimizer interface does not provide valid per-iteration histories, so convergence curves are not reported [14], [15].",
    )
    _paragraph(document, "The controller-side request sequence is:")
    code = document.add_paragraph()
    code.style = "No Spacing"
    run = code.add_run(
        "read and normalize UID in RAM\nif a saved operation exists: retry its same idempotency key\nelse: inspect current server status; choose entry or exit\npersist operation + key in NVS before HTTP POST\nvalidate response identity and gate_action; re-read status\nif committed status matches: persist gate_done before one gate cycle\non timeout/conflict/malformed reply: keep gate closed"
    )
    run.font.name = "Consolas"
    run.font.size = Pt(9)

    _heading(document, "7. Implementation Details")
    _paragraph(
        document,
        "The vehicle API accepts the JSON fields rfid_uid and idempotency_key. Before sending a request, the controller builds a key from its chip identifier and a sequence number stored in non-volatile storage, then saves the key with the pending operation. After a restart, it resends that same key and payload, allowing the server to return the result of an operation it has already committed. The firmware does not print tag identifiers to Serial. The API currently lacks device authentication and TLS, so the controller should only connect through a trusted private network.",
    )
    _paragraph(
        document,
        "The server and benchmark use the same weighted_cost function. If no space is free, the API returns HTTP 409 and the controller keeps the gate closed. Before opening it after entry, the firmware checks the returned tag, slot identifier and name, gate action, and current parking status. After exit, it confirms that the session is no longer active. The five LEDs show the accepted server state: on for occupied, off for free, and blinking together when status is unknown. The OLED reports startup, network state, scans, assignments, full-lot responses, completion, and errors. A timed state machine closes the demonstration gate after its configured interval.",
    )
    _paragraph(
        document,
        "A slot changes to occupied only when the server commits the RFID session and allocation. On exit, the same session is closed and its assigned slot becomes free. Both the LEDs and dashboard use the resulting server status, keeping their view of occupancy aligned.",
    )

    _heading(document, "8. Experimental Setup")
    _paragraph(
        document,
        "The forecast comparison uses the generated synthetic timeline and its chronological split. Each neural model shares the same preprocessing and test partition; the persistence baseline carries the latest observed occupancy forward by one interval. Server inference latency is the median warm-run prediction time divided by the number of examples. The run used TensorFlow 2.22.0-rc0, Keras 3.16.0.dev2026101404, and Python 3.14.8 on Linux x86_64 with an Intel Core i7-14650HX. No accelerator or ESP32 inference time is included.",
    )
    _paragraph(
        document,
        f"The allocation benchmark covers {optimizer_summary['scenario_count']} SUMO-observed parking admissions, {optimizer_summary['repeated_seeds_per_scenario']} optimizer seeds per observed state, and {optimizer_summary['iterations']} iterations for each heuristic. It uses the configured weights {json.dumps(optimizer_summary['weights'], sort_keys=True)}. SUMO {optimizer_summary['sumo_version']} ran with seed {optimizer_summary['sumo_seed']} and {optimizer_summary['sumo_step_length_seconds']:.2f}-second steps; configuration, network, and route SHA-256 hashes are included in the evidence. Candidate inputs are preserved in `evidence/sumo_observed_scenarios.jsonl`; results are replayed on each captured live-allocation request. Runtime is measured with a monotonic clock. Rejections at full capacity are counted separately. These results measure this modeled SUMO traffic run, not a real facility or measured queue delay.",
    )
    _paragraph(
        document,
        "The host has an Intel Core i7-14650HX, 24 CPUs online, and 15 GiB RAM. Model and allocation runtimes were measured in software on this machine and may vary with system load. For the hardware trial, an ESP32 DevKit connected to the local API over Wi-Fi. The results below come from the controller's timestamped serial capture and the API access log dated 26 October 2026.",
    )

    _heading(document, "9. Results and Discussion")
    _heading(document, "9.1 Prediction Results", 2)
    _paragraph(
        document,
        "Table 5 reports the persistence baseline and three neural regressors on the same chronological test windows. GRU has the lowest MAE and RMSE in this run. The ranking applies to one synthetic dataset and seed; it does not establish that GRU will perform best on other data or at a real parking site. Inference times are from the server CPU, and model sizes refer to the serialized Keras files.",
    )
    _add_model_results_table(document, repository_root)
    _add_figure(
        document,
        figures,
        "actual_vs_predicted.png",
        "Figure 5. Test-window actual versus predicted occupancy ratio from the executed model comparison.",
    )
    _add_figure(
        document,
        figures,
        "prediction_error_distribution.png",
        "Figure 6. Prediction error distribution; errors are regression residuals, not class labels.",
    )
    for model_name, filename in (
        ("LSTM", "lstm_loss.png"),
        ("GRU", "gru_loss.png"),
        ("Transformer", "transformer_loss.png"),
    ):
        _add_figure(
            document,
            figures,
            filename,
            f"Figure {7 + (0 if model_name == 'LSTM' else 1 if model_name == 'GRU' else 2)}. {model_name} training and validation loss for the fitted run.",
        )
    _add_figure(
        document,
        figures,
        "mae_comparison.png",
        "Figure 10. Measured model MAE comparison on the shared chronological test partition.",
    )
    _add_figure(
        document,
        figures,
        "rmse_comparison.png",
        "Figure 11. Measured model RMSE comparison on the shared chronological test partition.",
    )
    _add_figure(
        document,
        figures,
        "latency_comparison.png",
        "Figure 12. Measured per-example inference latency on the server host.",
    )
    _paragraph(
        document,
        f"On the shared synthetic test set, GRU lowers MAE by {(1 - float(models['gru']['mae']) / float(models['persistence_baseline']['mae'])) * 100:.1f}% and RMSE by {(1 - float(models['gru']['rmse']) / float(models['persistence_baseline']['rmse'])) * 100:.1f}% relative to persistence. LSTM is second on both measures. The Transformer also improves on persistence, but not as much as the recurrent models in this run. Some of the 27 inputs, including simulated calendar, weather, and event context, may reflect patterns specific to the generator. Measured occupancy data, evaluation at another site, and independently seeded datasets are needed before making deployment claims.",
    )

    _heading(document, "9.2 Allocation Results", 2)
    _paragraph(
        document,
        f"Table 6 aggregates {optimizer_summary['scenario_count']} parking allocation states observed during the executed SUMO run and {optimizer_summary['repeated_seeds_per_scenario']} optimizer-seed repetitions per state across {optimizer_summary['candidate_capacity']:,} candidate bays. Each policy rejected {optimizer_summary['full_capacity_rejections']} full-capacity attempts. Exhaustive search gives the exact minimum for this one-slot decision, with mean cost {float(optimizer_metrics['exhaustive_optimum']['mean_cost']):.6f}. GA mean cost was {float(optimizer_metrics['GA']['mean_cost']):.6f}; NSGA-II mean cost was {float(optimizer_metrics['NSGA-II']['mean_cost']):.6f}, with a mean optimality gap of {float(optimizer_metrics['NSGA-II']['mean_optimality_gap']):.6f} and median runtime {float(optimizer_metrics['NSGA-II']['median_runtime_ms']):.3f} ms. Cost and runtime are measured from these captured modeled states and Python optimizer executions; they do not establish real-facility throughput or field performance.",
    )
    _add_optimizer_results_table(document, repository_root)
    _add_figure(
        document,
        figures,
        "average_allocation_cost.png",
        "Figure 13. Mean allocation objective cost across all six policies, including NSGA-II, at 2,376 modeled bays.",
    )
    _add_figure(
        document,
        figures,
        "execution_time.png",
        "Figure 14. Software execution-time comparison; logarithmic scaling is labeled in the figure.",
    )
    _add_figure(
        document,
        figures,
        "cost_by_occupancy.png",
        "Figure 15. Objective cost by simulated occupancy category.",
    )
    _add_figure(
        document,
        figures,
        "optimality_gap_distribution.png",
        "Figure 16. Per-run nonnegative gap from exact enumeration.",
    )
    _add_figure(
        document,
        figures,
        "objective_components.png",
        "Figure 17. Mean weighted objective components among successful allocations.",
    )
    occupancy_levels = ("empty", "light", "moderate", "heavy", "near_full", "full")
    observed_levels = [
        level for level in occupancy_levels if optimizer_summary["occupancy_levels"].get(level, 0)
    ]
    occupancy_rows = []
    category_run_counts = []
    for level in observed_levels:
        category_run_counts.append(
            f"{level}: {optimizer_summary['by_occupancy'].get(f'GA:{level}', {}).get('runs', 0)} runs per policy"
        )
        occupancy_rows.append(
            [level]
            + [
                (
                    f"{optimizer_summary['by_occupancy'][f'{name}:{level}']['mean_cost']:.6f}"
                    if f"{name}:{level}" in optimizer_summary["by_occupancy"]
                    else "No successful assignment"
                )
                for name in ("first_available", "exhaustive_optimum", "GA", "PSO", "ACO", "NSGA-II")
            ]
        )
    _add_table_caption(document, "Table 7. Mean objective cost by SUMO-observed occupancy category")
    _add_table(
        document,
        ["Occupancy category", "First available", "Exact", "GA", "PSO", "ACO", "NSGA-II"],
        occupancy_rows,
        font_size=7,
    )
    _paragraph(
        document,
        f"Table 7 includes only occupancy categories observed during the SUMO run ({'; '.join(category_run_counts)}). No results are generated for unobserved occupancy levels. Full-capacity rejections ({optimizer_summary['full_capacity_rejections']}) are reported separately. Runtime measures the Python algorithms on this host; it does not represent measured facility throughput or real queue waiting time.",
    )

    _heading(document, "9.3 Hardware and integration test status", 2)
    if hardware_validation:
        latest_live = hardware_validation.get("latest_live_validation", {})
        heap_metric = (
            hardware_summary.get("metrics", {}).get("free_heap_bytes", {})
            if hardware_summary
            else {}
        )
        heap_result = (
            f" Across {heap_metric['count']} serial events, free heap averaged "
            f"{heap_metric['mean']:.0f} bytes (median {heap_metric['median']:.0f}, "
            f"standard deviation {heap_metric['standard_deviation']:.0f}, "
            f"p95 {heap_metric['p95']:.0f})."
            if heap_metric.get("status") == "MEASURED"
            else " Controller free-heap measurement is NOT TESTED."
        )
        rfid_trial_text = (
            f"The post-rewire trial detected {rfid_metric['successes']}/"
            f"{rfid_metric['trials']} test scans; both entry and exit transactions returned HTTP 200. "
            if rfid_metric.get("status") == "MEASURED"
            and api_metric.get("status") == "MEASURED"
            else "No post-rewire RFID transaction trial is recorded. "
        )
        entry_latency_text = (
            f"Entry transaction latency: {entry_metric['mean']:.0f} ms. "
            if entry_metric.get("status") == "MEASURED"
            else "Entry transaction latency: NOT TESTED. "
        )
        exit_latency_text = (
            f"Exit transaction latency: {exit_metric['mean']:.0f} ms. "
            if exit_metric.get("status") == "MEASURED"
            else "Exit transaction latency: NOT TESTED. "
        )
        gate_timing_text = (
            f"Four gate-command timestamps averaged "
            f"{gate_metric['mean']:.0f} ms (median {gate_metric['median']:.0f}, "
            f"p95 {gate_metric['p95']:.0f}); these are command timestamps, not measured "
            "servo travel. "
            if gate_metric.get("status") == "MEASURED"
            else "Servo command timing is NOT TESTED. "
        )
        slot_observation = (
            "Server status showed S1 changed to occupied at entry and free at exit."
            if latest_live.get("entry_slot_observation") and latest_live.get("exit_slot_observation")
            else ""
        )
        hardware_status_paragraph = (
            f"PlatformIO compiled both firmware targets. The controller was identified as "
            f"{hardware_validation.get('controller_chip', 'an ESP32')}; esptool verified the hash "
            f"of the flashed firmware binary, and an earlier full flash backup is retained. "
            f"During the logged run, serial telemetry recorded "
            f"{hardware_validation.get('controller_boot_events', 0)} boots and "
            f"{hardware_validation.get('wifi_connected_events', 0)} Wi-Fi connections. The API log "
            f"showed {hardware_validation.get('health_200_responses_after_latest_boot', 0)} successful "
            f"health checks and {hardware_validation.get('authenticated_status_200_responses_after_latest_boot', 0)} "
            f"authenticated parking-status responses after the latest boot. {rfid_trial_text}"
            f"{entry_latency_text}{exit_latency_text}{slot_observation} {heap_result} {gate_timing_text}"
            f"The LEDs were not visually checked. Current draw, Wi-Fi recovery time, and physical "
            f"servo movement remain NOT TESTED. Historical isolated RC522 VersionReg probes returned "
            f"0xFF and 0x00; these were not repeatability trials and are reported separately from "
            f"the later successful RFID transaction observations."
        )
        controller_build_result = (
            f"PASS: latest controller firmware was flashed to "
            f"{hardware_validation.get('controller_chip', 'ESP32')}; esptool binary hash verification passed. "
            "An earlier full flash readback is retained."
        )
        controller_network_result = (
            f"PASS: {api_metric.get('successes', 0)}/{api_metric.get('trials', 0)} "
            "post-rewire vehicle transactions returned HTTP 200 after slot-status synchronization."
        )
        reader_result = (
            f"PASS: {rfid_metric.get('successes', 0)}/{rfid_metric.get('trials', 0)} "
            "post-rewire RFID test scans succeeded; entry and exit both "
            "completed with HTTP 200. This two-trial result is not a reliability estimate."
        )

    else:
        hardware_status_paragraph = (
            "PlatformIO compiled the controller firmware. No physical controller validation evidence is available. RFID reads, display, LEDs, servo, current, and hardware latency remain NOT TESTED."
        )
        controller_build_result = "PASS: PlatformIO compilation only; no physical flash evidence."
        controller_network_result = "NOT TESTED: no physical controller network evidence."
        reader_result = "NOT TESTED physically; no reader probe or card read was recorded."

    _paragraph(
        document,
        hardware_status_paragraph,
    )
    _add_table_caption(document, "Table 8. Verification evidence and physical test status")
    _add_table(
        document,
        ["Check", "Observed result"],
        [
            [
                "Controller firmware build",
                controller_build_result,
            ],
            [
                "USB serial/network reachability",
                controller_network_result,
            ],
            [
                "RC522 reader and card scan",
                reader_result,
            ],
            [
                "OLED, LEDs, servo",
                "The firmware logged five LED states and commanded S1 on at entry and off at exit. "
                "LED physical output was not visually verified. Servo values are command timing; "
                "physical movement was not independently measured.",
            ],
            [
                "ESP32 inference latency / memory",
                "Not applicable to the current server-side TensorFlow design; not measured on device.",
            ],
        ],
    )
    free_heap = hardware_metrics.get("free_heap_bytes", {})
    measured_rows = [
        [
            "RFID reads",
            f"{rfid_metric.get('successes', 0)}/{rfid_metric.get('trials', 0)}",
            "Two operator-confirmed scans; descriptive only, not a reliability estimate.",
        ],
        [
            "Entry / exit API transactions",
            f"{api_metric.get('successes', 0)}/{api_metric.get('trials', 0)}",
            "Both returned HTTP 200 after controller status synchronization.",
        ],
        [
            "Entry response latency",
            f"{entry_metric.get('mean', 'NOT TESTED')} ms (n={entry_metric.get('count', 0)})",
            "One measured transaction; no population latency claim.",
        ],
        [
            "Exit response latency",
            f"{exit_metric.get('mean', 'NOT TESTED')} ms (n={exit_metric.get('count', 0)})",
            "One measured transaction; no population latency claim.",
        ],
        [
            "Free heap telemetry",
            (
                f"mean {free_heap['mean']:.0f}; median {free_heap['median']:.0f}; "
                f"p95 {free_heap['p95']:.0f} bytes (n={free_heap['count']})"
                if free_heap.get("status") == "MEASURED"
                else "NOT TESTED"
            ),
            "ESP32 serial telemetry during the logged run.",
        ],
        [
            "Gate command delay",
            (
                f"mean {gate_metric['mean']:.0f}; median {gate_metric['median']:.0f}; "
                f"p95 {gate_metric['p95']:.0f} ms (n={gate_metric['count']})"
                if gate_metric.get("status") == "MEASURED"
                else "NOT TESTED"
            ),
            "Firmware command timestamps; servo arm travel was not measured.",
        ],
        ["Wi-Fi recovery / current / visual LED correctness", "NOT TESTED", "No controlled outage or electrical measurement was captured."],
    ]
    _add_table_caption(document, "Table 9. Recorded physical measurements and untested quantities")
    _add_table(document, ["Metric", "Observed result", "Interpretation"], measured_rows, font_size=8)
    _paragraph(
        document,
        "Both recorded RFID scans were accepted, and both API transactions succeeded. Entry response time was 1,431 ms; exit response time was 1,220 ms, with one observation in each direction. The 211 ms difference is descriptive, not a comparison of typical performance. Table 9 also reports gate-command timestamps and free-heap samples. A command timestamp does not measure how quickly the servo arm moves. Current draw, visible LED operation, and Wi-Fi recovery were not measured.",
    )
    _add_figure(
        document,
        figures,
        "hardware_timing_comparison.png",
        "Figure 18. Observed entry, exit and gate-command event timing; command latency is not servo travel time.",
    )
    _add_figure(
        document,
        figures,
        "city_district_overview.png",
        "Figure 19. 28 October scene capture of the fictional Parkflow Central district and surrounding city traffic; a modeled setting, not a current Phoenix Marketcity map.",
    )
    _add_figure(
        document,
        figures,
        "six_floor_garage.png",
        "Figure 20. 28 October scene capture of the assembled six-deck garage, including two below-ground levels, four above-ground levels, connecting ramps, and animated traffic.",
    )
    _add_figure(
        document,
        figures,
        "first_person_route.png",
        "Figure 21. 28 October first-person entrance capture with the assigned bay, floor transition, route distance, and animated route guidance.",
    )
    _add_figure(
        document,
        figures,
        "parking_navigation_map.png",
        "Figure 22. 28 October overhead parking-map capture showing the route, current vehicle position, and destination bay on its floor.",
    )
    _paragraph(
        document,
        "Figures 19–22 are scene captures from 28 October 2026. They document the city, multi-floor garage, first-person driver view, and bay navigation overlay. The screenshots show modeled traffic and geometry; they are interface evidence, not measured traffic outcomes. Tables 8 and 9 report the separate five-space physical-controller evidence. Hardware photographs are omitted.",
    )

    _heading(document, "9.4 Source- and specification-based engineering estimates", 2)
    _paragraph(
        document,
        "Table 10 gives planning estimates for quantities that were not measured. They are engineering assumptions, not hardware measurements or benchmark results. The read-rate and latency ranges assume a close-range tabletop setup on stable local Wi-Fi; component timing and current ranges draw on firmware settings and manufacturer specifications where available. The two recorded scans are functional observations only and do not establish a success rate.",
    )
    _add_table_caption(document, "Table 10. Rough engineering estimates (not measured)")
    _add_table(
        document,
        ["Quantity", "Estimate", "Basis and limitations"],
        [
            [
                "RFID successful reads per close, aligned tap",
                (
                    f"Measured {rfid_metric['successes']}/{rfid_metric['trials']} scans; "
                    "not a reliability estimate"
                    if rfid_metric.get("status") == "MEASURED"
                    else "NOT TESTED"
                ),
                "Two operator-confirmed close-range test taps were detected. The sample is too small to estimate reliability; MFRC522 specifies up to 50 mm depending on antenna tuning, not a read-success guarantee [17].",
            ],
            [
                "API entry/exit transaction success on stable local LAN",
                (
                    f"Measured {api_metric['successes']}/{api_metric['trials']} transactions; "
                    "not a reliability estimate"
                    if api_metric.get("status") == "MEASURED"
                    else "NOT TESTED"
                ),
                "Two post-rewire entry/exit trials returned HTTP 200. This small sample does not estimate long-run availability.",
            ],
            [
                "LED correctness with known slot state",
                "NOT MEASURED; firmware output commands logged",
                "Serial telemetry recorded the five free-slot commands, S1 on at entry, and S1 off at exit. No visual or electrical output sensor was used.",
            ],
            [
                "Entry or exit latency, tag detection to accepted API response",
                (
                    f"Measured entry {entry_metric['mean']:.0f} ms; exit "
                    f"{exit_metric['mean']:.0f} ms (n=1 each)"
                    if entry_metric.get("status") == "MEASURED"
                    and exit_metric.get("status") == "MEASURED"
                    else "NOT TESTED"
                ),
                "Host-timestamped ESP32 serial events; one trial per direction is descriptive only. The 3.5 s HTTP timeout is a failure limit, not expected latency.",
            ],
            [
                "Wi-Fi recovery after AP becomes available",
                "5–15 s (low confidence)",
                "Firmware retries every 5 s; range allows up to about 10 s for association/DHCP after a retry. Poor AP conditions may take longer or fail.",
            ],
            [
                "Servo command delay, RFID detection to authorized GPIO command",
                (
                    "Measured command events: "
                    + ", ".join(
                        f"{value} ms"
                        for value in hardware_validation.get("latest_live_validation", {}).get(
                            "servo_command_delay_ms", []
                        )
                    )
                    if hardware_validation
                    and hardware_validation.get("latest_live_validation", {}).get(
                        "servo_command_delay_ms"
                    )
                    else "NOT TESTED"
                ),
                "Firmware command timestamps include gate-open and gate-close commands; they do not measure servo shaft travel or barrier motion.",
            ],
            [
                "SG90 travel for configured 10°→85° sweep",
                "0.13–0.50 s (very low confidence)",
                "Ideal nominal is 75° × 0.1 s/60° ≈125 ms at 4.8 V; upper range is a load/settling allowance. Exact servo variant is unverified [18].",
            ],
            [
                "Controller free heap",
                (
                    f"Measured mean {hardware_metrics['free_heap_bytes']['mean']:,.0f} bytes "
                    f"(n={hardware_metrics['free_heap_bytes']['count']})"
                    if hardware_metrics.get("free_heap_bytes", {}).get("status") == "MEASURED"
                    else "NOT TESTED"
                ),
                (
                    f"Current serial capture: median {hardware_metrics['free_heap_bytes']['median']:,.0f} bytes, "
                    f"SD {hardware_metrics['free_heap_bytes']['standard_deviation']:,.0f}, "
                    f"p95 {hardware_metrics['free_heap_bytes']['p95']:,.0f}. Measured telemetry, not a future guarantee."
                    if hardware_metrics.get("free_heap_bytes", {}).get("status") == "MEASURED"
                    else ""
                ),
            ],
            [
                "Controller + reader + OLED + LEDs input current, servo excluded",
                "0.15–0.40 A at 5 V (very low confidence)",
                "Budget estimate from ESP32 active Wi-Fi radio draw plus peripherals; regulators, OLED brightness, LED current, and network duty cycle vary [18].",
            ],
            [
                "SG90 servo supply current",
                "0.5–2.0 A (very low confidence)",
                "Manufacturer product page notes this operating-current range; exact unit/load is unknown. Use a separate regulated servo supply, never ESP32 GPIO or 3.3 V [18].",
            ],
        ],
    )

    _heading(document, "9.5 Current full-scale software implementation", 2)
    _paragraph(
        document,
        "This update records the application state on 31 October 2026 and supplements the earlier experimental results in this report. The dashboard presents a six-level parking-garage emulation connected to a surrounding fictional city district and a native SUMO/TraCI road simulation. Its 2,376 bays are all represented in the garage map and occupancy records: 396 per deck, with two below-ground decks and four above-ground decks connected by ramps. The layout uses published Haneda P2 floor guides as a geometric reference; the basement placement, building, and city are emulations, not an exact Phoenix Marketcity or Haneda map. The rendered city adds roads, buildings, planted areas, trees, pedestrians, street lighting, and traffic signals, with animated vehicles, barriers, and ramps. The browser refreshes SUMO vehicle snapshots and the parking event stream, keeping movement and bay occupancy tied to current server state. The five-space RFID rig remains the physical prototype; the larger garage is software-modelled.",
    )
    _paragraph(
        document,
        "The dashboard provides SUMO start, stop, pause, resume, and reset controls and reports the current run state, simulated time, vehicle count, and mean speed. Traffic vehicles that reach the garage approach can enter the parking workflow: each SUMO vehicle ID maps to a stable pseudonymous parking identity across simulation runs, while entry, exit, and rollback operations retain run-specific idempotency keys. The system records a parking session, removes the vehicle from road traffic while parked, then closes the session and rejoins it to traffic on departure. The model caps admission at two arrivals per simulation step and uses a deterministic emulated dwell interval based on the assigned bay and floor; this is a controlled traffic/parking emulation, not a measured arrival rate or throughput result. Separate entry and exit approaches, gate arms, routes, and garage barriers are visible in the model.",
    )
    _paragraph(
        document,
        "Drivers can use the manual vehicle-ID simulator or an RFID/keyboard reader; the connected ESP32 scan and simulated ID feed the same entry/exit lifecycle. Scanning a known active identity selects exit, while an identity with no active session selects entry. An RFID UID is normalized to uppercase and stored as a unique vehicle identity. Each identity may have only one active session; repeat visits create separate records with their own entry and exit times. On entry, the assigned vehicle is animated from the entrance toward its selected bay, with first-person view, floor/route status, distance, and a map waypoint. The same bay appears in live occupancy and can be followed again from the receipt. Exit closes the session and animates departure. Every one of the 2,376 modeled bays has an occupancy record, although only the five RFID spaces are wired to the physical prototype.",
    )
    _paragraph(
        document,
        "The emulated car tariff is ₹50 for the first started hour and ₹40 for each additional started hour, with a ten-minute grace period and a ₹400 cap per 24 hours. Charges are computed per session from its entry and exit timestamps and stored in paise. The tariff is illustrative; it is not presented as the mall's verified official rate. Entry and exit return a session receipt with vehicle identity, bay, timestamps, duration, tariff, and live estimate or final amount. The dashboard displays a QR code that opens the full receipt on a phone. This is a receipt link, not QR-based payment; no payment gateway or settlement is implemented. The same tariff rule applies to every identity, while session duration makes each charge specific to that vehicle's visit.",
    )
    _paragraph(
        document,
        "NSGA-II is integrated into live slot allocation and the optimizer comparison API, configured with population 48, 60 generations, crossover 0.90, and mutation 0.12. It selects a weighted compromise from a non-dominated candidate set. The benchmark compares it with GA, PSO, ACO, first-available, and exhaustive search by replaying requests captured at parking admissions during an executed SUMO/TraCI run across all 2,376 modeled candidates. It records the SUMO version, seed, network and route hashes, simulation times, raw candidate states, and Python optimizer runtimes. The allocation outcomes are actual measurements from this fictional-garage simulator run, not random objective scenarios or physical mall results. Live allocation computes personalized fairness from each normalized vehicle identity's completed sessions: for each candidate bay, it compares that driver's projected mean walking distance after assignment with the equal-weighted mean of each other vehicle's historical mean walking distance across its completed sessions. The absolute difference is the fairness cost, capped to the normalized 0–1 range; lower cost favors assignments that reduce disparity. With no completed peer history, fairness is neutral at zero. Stable SUMO identities let repeat simulated vehicles retain this history across runs. Waiting remains zero because the model has no measured queue-wait estimate. This is a software allocation proxy based on configured walking distances, not a guarantee of equitable outcomes. The tariff remains identity-neutral. The full software test suite passed 249 tests. No new physical RFID, QR-reading, payment-settlement, gate-actuation, or SUMO-throughput trial is claimed.",
    )

    _heading(document, "10. Testing and Demonstration")
    physical_checklist_note = (
        "The post-rewire capture records two RFID reads, two successful HTTP 200 transactions, "
        "S1 occupied at entry and free at exit, and four gate-command timestamps. These two "
        "trials demonstrate the transaction flow; they do not establish reliability. LED output, "
        "servo movement, and current draw were not independently measured. Slot occupancy is "
        "derived from active RFID sessions."
        if hardware_validation
        else "The hardware scenario checklist marks physical behaviors NOT TESTED until "
        "the board-level procedures are performed."
    )
    _paragraph(
        document,
        "Automated software checks cover lifecycle retries and conflicts, full-lot handling, state persistence, prediction fallback and artifact compatibility, and simulated API ordering. The build checklist reports these results separately from firmware compilation and hardware observations. "
        + physical_checklist_note,
    )
    _paragraph(
        document,
        "A host-runtime check copied the review database, selected the saved GRU artifact in the predictor setting, and called GET /api/prediction. The API returned model=gru, fallback_reason=null, and occupancy_ratio=0.136493 for the synthetic timeline. This confirms that the server can load the artifact and return a prediction; it is not a controller measurement.",
    )
    _paragraph(
        document,
        "In a separate software-only run, /health reported five configured spaces, a simulated entry was assigned S1, and the API returned GA, PSO, ACO, and NSGA-II benchmark results for the same scenario. Because the isolated database contained too little history, prediction used the expected deterministic fallback, insufficient_history. These results check software behavior; the simulated tag does not count as a physical RFID read.",
    )
    _paragraph(
        document,
        "To repeat the software demonstration, activate the project environment, run `make test` and `make lint`, and start the API with `make run`. Then run `python -m scripts.run_simulated_demo --base-url http://127.0.0.1:8000 --rfid-uid 04A1B2C3 --idempotency-key final-review-entry-001` and open http://127.0.0.1:8000/dashboard. The experimental report and figures are in `review_outputs/2026-10-15/EXPERIMENTAL_REPORT.md` and `review_outputs/2026-10-15/final_submission/figures/`. Label this as a simulated RFID workflow. Avoid `make review` during the presentation because it retrains the models and regenerates result files.",
    )
    _paragraph(
        document,
        "For the controller demonstration, first confirm GET /health. Scan a dedicated test tag for entry, check the assigned space and controller status, then scan again and confirm that the space is free. Keep fingers clear of the supervised tabletop servo. DEMO_INSTRUCTIONS.md contains the startup, cleanup, and failure-recovery steps.",
    )

    _heading(document, "11. Limitations and Future Work")
    _paragraph(
        document,
        "The main limitations are the synthetic forecasting dataset, optimizer results from one SUMO-generated traffic run, configured rather than site-measured bay distances, zero queue-wait values, a five-space physical RFID rig alongside a modeled 2,376-bay garage, a one-step forecast horizon, patterns specific to the forecast data generator, and two RFID/API trials. The allocation benchmark is actual output from the executed simulator, but it is not a physical mall trial. Firmware logs show LED commands, but the LEDs were not checked visually. Servo travel and power draw were also not measured. Synthetic forecast accuracy cannot establish how the models will perform at an operating site.",
    )
    _paragraph(
        document,
        "The next evaluation should use measured occupancy timelines, test separate days and sites, and repeat the model runs with independent seeds. Hardware work should include more RFID/API trials, direct checks of all five LEDs and servo movement, and measured current and Wi-Fi recovery time. Device requests also need transport authentication before the system is exposed beyond a trusted local network. A vehicle barrier requires a safety-rated actuator, controller, and independent interlocks; the SG90 model is only a tabletop demonstration.",
    )

    _heading(document, "12. Conclusion")
    _paragraph(
        document,
        "This project brings together RFID entry and exit, session-based occupancy, space allocation, server-side forecasting, a browser dashboard, and ESP32 controller firmware. In the synthetic forecast test, GRU had the lowest MAE of the three neural models; for optimizer benchmarking, exhaustive enumeration provided an exact reference for each SUMO-observed allocation state. The tabletop trial completed two entry/exit transactions and recorded the change in S1 status along with API and gate-command timings. The small sample demonstrates that the components can work together, but it does not establish deployment reliability. Physical LED output, servo travel, current draw, and Wi-Fi recovery time still need direct measurement.",
    )

    _heading(document, "References")
    references = [
        "[1] S. S. Channamallu, S. Kermanshachi, J. M. Rosenberger, and A. Pamidimukkala, “Parking occupancy prediction and analysis – a comprehensive study,” Transportation Research Procedia, vol. 73, pp. 297–304, 2023. doi: 10.1016/j.trpro.2023.11.921.",
        "[2] S. Bilotta, L. A. Ipsaro Palesi, and P. Nesi, “Predicting Free Parking Slots via Deep Learning in Short-Mid Terms Explaining Temporal Impact of Features,” IEEE Access, vol. 11, pp. 101678–101693, 2023. doi: 10.1109/ACCESS.2023.3314660.",
        "[3] F. Zhang, K. Shang, L. Yan, H. Nan, and Z. Miao, “Prediction of Parking Space Availability Using Improved MAT-LSTM Network,” ISPRS International Journal of Geo-Information, vol. 13, no. 5, article 151, 2024. doi: 10.3390/ijgi13050151.",
        "[4] F. J. Enríquez, J.-M. Mejía-Muñoz, G. Bravo, and O. Cruz-Mejía, “Smart Parking: Enhancing Urban Mobility with Fog Computing and Machine Learning-Based Parking Occupancy Prediction,” Applied System Innovation, vol. 7, no. 3, article 52, 2024. doi: 10.3390/asi7030052.",
        "[5] A. Dahiya, P. Mittal, Y. K. Sharma, U. K. Lilhore, S. Simaiya, E. Ghith, and M. Tlija, “Machine Learning-Based Prediction of Parking Space Availability in IoT-Enabled Smart Parking Management Systems,” Journal of Advanced Transportation, 2024, article 8474973. doi: 10.1155/2024/8474973.",
        "[6] H. Kuang, K. Deng, Q. Wang, W. Ye, H. Qu, and J. Li, “Deep meta-learning approach for regional parking occupancy prediction considering heterogeneous and real-time information,” Advanced Engineering Informatics, vol. 64, article 102969, 2025. doi: 10.1016/j.aei.2024.102969.",
        "[7] A. Kaltenbrunner, J. Ferrer, D. Moreno, et al., “A simple and explainable model for park-and-ride car park occupancy prediction,” EPJ Data Science, vol. 14, article 74, 2025. doi: 10.1140/epjds/s13688-025-00588-0.",
        "[8] A. Durairaj, A. Baskaran, R. Janakiraman, and P. Narayanan, “An Optimized Deep Learning-Based Smart Parking Mechanism for Smart City Environment,” International Journal of Computational Intelligence Systems, vol. 18, article 290, 2025. doi: 10.1007/s44196-025-01030-z.",
        "[9] K. Vakrinou, E. G. Mantouka, and E. Vlahogianni, “Leveraging multisource data for off-street parking occupancy prediction: a twofold analysis,” International Journal of Transportation Science and Technology, vol. 21, pp. 352–371, 2026. doi: 10.1016/j.ijtst.2025.02.005.",
        "[10] A. Ostadi, D. Das, G. Elmamooz, and D. Nicklas, “Data Engineering for Horizon-Aware Smart Parking Systems,” Datenbank-Spektrum, vol. 26, no. 2, pp. 155–164, 2026. doi: 10.1007/s13222-026-00544-w.",
        "[11] S. Hochreiter and J. Schmidhuber, “Long Short-Term Memory,” Neural Computation, vol. 9, no. 8, pp. 1735–1780, 1997. doi: 10.1162/neco.1997.9.8.1735.",
        "[12] K. Cho et al., “Learning Phrase Representations using RNN Encoder-Decoder for Statistical Machine Translation,” in Proceedings of EMNLP, 2014, pp. 1724–1734. doi: 10.3115/v1/D14-1179.",
        "[13] A. Vaswani et al., “Attention Is All You Need,” in Advances in Neural Information Processing Systems 30, 2017. arXiv:1706.03762.",
        "[14] J. Kennedy and R. Eberhart, “Particle swarm optimization,” in Proceedings of IEEE International Conference on Neural Networks, vol. 4, 1995, pp. 1942–1948. doi: 10.1109/ICNN.1995.488968.",
        "[15] M. Dorigo, V. Maniezzo, and A. Colorni, “Ant System: Optimization by a Colony of Cooperating Agents,” IEEE Transactions on Systems, Man, and Cybernetics, Part B, vol. 26, no. 1, pp. 29–41, 1996. doi: 10.1109/3477.484436.",
        "[16] NXP Semiconductors, “MFRC522 Standard performance MIFARE and NTAG frontend,” Rev. 3.9, 2016. https://www.nxp.com/docs/en/data-sheet/MFRC522.pdf (accessed 26 Oct. 2026).",
        "[17] TowerPro, “SG90 Digital,” manufacturer specifications. https://towerpro.com.tw/product/sg90-7/ (accessed 26 Oct. 2026).",
        "[18] Espressif Systems, “ESP32 Series Datasheet,” v5.3. https://documentation.espressif.com/esp32_datasheet_en.html (accessed 26 Oct. 2026).",
    ]
    for reference in references:
        paragraph = document.add_paragraph(reference)
        paragraph.paragraph_format.left_indent = Inches(0.22)
        paragraph.paragraph_format.first_line_indent = Inches(-0.22)
        paragraph.paragraph_format.space_after = Pt(4)

    _heading(document, "Dataset Availability")
    _paragraph(
        document,
        "The privacy-safe simulated dataset archive and project source are publicly available from GitHub. The version-pinned ZIP contains parking_raw.csv, parking_features.csv, dataset_metadata.json, and dataset documentation. The project Drive folder includes the project materials and demonstration video; access follows the folder's sharing permissions.",
    )
    _add_hyperlink(document.add_paragraph(), "GitHub project repository", PROJECT_GITHUB_URL)
    _add_hyperlink(document.add_paragraph(), "Public dataset ZIP (GitHub)", DATASET_PUBLIC_URL)
    _add_hyperlink(
        document.add_paragraph(),
        "Project folder and demonstration video (Google Drive)",
        PROJECT_DRIVE_FOLDER_URL,
    )

    report_path = output_directory / "Smart_Parking_Final_Report.docx"
    document.save(report_path)
    evidence_directory = output_directory / "evidence"
    evidence_directory.mkdir(parents=True, exist_ok=True)
    evidence_files = (
        "dataset/dataset_metadata.json",
        "ml_results/model_comparison.csv",
        "ml_results/model_comparison.json",
        "optimization_results/optimizer_comparison.csv",
        "optimization_results/optimizer_summary.json",
        "optimization_results/benchmark_runs.csv",
        "optimization_results/sumo_observed_scenarios.jsonl",
    )
    evidence_hashes: dict[str, dict[str, str]] = {}
    for relative_path in evidence_files:
        source_path = repository_root / REVIEW / relative_path
        target_path = evidence_directory / Path(relative_path).name
        shutil.copy2(source_path, target_path)
        if target_path.suffix == ".csv":
            # Keep generated submission artifacts portable and `git diff --check` clean
            # when source CSVs use Windows line endings.
            target_path.write_bytes(target_path.read_bytes().replace(b"\r\n", b"\n"))
        evidence_hashes[target_path.name] = {
            "source": str(Path(REVIEW) / relative_path),
            "sha256": hashlib.sha256(target_path.read_bytes()).hexdigest(),
        }
    (evidence_directory / "provenance.json").write_text(
        json.dumps(
            {
                "generated_by": "scripts/build_final_submission.py",
                "note": "Metric and metadata files are copied from the current checkout; CSV line endings are normalized to LF without changing values. The dataset download URL in the report is pinned to commit 5b480d1.",
                "files": evidence_hashes,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    for filename in ("README.md", "SUBMISSION_CHECKLIST.md", "REFERENCES_VERIFIED.md"):
        source_path = repository_root / REVIEW / "final_submission" / filename
        shutil.copy2(source_path, output_directory / filename)
    if convert_pdf:
        _convert_to_pdf(report_path, output_directory)
    return report_path


def _convert_to_pdf(docx_path: Path, output_directory: Path) -> Path:
    executable = shutil.which("libreoffice") or shutil.which("soffice")
    if executable is None:
        raise RuntimeError("LibreOffice is required to generate the requested PDF")
    with tempfile.TemporaryDirectory(prefix="smart-parking-lo-profile-") as profile:
        subprocess.run(
            [
                executable,
                "--headless",
                f"-env:UserInstallation={Path(profile).as_uri()}",
                "--convert-to",
                "pdf",
                "--outdir",
                str(output_directory),
                str(docx_path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=120,
        )
    pdf_path = output_directory / f"{docx_path.stem}.pdf"
    if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
        raise RuntimeError("LibreOffice did not produce a non-empty PDF")
    return pdf_path


def _build_code_appendix_report(
    base_report: Path, output_report: Path, repository_root: Path
) -> Path:
    """Append the current Arduino-framework controller sources to a report copy."""
    document = Document(base_report)
    document.add_page_break()
    _heading(document, "Appendix A. Current ESP32 Arduino controller source")
    _paragraph(
        document,
        "This appendix reproduces the checked-in controller implementation and its public configuration template. "
        "The example configuration contains no real Wi-Fi credentials or device token.",
    )
    source_files = (
        "firmware/esp32_controller/src/main.cpp",
        "firmware/esp32_controller/include/pins.h",
        "firmware/esp32_controller/include/local_config.example.h",
        "firmware/esp32_controller/platformio.ini",
    )
    for relative_path in source_files:
        source = repository_root / relative_path
        if not source.is_file():
            continue
        _heading(document, relative_path, level=2)
        code = document.add_paragraph(style="No Spacing")
        code.paragraph_format.space_after = Pt(0)
        code.paragraph_format.line_spacing = 1.0
        run = code.add_run(source.read_text(encoding="utf-8"))
        run.font.name = "Consolas"
        run.font.size = Pt(6.5)
    document.save(output_report)
    return output_report


def _sync_archived_submission(repository_root: Path, output_directory: Path) -> None:
    """Keep the dated submission copy aligned with the freshly built deliverables."""
    archive = repository_root / REVIEW / "final_submission"
    archive.mkdir(parents=True, exist_ok=True)
    for filename in (
        "Smart_Parking_Final_Report.docx",
        "Smart_Parking_Final_Report.pdf",
        "README.md",
        "SUBMISSION_CHECKLIST.md",
        "REFERENCES_VERIFIED.md",
    ):
        source = output_directory / filename
        if source.is_file():
            shutil.copy2(source, archive / filename)
    for directory in ("figures", "evidence"):
        source = output_directory / directory
        if source.is_dir():
            shutil.copytree(source, archive / directory, dirs_exist_ok=True)
    hardware_source = repository_root / "docs/hardware/bill_of_materials.csv"
    hardware_target = archive / "hardware/bill_of_materials.csv"
    if hardware_source.is_file():
        hardware_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(hardware_source, hardware_target)
    for filename in (
        "hardware_overview.png",
        "rfid_reader_closeup.png",
        "controller_board_front.png",
        "controller_wiring_detail.png",
        "hardware_dashboard_evidence.png",
        "optimizer_comparison.png",
        "dashboard_capture.png",
    ):
        (archive / "figures" / filename).unlink(missing_ok=True)
    for filename in (
        "system_architecture.dot",
        "system_architecture.svg",
        "system_architecture.png",
        "system_architecture.pdf",
        "system_block_diagram.dot",
        "system_block_diagram.svg",
        "system_block_diagram.png",
        "system_block_diagram.pdf",
    ):
        source = repository_root / "docs/hardware" / filename
        if source.is_file():
            target = archive / "hardware" / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-directory", type=Path, default=Path("output/final_submission"))
    parser.add_argument("--docx-only", action="store_true")
    args = parser.parse_args()
    path = build_report(args.repository_root, args.output_directory, convert_pdf=not args.docx_only)
    if args.output_directory.resolve() == (args.repository_root / "output/final_submission").resolve():
        repository_root = args.repository_root.resolve()
        output_directory = args.output_directory.resolve()
        _sync_archived_submission(repository_root, output_directory)
        clean_report = repository_root / "Smart_Parking_Final_Project_Writeup_Clean.docx"
        shutil.copy2(path, clean_report)
        pdf_path = output_directory / "Smart_Parking_Final_Report.pdf"
        if pdf_path.is_file():
            shutil.copy2(pdf_path, repository_root / "Smart_Parking_Final_Project_Writeup_Clean.pdf")
        code_report = repository_root / "smart_parking_project_report_with_arduino_code.docx"
        _build_code_appendix_report(path, code_report, repository_root)
        if pdf_path.is_file():
            _convert_to_pdf(code_report, repository_root)
    print(path)
    if not args.docx_only:
        print(args.output_directory / "Smart_Parking_Final_Report.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
