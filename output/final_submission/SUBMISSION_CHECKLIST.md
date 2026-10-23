# Final submission checklist

## Report and evidence

- [x] Editable A4 single-column DOCX and rendered PDF generated under `output/final_submission/`.
- [x] Abstract is 250 words and has nine keywords.
- [x] Report includes the requested architecture, hardware, software/ML, implementation, experimental setup, results, and conclusion sections.
- [x] Student name and registration number are set to Akil and 25BCE2777; unknown institution, course, and faculty fields remain editable.
- [x] Recent literature table contains five 2022–2024 papers with verified publication metadata and DOI links recorded in `REFERENCES_VERIFIED.md`.
- [x] Forecasting is evaluated with MAE, MSE, and RMSE. No classification confusion matrix or ROC result is manufactured for the regression target.
- [x] Synthetic dataset and optimizer evidence tables are copied into `output/final_submission/evidence/` with their original filenames.
- [x] Report figures and typography are monochrome; the original report images and checked-in DOCX/PDF are preserved.
- [x] Public, version-pinned dataset download is included. The Google Drive copy is described as institution-restricted.

## Still required before academic submission

- [ ] Fill in the institution, course, and faculty/guide fields.
- [ ] Apply the institution's required base-paper/report template; no template was present in the repository.
- [ ] Confirm Google Drive access using the professor's account if Drive submission is required.
- [x] Re-ran `make test` (257 passed), `make lint`, both firmware build targets, `make final-submission`, and `git diff --check` after integration changes. Keep command logs if the evaluator requests them; no standalone log files were generated.
- [ ] Complete supervised bench tests for the exact controller/camera boards, RFID reader, OLED, five LEDs, and unloaded tabletop servo. Firmware compilation and a USB adapter do not verify hardware behavior.
- [ ] Calibrate the camera ROIs on the actual fixed scene and evaluate occupancy against labeled real images before reporting camera accuracy.
- [ ] Collect genuine hardware latency, recovery, RFID-read, LED correctness, camera processing, servo timing, memory, and power records. `output/hardware/hardware_summary.json` records zero captured events and all 12 metrics as `NOT TESTED`.
- [ ] Obtain permissioned real occupancy data before making deployment claims; all bundled ML and optimizer datasets are synthetic/simulated.
- [ ] Review final author details, citations, page layout, and figure legibility against the professor's submission instructions.
