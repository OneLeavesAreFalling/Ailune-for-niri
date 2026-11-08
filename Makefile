SHELL := /bin/bash
ROOT := $(CURDIR)
PYTHON := $(ROOT)/.venv/bin/python
PYTHONPATH := $(ROOT)/python
GO ?= go
GOCACHE ?= $(ROOT)/.cache/go-build
export GOCACHE
export PYTHONPATH

.PHONY: help setup build run core ui pet service doctor test test-go test-py clean install-python

help:
	@echo "Ailune development targets"
	@echo "  make setup           Create the Python venv and build the Go binary"
	@echo "  make run             Run core + AI service + pet, then open the UI"
	@echo "  make core            Run the core in the foreground"
	@echo "  make ui              Run the settings/chat UI"
	@echo "  make pet             Run the pet shell"
	@echo "  make service         Run the AI service"
	@echo "  make doctor          Check dependencies and the Niri session"
	@echo "  make test            Run Go and Python tests"
	@echo "  make clean           Remove build artifacts"

setup:
	@bash scripts/setup.sh

build:
	@mkdir -p build
	$(GO) build -trimpath -o build/ailune ./cmd/ailune
	@echo "built build/ailune"

run: build
	@bash scripts/dev.sh

core: build
	@./build/ailune core

ui:
	@$(PYTHON) -m ailune.ui

pet:
	@$(PYTHON) -m ailune.pet

service:
	@$(PYTHON) -m ailune.service

doctor: build
	@./build/ailune doctor

test: test-go test-py

test-go:
	$(GO) test ./...

test-py:
	@cd python && ../.venv/bin/python -m pytest

install-python:
	@source .venv/bin/activate && uv pip install -e python

clean:
	@rm -rf build .cache/go-build .pytest_cache python/.pytest_cache
	@find python -name __pycache__ -type d -prune -exec rm -rf {} +
