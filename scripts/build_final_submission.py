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
from PIL import Image, ImageOps

REVIEW = Path("review_outputs/2026-10-15")
DATASET_URL = "https://drive.google.com/file/d/1-bgCGNuCgbhWTbKyxnMlLpOQH1s3lxSZ/view?usp=drivesdk"
DATASET_PUBLIC_URL = "https://github.com/dumbly-smart/smart-parking/raw/5b480d1/review_outputs/2026-10-15/dataset/parking_dataset.zip"
MODELS_URL = "https://drive.google.com/file/d/1I1ECMeYlJT9-oop4Bh-Qedgti9Kds6lj/view?usp=drivesdk"


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
    paragraph.paragraph_format.keep_with_next = True
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
    paragraph.add_run().add_picture(str(path), width=Inches(6.25))
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
    header.text = "FINAL PROJECT REPORT  ·  20 OCTOBER 2026"
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
            ImageOps.grayscale(image).save(figures / source.name)
    metadata = json.loads(
        (repository_root / REVIEW / "dataset/dataset_metadata.json").read_text(encoding="utf-8")
    )
    optimizer_summary = json.loads(
        (repository_root / REVIEW / "optimization_results/optimizer_summary.json").read_text(
            encoding="utf-8"
        )
    )
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
        "Akil\nRegistration number: 25BCE2777\nInstitution: [Enter institution]\n"
        "Course: [Enter course]\nFaculty / guide: [Enter name]\nFinal project report · 20 October 2026"
    )
    authors.paragraph_format.space_before = Pt(28)
    document.add_page_break()

    _heading(document, "Abstract")
    abstract = (
        "Parking guidance requires occupancy, reliable vehicle records, and a rule for choosing among "
        "free spaces. This project presents a five-space smart-parking prototype integrating RFID session handling, camera "
        "occupancy processing, slot allocation, short-horizon forecasting, and a browser dashboard. A FastAPI service and "
        "SQLite database coordinate state. ESP32 controller firmware reads RFID tags and requests entry or exit decisions; "
        "ESP32-CAM firmware serves JPEG captures to a Python ingestion process. Forecast models run on the server, keeping "
        "neural inference outside the microcontrollers. Evaluation uses a synthetic timeline of 4,032 five-minute intervals "
        "with 27 features. LSTM, GRU, and temporal Transformer regressors share a 12-step lookback, one-step horizon, "
        "chronological 70/15/15 split, and training-only scaling. On the synthetic test partition, GRU obtains MAE 0.098055 "
        "and RMSE 0.117862; persistence obtains MAE 0.120875 and RMSE 0.169173. The allocation study evaluates five policies "
        "across 120 scenarios with three seeded repetitions. Exact enumeration and the genetic algorithm both achieve mean "
        "objective cost 0.378194; PSO and ACO have mean optimality gaps 0.048264 and 0.003586. These values describe "
        "generated observations and five-slot software simulations, not field performance. Automated tests cover lifecycle, "
        "camera input, occupancy transitions, and prediction behavior; both firmware targets have compile evidence. "
        "The user reports that the assembled tabletop hardware works; this qualitative report was not captured as a serial trial log. Earlier RC522 diagnostics recorded invalid SPI responses before that report. RFID success rates, camera accuracy, OLED/LED correctness, servo timing, and power remain without measured trials. The camera detector is an edge-density "
        "heuristic requiring calibrated regions and real-scene validation. This report documents architecture, proposed wiring, "
        "implementation, measurements, limitations, and bench procedures. The prototype demonstrates an auditable software "
        "integration path; deployment conclusions require real data, occupancy labels, electrical checks, and supervised "
        "hardware trials."
    )
    _paragraph(document, abstract)
    document.paragraphs[-1].paragraph_format.line_spacing = 1.15
    document.paragraphs[-1].paragraph_format.space_after = Pt(12)
    _paragraph(
        document,
        "Keywords: smart parking, Internet of Things, RFID, camera occupancy, allocation optimization, occupancy forecasting, LSTM, GRU, Transformer",
    )
    document.add_page_break()

    _heading(document, "1. Introduction")
    _paragraph(
        document,
        "Parking search is a coordination problem: drivers need current availability, operators need a consistent record of arrivals and departures, and a guidance policy must select from the spaces that remain free. Sensors and networked systems can make that state visible, but the quality of a result depends on the sensing method, communication reliability, and whether the allocation and forecasting methods are evaluated against appropriate baselines [1].",
    )
    _paragraph(
        document,
        "This project separates device I/O from server computation. An ESP32 controller reads an RFID tag and calls the existing vehicle lifecycle API. A camera module can provide JPEG snapshots to a Python polling service; that service forwards valid frames to the backend's existing occupancy endpoint. FastAPI coordinates persistence, occupancy, allocation, prediction, and the browser dashboard. TensorFlow/Keras forecasting runs on the server; neither the ESP32 controller nor the ESP32-CAM performs neural inference.",
    )
    _paragraph(
        document,
        "The software contributions are (i) an idempotent API lifecycle and shared allocation objective, (ii) a privacy-conscious simulated time-series dataset and comparable neural forecasting experiment, (iii) a reproducible GA/PSO/ACO benchmark with deterministic and exact references, and (iv) a hardware integration path that fails closed when allocation cannot be confirmed. The user reports that the assembled tabletop hardware works. Since no post-rewire trial logs or quantitative measurements were captured, the report distinguishes that qualitative user report from measured results and provides only source/specification-based engineering estimates where defensible.",
    )
    _paragraph(
        document,
        "The Arduino framework on the ESP32 is suited to deterministic sensor polling and actuator control, while the host computer provides the memory and processing environment for training and running the neural regressors. This split keeps the microcontroller responsible for bounded I/O and authorization checks and leaves data-intensive inference on the server.",
    )

    _heading(document, "2. Literature Survey")
    _paragraph(
        document,
        "Prior work spans sensing, RFID-mediated access, vision datasets, forecasting, and allocation. The comparison below distinguishes the evaluated scope of each source from the narrower five-slot simulated experiments in this project.",
    )
    literature = [
        [
            "de Almeida et al. [14]",
            "2022 · Expert Systems with Applications",
            "Systematic review of public datasets and computer-vision methods for parking-lot management.",
            "Finds dataset dependence and weak evaluation protocols; motivates explicit limits on this project's heuristic and absence of labeled field images.",
        ],
        [
            "Lee et al. [15]",
            "2022 · Microprocessors and Microsystems",
            "Reviews edge-enabled smart parking with emphasis on security, energy use, sensors, and communication.",
            "Highlights security and energy considerations; this prototype's HTTP endpoints remain unauthenticated and its power is unmeasured.",
        ],
        [
            "Feng et al. [16]",
            "2022 · Complex & Intelligent Systems",
            "Uses a dual ConvLSTM and dense convolution network for zone-wise availability prediction over public-lot data.",
            "Models spatial relationships across lots and reports real-data experiments; the present five-slot regression uses synthetic data and no spatial graph.",
        ],
        [
            "Zhang et al. [17]",
            "2024 · ISPRS International Journal of Geo-Information",
            "Compares TCN and LSTM and proposes MAT-LSTM for parking-space availability using real and synthetic datasets.",
            "Supports controlled comparisons across data sources; it does not validate the architectures or synthetic generator used in this project.",
        ],
        [
            "Enríquez et al. [18]",
            "2024 · Applied System Innovation",
            "Studies AdaBoost parking prediction with real parking-flow data and simulated fog/cloud latency.",
            "Shows the distinction between measured prediction and simulated network latency; this project reports server-side model timing only.",
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
        "Recent work emphasizes dataset-independent vision evaluation [14], security and energy concerns in edge deployments [15], spatial forecasting across zones [16], recurrent and convolutional model comparisons [17], and prediction with fog/cloud architectures [18]. Foundational model formulations used here are LSTM [6], GRU [7], and self-attention [8]. These publications define methods and identify evaluation needs; they do not validate this project's synthetic corpus or hardware. The gap addressed here is a small, reproducible integration with matched model inputs and explicit simulation limits, rather than a new state-of-the-art claim.",
    )
    _paragraph(
        document,
        "Across these strands, prior work commonly emphasizes a particular sensing modality, city-scale prediction task, or optimization formulation. The present contribution is an integrated, inspectable prototype and a controlled comparison on its five-slot objective, with exact enumeration used to test whether metaheuristics add value at this scale. The contribution is engineering and evaluation of this system instance; it is not a new optimization algorithm or a field-validated occupancy model.",
    )

    _heading(document, "3. Problem Statement and Objectives")
    _paragraph(
        document,
        "The system must keep a consistent record of which configured parking spaces are occupied, associate a vehicle's entry and exit with idempotent operations, select only a free slot, and expose current and short-horizon occupancy through a dashboard/API. A camera-based heuristic may suggest occupancy transitions, but its output is confidence-filtered and temporally smoothed before persistence. A forecast is a regression estimate over aggregated server history, not a direct image classifier.",
    )
    _add_table_caption(document, "Table 2. Objectives, completion status, and available evidence")
    _add_table(
        document,
        ["Objective", "Status and evidence"],
        [
            [
                "Identify configured-slot occupancy",
                "Software implemented: JPEG ROI edge-density detector, confidence filter, consecutive-frame smoothing, SQLite persistence. Real-camera accuracy is not measured.",
            ],
            [
                "RFID entry/exit",
                "Backend API complete and tested; controller firmware implements polling, idempotent retry and response validation. Physical reader tests remain open.",
            ],
            [
                "Compare GA, PSO, ACO allocation",
                "Complete: 120 scenarios, three repeat seeds, common objective, first-available and exhaustive references.",
            ],
            [
                "Forecast next-interval occupancy",
                "Complete on deterministic synthetic data using LSTM, GRU, Transformer and persistence baseline.",
            ],
            [
                "Dashboard visibility",
                "Existing dashboard and API are implemented; browser screenshot and physical-device indicators were not captured in this environment.",
            ],
            [
                "Low-cost hardware integration",
                "Firmware projects compile and connection design is documented. A generic CH340 adapter was detected but its target is unknown; no peripheral behavior is verified.",
            ],
        ],
    )

    _heading(document, "4. System Architecture")
    _paragraph(
        document,
        "The backend remains the system coordinator. Camera capture and RFID access use distinct flows so a camera outage does not invent a vehicle operation and a network failure cannot trigger a gate opening. SQLite is the local system of record. The dashboard consumes backend routes rather than reading device state directly.",
    )
    _add_figure(
        document,
        figures,
        "system_block_diagram.png",
        "Figure 1. System data flow; compute-intensive vision aggregation, allocation, forecasting and persistence run on the server.",
    )
    _paragraph(
        document,
        "Camera flow: ESP32-CAM GET /capture → camera_ingest validates size, MIME type and JPEG decode → multipart POST /api/camera/occupancy → configured ROI detection → confidence and consecutive-frame checks → persisted accepted occupancy transition → status/dashboard and feature aggregation. Controller flow: RC522 UID → GET /api/parking/status → POST /api/vehicle/entry or /api/vehicle/exit with a persisted idempotency key → response and subsequent status validation → OLED/LED update and one gate cycle. A timeout preserves the pending key and leaves the gate closed until confirmation.",
    )
    _paragraph(
        document,
        "Forecast flow uses the same PreparedDataset contract for each model. The runtime predictor loads compatible, hash-checked model artifacts and uses a deterministic fallback when unavailable. Allocation uses configured weights and excludes occupied candidates. The small five-slot exhaustive benchmark computes the exact single-slot minimum for each scenario.",
    )
    _paragraph(
        document,
        "The backend exposes separate routes for vehicle entry/exit, parking status, image occupancy, allocation benchmarks, forecasts, and dashboard data. The database is the authoritative state shared by those services. Camera-derived observations update occupancy only after the detector's configured confidence and temporal conditions are met; they do not create or close an RFID vehicle session. Conversely, an RFID entry creates an operational session and allocation record but does not prove that a camera has visually observed the vehicle.",
    )

    _heading(document, "5. Hardware Design")
    _paragraph(
        document,
        "The selected compile targets are a generic ESP32 DevKit/WROOM-32 controller and an AI-Thinker ESP32-CAM/OV2640. The repository's original design did not specify purchased board revisions; therefore the controller pin assignment is proposed and the camera firmware explicitly selects the AI-Thinker map. Check the board silkscreen and vendor documentation before power-up. The diagrams are a design proposal, not a physically verified circuit.",
    )
    _add_figure(
        document,
        figures,
        "circuit_diagram.png",
        "Figure 2. Proposed electrical wiring with separate servo/camera power rails and a common ground reference.",
    )
    _add_figure(
        document,
        figures,
        "wiring_diagram.png",
        "Figure 3. Proposed signal map for controller peripherals and Wi-Fi-connected camera.",
    )
    _add_table_caption(document, "Table 3. Proposed controller pin assignments")
    _add_table(
        document,
        ["Component", "Signal", "ESP32 pin", "Voltage", "Connection note"],
        [
            ["RC522", "SCK / MISO / MOSI", "18 / 19 / 23", "3.3 V logic", "VSPI; dedicated bus"],
            ["RC522", "SS / RST", "13 / 4", "3.3 V logic", "Avoid strap pins for SS"],
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
            [
                "AI-Thinker ESP32-CAM",
                "OV2640 camera bus",
                "0, 5, 18, 19, 21–27, 32, 34–39",
                "Module-internal",
                "Reserved by camera; no external peripherals on these pins",
            ],
        ],
        font_size=8,
    )
    _paragraph(
        document,
        "The controller pin proposal avoids classic ESP32 strapping pins (0, 2, 5, 12, 15), flash-reserved pins (6–11), and input-only GPIO34–39. The selected RC522 bus uses 18/19/23; the OLED uses 21/22; LED and servo signals use output-capable GPIO. Espressif documents these GPIO restrictions and boot-strap considerations [9]. Camera GPIO assignments follow the AI-Thinker reference map in Espressif's esp32-camera project [10]. The pin map has been reviewed against those references but not checked with a multimeter or actual board revision.",
    )
    _paragraph(
        document,
        "Use the controller's USB input, RC522/OLED 3V3, a separate regulated 5-V supply for the servo, and a separately regulated 5-V camera input. Connect grounds at a common reference while keeping positive 5-V rails isolated. A 330 Ω series resistor limits each indicator LED current. A servo can draw a transient/stall current beyond a GPIO or dev-board regulator budget; size the external supply to the exact SG90 variant, and keep the barrier model lightweight and supervised. A hobby servo is not a safety-rated real gate: loss of servo power may leave the arm where it stopped.",
    )
    _paragraph(
        document,
        "The bill of materials, full per-signal CSV pin map, wiring sequence, calibration notes and troubleshooting table are included in final_submission/hardware/ and docs/hardware/validation.md. The user reports successful operation of the assembled tabletop rig; quantitative per-component validation remains uncaptured.",
    )

    _heading(document, "6. Software and Machine-Learning Design")
    _add_table_caption(document, "Table 4. Software components and responsibilities")
    _add_table(
        document,
        ["Technology", "Role in implementation"],
        [
            [
                "Python 3.14.8",
                "Backend, data preparation, benchmarking, camera ingestion, calibration, report tooling on the measured host.",
            ],
            [
                "FastAPI and SQLite",
                "HTTP contracts, lifecycle state, occupancy transitions, prediction/optimizer metrics and dashboard data.",
            ],
            [
                "NumPy and Pillow",
                "Feature arrays and bounded JPEG decode/ROI edge-density detection.",
            ],
            [
                "TensorFlow/Keras",
                "Server-side LSTM, GRU, and temporal Transformer regression models.",
            ],
            [
                "Arduino framework + PlatformIO",
                "ESP32 controller and AI-Thinker ESP32-CAM builds; no device was attached during compile verification.",
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
        f"The deterministic corpus is explicitly synthetic: {metadata['records']['feature_timeline']:,} five-minute timeline buckets across 14 days, {metadata['feature_count']} model input features, and {metadata['records']['raw_observations']:,} privacy-safe source observations. It covers five configured slots from {metadata['time_coverage_utc']['start']} through {metadata['time_coverage_utc']['end']}; seed {metadata['random_seed']}. Features include occupancy ratio/change and rolling means, cyclic hour and weekday terms, simulated weather categories, holiday/event flags, entry/exit/allocation counts, active sessions, privacy-safe vehicle aggregates, and normalized allocation context. The target is occupancy ratio at the next five-minute interval.",
    )
    _paragraph(
        document,
        "The existing preprocessor creates a 12-bucket (60-minute) lookback and one-step forecast horizon. It divides the timeline chronologically into 70% training, 15% validation and 15% test before sequence construction; sequence counts are 2,810, 592 and 594. Continuous-feature means and scales are fitted on training data only. The same immutable PreparedDataset is passed to all three neural models, and no RFID UID is part of model inputs. This prevents future observations from entering earlier sequences or fitted scaling statistics.",
    )
    _paragraph(
        document,
        "Missing-value handling follows the existing feature builder: eligible short gaps are forward-filled and longer gaps remain missing and are excluded from training examples. Bounded/cyclic/one-hot inputs retain their established contract; the continuous feature scaler is shared by all models. The last timeline bucket has no next-step target and is not used as a supervised target row. The data is useful for exercising code paths and comparing models reproducibly; it cannot estimate field performance, actual weather effects, arrival rates, camera accuracy or transfer to another lot.",
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
        "LSTM and GRU models each apply one 16-unit recurrent layer to the 12-step sequence, followed by a one-unit sigmoid output. The temporal Transformer projects each 27-feature step to width 16, adds learned positional embeddings, applies two-head self-attention (key dimension 8), residual/LayerNorm, a 32-unit ReLU then 16-unit feed-forward block, a second residual/LayerNorm, global average pooling, and a sigmoid scalar output. Training uses mean-squared-error loss with Adam at 0.001, 12 maximum epochs, batch size 32, early-stopping patience 3, recurrent units 16, Transformer width 16 and two heads. Seeded TensorFlow/Keras deterministic operations are enabled where supported. The target is continuous occupancy ratio, so classification accuracy, F1, ROC and confusion matrices are not applicable.",
    )
    _paragraph(
        document,
        "Model files use content-addressed Keras artifacts with manifests containing feature order, split identity, scaler values, configuration, software versions and SHA-256. The artifacts execute in the server runtime. TensorFlow Lite, quantization and pruning were not implemented because inference is intentionally server-side; no ESP32 inference claim is made.",
    )

    _heading(document, "6.3 Allocation Objective", 2)
    _paragraph(
        document,
        "For candidate slot i, the shared normalized scalar objective is J(i) = 0.35 dᵢ + 0.30 cᵢ + 0.20 wᵢ + 0.15 fᵢ, where distance d, congestion c, waiting contribution w, and fairness penalty f are read from parking configuration. Occupied slots are excluded before search. The benchmark compares a first-available policy, exhaustive enumeration of every free slot (the exact optimum for this single-slot decision), and GA, PSO, and ACO on identical scenario records and weights. For heuristic assignment x, the optimality gap is J(x) − minᵢ J(i), which is nonnegative up to floating-point tolerance. Convergence curves are not included because the existing optimizer interface does not expose valid per-iteration histories [12], [13].",
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
        "The backend lifecycle API accepts JSON fields rfid_uid and idempotency_key. A key is generated from the controller chip identifier and an NVS-persisted sequence number, then stored with the pending operation before transmission. A restart reuses the same key and payload, allowing the server's existing idempotency behavior to replay a completed response safely. The UID is not printed to Serial. As the existing API has no device authentication or TLS provision in this project, these requests must remain on a trusted private LAN.",
    )
    _paragraph(
        document,
        "Allocation follows one shared weighted_cost function. A no-available-slot response is HTTP 409, which the controller treats as a closed-gate result. For successful entry, the firmware validates the returned UID, slot identifier, slot name, gate_action and current status before display and actuation. For exit it requires that the session no longer appears active. The slot LEDs reflect accepted server occupancy: ON means occupied, OFF means free, and all blink when status is unknown. OLED messages cover initialization, Wi-Fi/backend state, scanning, assignment, parking-full/conflict, completion and errors. The timed gate state machine closes after its configured open interval; it does not use an unbounded delay.",
    )
    _paragraph(
        document,
        "The ESP32-CAM exposes GET /health and GET /capture. AI-Thinker pin assignments are isolated in camera_board.h; unknown board variants fail compilation unless a mapping is explicitly selected. JPEG capture uses VGA and JPEG quality 12 by default, with PSRAM-aware buffers. The Python camera_ingest process validates image/jpeg, bounds payload size and response size, decodes the JPEG with Pillow, posts to the existing multipart occupancy API, limits operation to one in-flight frame, and exponentially backs off after errors. The minimum capture interval is two seconds.",
    )
    _paragraph(
        document,
        "ROI calibration captures a live JPEG or accepts a previously saved real JPEG, presents an interactive Tk/Pillow rectangle selector, validates one in-bounds non-overlapping ROI per configured slot, writes the same ROI schema used by the detector, and saves a visual overlay. This environment cannot supply a real lot image, so no calibrated field ROI file is included. The current detector computes edge density for each crop and applies the configured score threshold; confidence and three consecutive candidate frames are required before persisting a transition. It remains a heuristic, not a validated vehicle classifier.",
    )

    _heading(document, "8. Experimental Setup")
    _paragraph(
        document,
        "The prediction experiment uses the generated synthetic timeline and the unchanged chronological split. All neural models use common preprocessing and the untouched test partition; the persistence baseline predicts the latest occupancy ratio. Inference latency is measured as median warm prediction time divided by example count on the server CPU. The results are from TensorFlow 2.22.0-rc0/Keras 3.16.0.dev2026101404 under Python 3.14.8 on Linux x86_64 with an Intel Core i7-14650HX host. No accelerator or microcontroller timing is reported.",
    )
    _paragraph(
        document,
        f"Optimizer tests use {optimizer_summary['scenario_count']} distinct scenarios, three repeat seeds per scenario, {optimizer_summary['iterations']} iterations per heuristic, and configured weights {json.dumps(optimizer_summary['weights'], sort_keys=True)}. Scenario occupancy spans empty, light, moderate, heavy, near-full and full categories. Seed derivation is `{optimizer_summary['random_seed_formula']}`. Each policy receives identical scenario inputs. Runtime is measured with a monotonic clock. Full-capacity rejections are separated from successful cost statistics. This is a simulated one-slot objective, not traffic throughput or physical wait time.",
    )
    _paragraph(
        document,
        "The host's development environment provides an Intel Core i7-14650HX with 24 CPUs online and 15 GiB RAM; benchmark latencies are software measurements from this machine and vary with system load. During an earlier integration check, the host exposed a generic CH340 USB serial adapter at /dev/ttyUSB0, but the attached target board could not then be identified from the host. No private controller configuration was present, and esp32-cam.local was not resolved at that time. Later work identified and flashed an ESP32 controller; the user subsequently reported that the assembled tabletop rig works. These historical host observations are not post-rewire peripheral measurements.",
    )

    _heading(document, "9. Results and Discussion")
    _heading(document, "9.1 Prediction Results", 2)
    _paragraph(
        document,
        "Table 5 compares the persistence reference with the three trained neural regressors on the same test windows. GRU is the best measured model for MAE and RMSE on this generated split. This is an empirical ranking for one synthetic dataset and seed, not evidence of universal superiority or real-lot forecast quality. All inference timing is server CPU timing; model size is serialized Keras size.",
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
        f"The measured GRU test MAE is {float(models['gru']['mae']):.6f}, versus persistence MAE {float(models['persistence_baseline']['mae']):.6f}. The 27 features include simulated calendar/weather/event context, but synthetic context may encode generator-specific patterns. Real measured samples, external-site validation and repeated independent dataset seeds are needed before drawing deployment conclusions. No camera accuracy metric is reported because no labeled image evaluation set is available.",
    )

    _heading(document, "9.2 Allocation Results", 2)
    _paragraph(
        document,
        "Table 6 summarizes allocation performance across the repeated attempts; each policy rejected 60 of 360 attempts at full capacity. There were zero invalid slot assignments. The exhaustive policy is the exact single-slot minimum for each scenario. GA matched this mean cost in this run but required substantially more Python runtime than enumeration; ACO was close to optimal and PSO had a larger mean gap. The first-available baseline was fastest but had higher mean cost. Heuristics are not expected to beat exact enumeration when at most five candidates exist.",
    )
    _add_optimizer_results_table(document, repository_root)
    _add_figure(
        document,
        figures,
        "optimizer_comparison.png",
        "Figure 13. Mean allocation objective cost by policy and exact/baseline reference.",
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
    occupancy_rows = []
    for level in ("empty", "light", "moderate", "heavy", "near_full"):
        occupancy_rows.append(
            [level]
            + [
                f"{optimizer_summary['by_occupancy'][f'{name}:{level}']['mean_cost']:.6f}"
                for name in ("first_available", "exhaustive_optimum", "GA", "PSO", "ACO")
            ]
        )
    _add_table_caption(document, "Table 7. Mean objective cost by simulated occupancy category")
    _add_table(
        document,
        ["Occupancy category", "First available", "Exact", "GA", "PSO", "ACO"],
        occupancy_rows,
        font_size=7,
    )
    _paragraph(
        document,
        "The occupancy-stratified table uses 60 repeated successful runs per category and policy. Full-capacity cases are excluded from these cost means and are reported separately. Runtime values describe Python algorithm execution on the host and are not estimates of physical vehicle wait or lane throughput.",
    )

    _heading(document, "9.3 Hardware and integration test status", 2)
    if hardware_validation:
        reader_versions = ", ".join(
            f"0x{item['version_register']:02X}"
            for item in hardware_validation.get("rfid_reader_spi_probes", [])
            if isinstance(item.get("version_register"), int)
        ) or "no reader probe captured"
        heap_metric = (
            hardware_summary.get("metrics", {}).get("free_heap_bytes", {})
            if hardware_summary
            else {}
        )
        heap_result = (
            f" Free heap across {heap_metric['count']} physical serial events averaged "
            f"{heap_metric['mean']:.0f} bytes (median {heap_metric['median']:.0f}, "
            f"sample standard deviation {heap_metric['standard_deviation']:.0f}, "
            f"p95 {heap_metric['p95']:.0f})."
            if heap_metric.get("status") == "MEASURED"
            else " Controller free-heap measurement is NOT TESTED."
        )
        hardware_status_paragraph = (
            f"PlatformIO compiled both firmware targets. A read-only probe identified "
            f"the controller as {hardware_validation.get('controller_chip', 'an ESP32')}; "
            f"its {hardware_validation.get('flash_size_bytes', 0):,}-byte flash was backed "
            f"up before the upload, and esptool verified the flashed image hash. Serial "
            f"telemetry recorded {hardware_validation.get('controller_boot_events', 0)} boots "
            f"and {hardware_validation.get('wifi_connected_events', 0)} Wi-Fi connections. "
            f"The local API access log recorded "
            f"{hardware_validation.get('health_200_responses_after_latest_boot', 0)} successful "
            f"health checks and {hardware_validation.get('authenticated_status_200_responses_after_latest_boot', 0)} "
            f"authenticated parking-status responses from the ESP32 after its latest boot."
            f"{heap_result} The RC522 VersionReg probes returned {reader_versions} during "
            f"the earlier wiring attempt. The user subsequently reports that the rewired "
            f"tabletop rig works, but no post-rewire serial capture, trial count, or "
            f"quantitative result was supplied; this remains a user-reported functional "
            f"check rather than independently captured evidence. No camera health endpoint "
            f"was found during the earlier LAN scan. RFID success rate, camera accuracy, "
            f"OLED/LED correctness, current draw, and physical servo timing remain without "
            f"measured trials. The occupancy API "
            f"has software tests with generated images and status-transition assertions, "
            f"not a labeled real-camera set."
        )
        controller_build_result = (
            f"PASS: compiled and flashed to {hardware_validation.get('controller_chip', 'ESP32')}; "
            "esptool hash verification passed and a full flash readback was saved before update."
        )
        controller_network_result = (
            f"PASS: {hardware_validation.get('wifi_connected_events', 0)} Wi-Fi connection "
            f"events; {hardware_validation.get('authenticated_status_200_responses_after_latest_boot', 0)} "
            "authenticated status responses returned HTTP 200."
        )
        reader_result = (
            f"Earlier probe: invalid VersionReg values {reader_versions}. The user later "
            "reported successful operation after rewiring; no post-rewire card-read log "
            "or repeated-trial count was captured. Qualitative user report only."
        )
        camera_network_result = "NOT TESTED: camera board or /health endpoint was not found on LAN."
    else:
        hardware_status_paragraph = (
            "PlatformIO compiled the controller and AI-Thinker ESP32-CAM firmware. "
            "There is no physical controller validation evidence in the repository; "
            "no physical controller validation evidence is available. RFID, camera, "
            "display, LEDs, servo, current, and hardware latency remain NOT TESTED. "
            "The occupancy API has software tests with generated images and status-transition "
            "assertions, not a labeled real-camera set."
        )
        controller_build_result = "PASS: PlatformIO compilation only; no physical flash evidence."
        controller_network_result = "NOT TESTED: no physical controller network evidence."
        reader_result = "NOT TESTED physically; no reader probe or card read was recorded."
        camera_network_result = "NOT TESTED: no camera health endpoint was verified."
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
                "ESP32-CAM firmware build",
                "PASS: PlatformIO compilation for AI-Thinker target; no camera capture verified.",
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
                "OLED, LEDs, servo, physical camera",
                f"The user reports that the assembled rig works; no post-rewire per-component captures or trial counts are available. {camera_network_result}",
            ],
            [
                "Vision accuracy",
                "Not measured; no labeled real-camera test set.",
            ],
            [
                "ESP32 inference latency / memory",
                "Not applicable to the current server-side TensorFlow design; not measured on device.",
            ],
        ],
    )

    _heading(document, "9.4 Source- and specification-based engineering estimates", 2)
    _paragraph(
        document,
        "The following are rough engineering planning estimates, not hardware measurements or simulated benchmark outputs. Rate and latency ranges are low-confidence analyst assumptions for a close-range tabletop setup on stable local Wi-Fi. Component timing and current ranges use firmware constants and manufacturer specifications where available. Replace these with recorded trials before drawing performance conclusions. Camera accuracy has no defensible estimate without labeled images.",
    )
    _add_table_caption(document, "Table 9. Rough engineering estimates (not measured)")
    _add_table(
        document,
        ["Quantity", "Estimate", "Basis and limitations"],
        [
            [
                "RFID successful reads per close, aligned tap",
                "90–99% (very low confidence)",
                "Assumes a supported tag within about 20 mm, stable 3.3 V, and no nearby metal. MFRC522 specifies up to 50 mm depending on antenna tuning; that is not a success-rate guarantee [20].",
            ],
            [
                "API entry/exit transaction success on stable local LAN",
                "98–99.5% (very low confidence)",
                "Planning assumption for a reachable backend and healthy Wi-Fi. Retries are idempotent, but no post-rewire transaction trial series was captured.",
            ],
            [
                "Camera capture success on stable power/Wi-Fi",
                "95–99% (very low confidence)",
                "Planning assumption only; no physical ESP32-CAM capture series or dropped-frame count is available.",
            ],
            [
                "LED correctness with known slot state",
                "95–100% (very low confidence)",
                "Assumes correct pin mapping/polarity and a successful status refresh. No per-slot expected-versus-observed trial table is available.",
            ],
            [
                "Entry or exit latency, tag detection to accepted API response",
                "0.2–1.0 s (low confidence)",
                "Order-of-magnitude estimate for one local-Wi-Fi request and SQLite transaction with the server healthy. The 3.5 s HTTP timeout is a failure limit, not expected latency.",
            ],
            [
                "Wi-Fi recovery after AP becomes available",
                "5–15 s (low confidence)",
                "Firmware retries every 5 s; range allows up to about 10 s for association/DHCP after a retry. Poor AP conditions may take longer or fail.",
            ],
            [
                "Servo command delay, RFID detection to authorized GPIO command",
                "0.2–1.0 s (low confidence)",
                "Uses the assumed local API round trip; firmware issues the command only after authorization. Excludes mechanical travel.",
            ],
            [
                "SG90 travel for configured 10°→85° sweep",
                "0.13–0.50 s (very low confidence)",
                "Ideal nominal is 75° × 0.1 s/60° ≈125 ms at 4.8 V; upper range is a load/settling allowance. Exact servo variant is unverified [19].",
            ],
            [
                "OV2640 frame capture latency, configured JPEG mode",
                "0.10–0.50 s (very low confidence)",
                "Planning range for one SVGA-class JPEG frame with PSRAM. Exposure, frame size, clone, and lighting affect timing; no physical capture log is available.",
            ],
            [
                "Backend five-ROI heuristic processing latency",
                "0.01–0.10 s (very low confidence)",
                "Planning range for one frame and five ROIs on the local host; excludes capture, transfer, and queue delay. Not measured on a physical frame.",
            ],
            [
                "Controller free heap",
                "Measured historical mean 274,069 bytes (n=8)",
                "Captured physical serial telemetry before the user's later hardware report; median 292,240 bytes, SD 26,019 bytes, p95 293,416 bytes. This is measured, not an estimate or future guarantee.",
            ],
            [
                "Controller + reader + OLED + LEDs input current, servo excluded",
                "0.15–0.40 A at 5 V (very low confidence)",
                "Budget estimate from ESP32 active Wi-Fi radio draw plus peripherals; regulators, OLED brightness, LED current, and network duty cycle vary [21].",
            ],
            [
                "AI-Thinker ESP32-CAM input current",
                "About 0.18 A at 5 V; up to 0.31 A with flash at maximum",
                "Ai-Thinker module specification; not measured on this camera board [22].",
            ],
            [
                "SG90 servo supply current",
                "0.5–2.0 A (very low confidence)",
                "Manufacturer product page notes this operating-current range; exact unit/load is unknown. Use a separate regulated servo supply, never ESP32 GPIO or 3.3 V [19].",
            ],
            [
                "Camera occupancy accuracy",
                "Not estimated",
                "Requires a manually labeled real-scene test set. Synthetic frames cannot support an accuracy percentage.",
            ],
        ],
    )

    _heading(document, "10. Testing and Demonstration")
    physical_checklist_note = (
        "The hardware checklist records the controller boot, Wi-Fi, and authenticated "
        "status API evidence separately from the earlier invalid RC522 SPI probes. The user later "
        "reported successful operation after rewiring, but no post-rewire per-component logs, "
        "trial counts, or power measurements were captured."
        if hardware_validation
        else "The hardware scenario checklist marks physical behaviors NOT TESTED until "
        "the board-level procedures are performed."
    )
    _paragraph(
        document,
        "Automated software coverage includes backend lifecycle retries/conflicts, no-free-slot behavior, JPEG input validation, ROI bounds, confidence smoothing, state persistence, prediction fallback/artifact compatibility, simulated demo API ordering, and the new camera-ingestion and ROI-geometry tests. The build checklist distinguishes those results from firmware compilation and physical tests. "
        + physical_checklist_note,
    )
    _paragraph(
        document,
        "A separate host-runtime smoke test copied the review database, selected the saved GRU artifact through the existing predictor setting, and called GET /api/prediction. The response was model=gru, fallback_reason=null, occupancy_ratio=0.136493 for the synthetic timeline. This verifies server-side artifact loading and inference; it is not an ESP32 measurement.",
    )
    _paragraph(
        document,
        "The same-host simulated integration check also confirmed /health with five configured slots, accepted three generated JPEG frames through the occupancy route, and ran a labeled simulated RFID entry that received slot S1. GA, PSO and ACO benchmark endpoints returned results. With only the short synthetic history in that isolated database, prediction correctly reported the deterministic fallback reason insufficient_history. These checks establish that software paths respond; generated images and RFID values do not establish camera or reader operation.",
    )
    _paragraph(
        document,
        "For a simulated review: activate the project's virtual environment and run `make test` and `make lint`; start the API with `make run`; execute `python -m scripts.run_simulated_demo --base-url http://127.0.0.1:8000 --rfid-uid 04A1B2C3 --idempotency-key final-review-entry-001`; open http://127.0.0.1:8000/dashboard; then show `review_outputs/2026-10-15/EXPERIMENTAL_REPORT.md` and the figures under `review_outputs/2026-10-15/final_submission/figures/`. The simulated JPEGs and RFID label must be described as simulated. Do not run `make review` during the presentation because it retrains models and regenerates result files.",
    )
    _paragraph(
        document,
        "For a physical demo after wiring validation: use the private-LAN addresses in local_config.h, confirm GET /health, GET http://CAMERA-IP/health, run camera_ingest with a five-second interval, and scan one test tag. Verify status and gate action before proceeding to subsequent cards. Keep a hand-operated emergency power disconnect available for the lightweight servo fixture. The detailed startup, cleanup, and failure procedure appears in DEMO_INSTRUCTIONS.md.",
    )

    _heading(document, "11. Limitations and Future Work")
    _paragraph(
        document,
        "Primary limitations are the synthetic dataset, five-space scale, one-step horizon, generator-specific correlations, edge-density camera heuristic, absent labeled real imagery, lack of post-rewire quantitative hardware logs, and nonauthenticated HTTP control API. The user reports that the assembled tabletop rig works, but the available serial evidence predates that report. The architecture assumes a fixed camera and calibrated static ROIs. Lighting, weather, vehicle type, partial occlusion, perspective, shadows and camera motion may invalidate the baseline detector. Prediction accuracy on synthetic samples cannot establish field generalization.",
    )
    _paragraph(
        document,
        "Next work should acquire permissioned, labeled images and real occupancy timelines; split evaluation by day/site and repeat seeds; compare the heuristic with a measured vision baseline; validate the AI-Thinker and controller board revisions; conduct current-limited bench tests for RFID, display, LEDs and a lightweight servo; add transport authentication for device requests before any wider network exposure; and measure field latency and availability. A real gate requires a safety-rated actuator/controller and independent interlocks; the SG90 prototype is not that system.",
    )

    _heading(document, "12. Conclusion")
    _paragraph(
        document,
        "The repository provides a reproducible software smart-parking prototype with lifecycle, occupancy, allocation, forecasting, dashboard, synthetic experiment outputs, and ESP32 controller/camera firmware plus camera ingestion and ROI calibration. The measured synthetic experiment ranks GRU lowest in test MAE among the tested predictors, while exhaustive enumeration is an efficient exact reference for five-slot allocation. These results demonstrate functioning software and an experimental workflow, not deployment performance. The user reports successful operation of the assembled tabletop hardware. Earlier serial probes predate that report, and quantitative post-rewire RFID, camera, display, LED, servo, power, and latency trials were not captured. The report separates this user-reported function from measured results and source/specification-based estimates.",
    )

    _heading(document, "References")
    references = [
        "[1] T. Lin, H. Rivano, and F. Le Mouël, “A Survey of Smart Parking Solutions,” IEEE Transactions on Intelligent Transportation Systems, vol. 18, no. 12, pp. 3229–3253, 2017. doi: 10.1109/TITS.2017.2685143.",
        "[2] E. E. Tsiropoulou, J. S. Baras, S. Papavassiliou, and S. Sinha, “RFID-based smart parking management system,” Cyber-Physical Systems, vol. 3, nos. 1–4, pp. 22–41, 2017. doi: 10.1080/23335777.2017.1358765.",
        "[3] P. R. L. de Almeida, L. S. Oliveira, A. S. Britto Jr., E. J. Silva Jr., and A. L. Koerich, “PKLot – A robust dataset for parking lot classification,” Expert Systems with Applications, vol. 42, no. 11, pp. 4937–4949, 2015. doi: 10.1016/j.eswa.2015.02.009.",
        "[4] S. Yang, W. Ma, X. Pi, and S. Qian, “A deep learning approach to real-time parking occupancy prediction in transportation networks incorporating multiple spatio-temporal data sources,” Transportation Research Part C: Emerging Technologies, vol. 107, pp. 248–265, 2019. doi: 10.1016/j.trc.2019.08.010.",
        "[5] D. Thomas and B. C. Kovoor, “A Genetic Algorithm Approach to Autonomous Smart Vehicle Parking system,” Procedia Computer Science, vol. 125, pp. 68–76, 2018. doi: 10.1016/j.procs.2017.12.011.",
        "[6] S. Hochreiter and J. Schmidhuber, “Long Short-Term Memory,” Neural Computation, vol. 9, no. 8, pp. 1735–1780, 1997. doi: 10.1162/neco.1997.9.8.1735.",
        "[7] K. Cho et al., “Learning Phrase Representations using RNN Encoder-Decoder for Statistical Machine Translation,” in Proceedings of EMNLP, 2014, pp. 1724–1734. doi: 10.3115/v1/D14-1179.",
        "[8] A. Vaswani et al., “Attention Is All You Need,” in Advances in Neural Information Processing Systems 30, 2017. arXiv:1706.03762.",
        "[9] Espressif Systems, “GPIO & RTC GPIO — ESP32,” ESP-IDF Programming Guide v5.1. https://docs.espressif.com/projects/esp-idf/en/v5.1/esp32/api-reference/peripherals/gpio.html (accessed 14 Oct. 2026).",
        "[10] Espressif Systems, “ESP32-CAM / AI-Thinker camera pin map,” esp32-camera repository. https://github.com/espressif/esp32-camera/blob/master/examples/camera_example/main/camera_pinout.h (accessed 14 Oct. 2026).",
        "[11] Smart Parking System repository, implementation and experimental outputs. https://github.com/dumbly-smart/smart-parking (accessed 14 Oct. 2026).",
        "[12] J. Kennedy and R. Eberhart, “Particle swarm optimization,” in Proceedings of IEEE International Conference on Neural Networks, vol. 4, 1995, pp. 1942–1948. doi: 10.1109/ICNN.1995.488968.",
        "[13] M. Dorigo, V. Maniezzo, and A. Colorni, “Ant System: Optimization by a Colony of Cooperating Agents,” IEEE Transactions on Systems, Man, and Cybernetics, Part B, vol. 26, no. 1, pp. 29–41, 1996. doi: 10.1109/3477.484436.",
        "[14] P. R. L. de Almeida, J. H. Alves, R. S. Parpinelli, and J. P. Barddal, “A systematic review on computer vision-based parking lot management applied on public datasets,” Expert Systems with Applications, vol. 198, article 116731, 2022. doi: 10.1016/j.eswa.2022.116731.",
        "[15] C. P. Lee, F. T. J. Leng, R. A. A. Habeeb, M. A. Amanullah, and M. H. ur Rehman, “Edge computing-enabled secure and energy-efficient smart parking: A review,” Microprocessors and Microsystems, vol. 93, article 104612, 2022. doi: 10.1016/j.micpro.2022.104612.",
        "[16] Y. Feng, Y. Xu, Q. Hu, S. Krishnamoorthy, and Z. Tang, “Predicting vacant parking space availability zone-wisely: A hybrid deep learning approach,” Complex & Intelligent Systems, vol. 8, pp. 4145–4161, 2022. doi: 10.1007/s40747-022-00700-1.",
        "[17] F. Zhang, K. Shang, L. Yan, H. Nan, and Z. Miao, “Prediction of Parking Space Availability Using Improved MAT-LSTM Network,” ISPRS International Journal of Geo-Information, vol. 13, no. 5, article 151, 2024. doi: 10.3390/ijgi13050151.",
        "[18] F. J. Enríquez, J.-M. Mejía-Muñoz, G. Bravo, and O. Cruz-Mejía, “Smart Parking: Enhancing Urban Mobility with Fog Computing and Machine Learning-Based Parking Occupancy Prediction,” Applied System Innovation, vol. 7, no. 3, article 52, 2024. doi: 10.3390/asi7030052.",
        "[19] TowerPro, “SG90 Digital,” manufacturer specifications, operating speed 0.1 s/60° at 4.8 V. https://towerpro.com.tw/product/sg90-7/ (accessed 21 Oct. 2026).",
        "[20] NXP Semiconductors, “MFRC522 Standard performance MIFARE and NTAG frontend,” Rev. 3.9, 2016. Typical read/write distance up to 50 mm depending on antenna size and tuning. https://www.nxp.com/docs/en/data-sheet/MFRC522.pdf (accessed 21 Oct. 2026).",
        "[21] Espressif Systems, “ESP32 Series Datasheet,” v5.3, Wi-Fi active-mode current. https://documentation.espressif.com/esp32_datasheet_en.html (accessed 21 Oct. 2026).",
        "[22] Shenzhen Ai-Thinker Technology, “ESP32-CAM Wi-Fi+BT SoC Module Product Specification,” v1.0, 2017. https://d229kd5ey79jzj.cloudfront.net/1205/ESP32-CAM%20Product%20Specification.pdf (accessed 21 Oct. 2026).",
    ]
    for reference in references:
        paragraph = document.add_paragraph(reference)
        paragraph.paragraph_format.left_indent = Inches(0.22)
        paragraph.paragraph_format.first_line_indent = Inches(-0.22)
        paragraph.paragraph_format.space_after = Pt(4)

    _heading(document, "Dataset Availability")
    _paragraph(
        document,
        "The privacy-safe simulated dataset archive is publicly downloadable from the project's GitHub repository. The version-pinned ZIP contains parking_raw.csv, parking_features.csv, dataset_metadata.json, and dataset documentation. A Google Drive mirror is also provided, but its current permission is restricted to the vit.ac.in Google Workspace domain; use the public GitHub link if you do not have VIT access.",
    )
    _add_hyperlink(document.add_paragraph(), "Public dataset ZIP (GitHub)", DATASET_PUBLIC_URL)
    _add_hyperlink(
        document.add_paragraph(), "Google Drive dataset ZIP (institution-only)", DATASET_URL
    )
    _add_hyperlink(
        document.add_paragraph(), "Google Drive model artifacts (institution-only)", MODELS_URL
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
    )
    evidence_hashes: dict[str, dict[str, str]] = {}
    for relative_path in evidence_files:
        source_path = repository_root / REVIEW / relative_path
        target_path = evidence_directory / Path(relative_path).name
        shutil.copy2(source_path, target_path)
        evidence_hashes[target_path.name] = {
            "source": str(Path(REVIEW) / relative_path),
            "sha256": hashlib.sha256(target_path.read_bytes()).hexdigest(),
        }
    (evidence_directory / "provenance.json").write_text(
        json.dumps(
            {
                "generated_by": "scripts/build_final_submission.py",
                "note": "Metric and metadata files are copied verbatim from the current checkout; the dataset download URL in the report is pinned to commit 5b480d1.",
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository-root", type=Path, default=Path.cwd())
    parser.add_argument("--output-directory", type=Path, default=Path("output/final_submission"))
    parser.add_argument("--docx-only", action="store_true")
    args = parser.parse_args()
    path = build_report(args.repository_root, args.output_directory, convert_pdf=not args.docx_only)
    print(path)
    if not args.docx_only:
        print(args.output_directory / "Smart_Parking_Final_Report.pdf")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
