# Final submission report sources

The report generator is `scripts/build_final_submission.py`. Generate a fresh,
editable report and PDF without touching the preserved review artifacts with:

```bash
.venv/bin/python -m scripts.build_final_submission --output-directory output/final_submission
```

The generated files are `output/final_submission/Smart_Parking_Final_Report.docx`
and `output/final_submission/Smart_Parking_Final_Report.pdf`. The report uses
grayscale copies of the original figures and reads the checked-in dataset,
prediction, and optimizer results. Copies of the metric CSV/JSON inputs are in
`output/final_submission/evidence/`.
`evidence/provenance.json` records their repository source paths and SHA-256
hashes so the copies can be compared with the input tables.

The checked-in DOCX/PDF in this directory are preserved as source artifacts.
The separately supplied clean PDF at the repository root is also preserved.
Neither is replaced by the regeneration command.

See `SUBMISSION_CHECKLIST.md` for completed work and manual requirements. The
literature entries added for this version were checked against publisher or
authoritative bibliographic pages; links and verification notes are in
`output/final_submission/REFERENCES_VERIFIED.md`.
