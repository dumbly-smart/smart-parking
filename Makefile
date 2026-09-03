.PHONY: install test lint run

install:
	python -m pip install -r requirements.txt

test:
	python -m pytest

lint:
	python -m ruff check .

run:
	python -m uvicorn backend.app.main:app --reload
