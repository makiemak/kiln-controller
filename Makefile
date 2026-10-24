VENV := venv
PYTHON := $(VENV)/bin/python3
UV := uv

.PHONY: test lint dev-setup docker-legacy-build docker-legacy-run docker-legacy-test

test:
	$(UV) run pytest Test -q

lint:
	$(UV) run ruff check .

dev-setup:
	UV_PROJECT_ENVIRONMENT=$(VENV) $(UV) sync

# rehearse a 25.10.x release with the pi's exact python and libraries,
# using the kiln's real config.py and profiles from $(BACKUP_DIR).
# HW=1 runs RealOven against the fake hardware in docker/fakehw.
LEGACY_IMAGE ?= kiln-controller-legacy:25.10
REF ?= v25.10.0
HW ?= 0
BACKUP_DIR ?= ../kiln-backups

docker-legacy-build:
	docker build -t $(LEGACY_IMAGE) docker/legacy

docker-legacy-run:
	LEGACY_IMAGE=$(LEGACY_IMAGE) BACKUP_DIR=$(BACKUP_DIR) docker/legacy/run.sh run $(REF) $(if $(filter 1,$(HW)),hw,sim)

docker-legacy-test:
	LEGACY_IMAGE=$(LEGACY_IMAGE) BACKUP_DIR=$(BACKUP_DIR) docker/legacy/run.sh test $(REF)
