.PHONY: install test lint run review review-dataset review-ml review-package-models review-optimizers review-report

REVIEW_ROOT = review_outputs/2026-10-15
REVIEW_DB = sqlite:///$(REVIEW_ROOT)/dataset/review.db

install:
	python -m pip install -r requirements.txt

test:
	python -m pytest

lint:
	python -m ruff check .

run:
	python -m uvicorn backend.app.main:app --reload

review-dataset:
	python -m scripts.create_review_dataset

review-ml: review-dataset
	python -m scripts.train_prediction_models --database-url $(REVIEW_DB) --artifact-directory artifacts/prediction --results-directory $(REVIEW_ROOT)/ml_results

review-package-models: review-ml
	python -m scripts.package_prediction_artifacts --artifact-directory artifacts/prediction --output $(REVIEW_ROOT)/ml_results/prediction_model_artifacts.zip --results-csv $(REVIEW_ROOT)/ml_results/model_comparison.csv

review-optimizers:
	python -m scripts.run_optimizer_benchmarks --output-dir $(REVIEW_ROOT)/optimization_results --scenarios 120 --repeats 3

review-report:
	python -m scripts.generate_experimental_report --output-root $(REVIEW_ROOT)

review: review-package-models review-optimizers review-report
