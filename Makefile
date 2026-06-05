# AlpacaTrader — dev tasks (AH-4). The venv Python + PYTHONPATH split is required
# (Homebrew Python vs venv site-packages) — see CLAUDE.md.
PY        := venv/bin/python3.11
PYPATH    := venv/lib/python3.11/site-packages

.PHONY: install-dev test test-q smoke

install-dev:        ## one-time: install runtime + test deps
	$(PY) -m pip install -r requirements.txt -r requirements-dev.txt

test:               ## run the full hermetic test suite (verbose)
	PYTHONPATH=$(PYPATH) $(PY) -m pytest tests/ -v

test-q:             ## run the suite quietly (CI / pre-push)
	PYTHONPATH=$(PYPATH) $(PY) -m pytest tests/ -q

smoke:              ## import check — catches syntax errors before reload
	PYTHONPATH=$(PYPATH) $(PY) -c "import sys; sys.path.insert(0,'scripts'); import app; print('import OK')"
