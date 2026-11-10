.PHONY: install test test-verbose lint clean run dry-run

install:
	pip install -r requirements.txt

test:
	python -m unittest discover -s tests

test-verbose:
	python -m unittest discover -s tests -v

lint:
	python -m py_compile src/*.py tests/*.py

clean:
	rm -rf __pycache__ src/__pycache__ tests/__pycache__ .venv output work scratch

run:
	python -m src.main

dry-run:
	DRY_RUN=true python -m src.main

verify-youtube:
	python -m src.youtube --verify