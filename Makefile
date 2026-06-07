# MediScan Health OS — Development Makefile

.PHONY: run build-js build-css build dev clean

## Start the development server
run:
	python app.py

## Rebuild JS bundle from modules
build-js:
	cat static/js/modules/*.js > static/js/app.js
	@echo "JS bundle rebuilt ($(shell wc -l < static/js/app.js) lines)"

## Rebuild CSS bundle from modules
build-css:
	cat static/css/modules/*.css > static/css/style.css
	@echo "CSS bundle rebuilt ($(shell wc -l < static/css/style.css) lines)"

## Rebuild everything
build: build-js build-css

## Dev mode: rebuild + run
dev: build run

## Run with debug off
prod:
	FLASK_DEBUG=0 python app.py

## Show bundle sizes
info:
	@echo "JS modules:"
	@wc -l static/js/modules/*.js | tail -1
	@echo "CSS modules:"
	@wc -l static/css/modules/*.css | tail -1
	@echo "DB size:"
	@ls -lh mediscan.db 2>/dev/null || echo "  not created yet"
