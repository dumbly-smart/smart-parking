# Final submission bundle

- `Smart_Parking_Final_Report.docx` is the editable single-column report; `Smart_Parking_Final_Report.pdf` is the rendered A4 copy.
- `hardware/` contains the pin map, validation notes, and editable Graphviz source plus SVG diagrams. Rendered PNGs and real experiment charts are in `figures/`.
- `demo/` contains verified software demonstration commands, scenario checklist, and limitations. Physical tests remain marked not tested.
- `SUBMISSION_CHECKLIST.md` separates completed deliverables from manual institutional and bench validation.

Regenerate the report without rerunning completed experiments with `make final-submission` (after installing the optional `review` dependency from `pyproject.toml`). The raw and feature datasets and the measured result tables remain under `../dataset/`, `../ml_results/`, and `../optimization_results/`. The report points to the institution-restricted Google Drive archive already documented in `EXPERIMENTAL_REPORT.md`.
