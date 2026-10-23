.PHONY: install test lint run review review-dataset review-ml review-package-models review-optimizers review-report final-submission camera-ingest calibrate-rois hardware-capture hardware-summary firmware-controller firmware-camera

REVIEW_ROOT = review_outputs/2026-10-15
REVIEW_DB = sqlite:///$(REVIEW_ROOT)/dataset/review.db
PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
PIO ?= $(shell command -v pio 2>/dev/null || printf '%s' '.venv/bin/pio')

install:
	$(PYTHON) -m pip install -r requirements.txt

test:
	$(PYTHON) -m pytest

lint:
	$(PYTHON) -m ruff check .

run:
	$(PYTHON) -m uvicorn backend.app.main:app --reload

review-dataset:
	$(PYTHON) -m scripts.create_review_dataset

review-ml: review-dataset
	$(PYTHON) -m scripts.train_prediction_models --database-url $(REVIEW_DB) --artifact-directory artifacts/prediction --results-directory $(REVIEW_ROOT)/ml_results

review-package-models: review-ml
	$(PYTHON) -m scripts.package_prediction_artifacts --artifact-directory artifacts/prediction --output $(REVIEW_ROOT)/ml_results/prediction_model_artifacts.zip --results-csv $(REVIEW_ROOT)/ml_results/model_comparison.csv

review-optimizers:
	$(PYTHON) -m scripts.run_optimizer_benchmarks --output-dir $(REVIEW_ROOT)/optimization_results --scenarios 120 --repeats 3

review-report:
	$(PYTHON) -m scripts.generate_experimental_report --output-root $(REVIEW_ROOT)

review: review-package-models review-optimizers review-report

final-submission:
	$(PYTHON) -m scripts.build_final_submission

camera-ingest:
	$(PYTHON) -m scripts.camera_ingest

calibrate-rois:
	$(PYTHON) -m scripts.calibrate_camera_rois

hardware-capture:
	$(PYTHON) -m scripts.hardware_evaluation capture --port $(PORT) --output $(OUTPUT)

hardware-summary:
	$(PYTHON) -m scripts.hardware_evaluation summarize --input $(INPUT) --output-directory $(OUTPUT_DIR)

firmware-controller:
	$(PIO) run -d firmware/esp32_controller

firmware-camera:
	$(PIO) run -d firmware/esp32_cam
