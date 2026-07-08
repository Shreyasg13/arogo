# MedEasy Health OS — Development Makefile

.PHONY: run prod test test-js hooks info

## Start the development server
run:
	python app.py

## Run with debug off (requires SECRET_KEY in env)
prod:
	FLASK_DEBUG=0 python app.py

## Run the full test suite (Python + JS)
test:
	pytest tests/ -q
	node --check static/js/app.js
	node --check static/sw.js
	node tests/js/run_js_tests.mjs

## Run only the JS unit tests
test-js:
	node tests/js/run_js_tests.mjs

## Enable the pre-commit hook (runs `make test` before every commit)
hooks:
	git config core.hooksPath .githooks
	@echo "pre-commit hook enabled"

## Show project stats
info:
	@echo "JS bundle:"
	@wc -l static/js/app.js
	@echo "CSS bundle:"
	@wc -l static/css/style.css
	@echo "DB size:"
	@ls -lh medeasy.db 2>/dev/null || echo "  not created yet"
