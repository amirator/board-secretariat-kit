PY ?= python

.PHONY: help install demo test screenshots templates clean

help:          ## list targets
	@grep -E '^[a-z]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/ -/'

install:       ## install pinned dependencies
	$(PY) -m pip install -r requirements-dev.txt -c constraints.txt

demo:          ## run both sample meetings (PDFs too if LibreOffice is installed)
	$(PY) -m secretariat demo

test:          ## run the test suite
	$(PY) -m pytest -q

screenshots:   ## refresh docs/*.png and examples/ (needs LibreOffice and poppler)
	$(PY) scripts/make_screenshots.py

templates:     ## rebuild the Word templates from code (overwrites edits)
	$(PY) -m secretariat build-templates

clean:         ## delete generated outputs
	$(PY) -c "import shutil; shutil.rmtree('outputs', ignore_errors=True)"
