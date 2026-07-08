# MedEasy Health OS — Development Makefile

.PHONY: run prod test info

## Start the development server
run:
	python app.py

## Run with debug off (requires SECRET_KEY in env)
prod:
	FLASK_DEBUG=0 python app.py

## Run the test suite
test:
	pytest tests/ -q

## Show project stats
info:
	@echo "JS bundle:"
	@wc -l static/js/app.js
	@echo "CSS bundle:"
	@wc -l static/css/style.css
	@echo "DB size:"
	@ls -lh medeasy.db 2>/dev/null || echo "  not created yet"
