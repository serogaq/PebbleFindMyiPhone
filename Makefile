.POSIX:
SHELL = /bin/sh

include toolchain.env

PYTHON ?= $(PYTHON_VERSION)
UV ?= uv
UVX ?= uvx
NPM ?= npm
NODE ?= node
PEBBLE ?= pebble
DOCKER ?= docker
DOCKER_COMPOSE ?= docker compose

BACKEND_VENV ?= backend/.venv
BACKEND_PYTHON = $(BACKEND_VENV)/bin/python
BACKEND_DEPS_STAMP = $(BACKEND_VENV)/.requirements-dev.stamp
APP_DEPS_STAMP = app/node_modules/.package-lock.stamp

# Pebble Time 2. Override with, for example, PLATFORM=gabbro.
PLATFORM ?= emery
PBW ?= app/build/app.pbw
IP ?=
QEMU_FLAGS ?=
LOG_FLAGS ?=
BACKEND_IMAGE ?= pebble-find-my-iphone-backend
BACKEND_TAG ?= latest
BACKEND_PLATFORMS ?=
BACKEND_BUILD_FLAGS ?=
PYTHON_BASE_IMAGE ?= python:$(PYTHON_VERSION)-slim-bookworm

.PHONY: help backend-deps app-node-check app-deps backend-test backend-audit \
	app-test app-eslint app-audit backend-build app-build app-qemu app-install

help:
	@printf '%s\n' \
		'Development targets:' \
		'  make backend-test                 Run backend unit/integration tests' \
		'  make backend-audit                Run backend lint, security and dependency audits' \
		'  make app-test                     Run PebbleKit JS tests' \
		'  make app-eslint                   Run ESLint for the Pebble app' \
		'  make app-audit                    Audit app production and development dependencies' \
		'  make backend-build [BACKEND_IMAGE=name] [BACKEND_TAG=tag] [BACKEND_PLATFORMS=list]' \
		'  make app-build                    Build app/build/app.pbw' \
		'  make app-qemu [PLATFORM=emery] [PBW=path] [QEMU_FLAGS=--vnc]' \
		'  make app-install [IP=phone-ip] [PBW=path] [LOG_FLAGS=--no-color]'

$(BACKEND_DEPS_STAMP): backend/requirements.txt backend/requirements-dev.txt
	@command -v "$(UV)" >/dev/null 2>&1 || { printf '%s\n' 'error: uv is required'; exit 1; }
	@test -x "$(BACKEND_PYTHON)" || "$(UV)" venv --python "$(PYTHON)" "$(BACKEND_VENV)"
	"$(UV)" pip install --python "$(BACKEND_PYTHON)" -r backend/requirements-dev.txt
	@touch "$(BACKEND_DEPS_STAMP)"

backend-deps: $(BACKEND_DEPS_STAMP)

$(APP_DEPS_STAMP): app/package.json app/package-lock.json
	@command -v "$(NPM)" >/dev/null 2>&1 || { printf '%s\n' 'error: npm is required'; exit 1; }
	cd app && "$(NPM)" ci
	@touch "$(APP_DEPS_STAMP)"

app-node-check:
	@command -v "$(NODE)" >/dev/null 2>&1 || { printf '%s\n' 'error: Node.js is required'; exit 1; }
	@"$(NODE)" -e "var v=process.versions.node.split('.').map(Number); var ok=(v[0]===20&&v[1]>=19)||(v[0]===22&&v[1]>=13)||v[0]>=24; if(!ok){console.error('error: Node.js 20.19+, 22.13+, or 24+ is required; current: '+process.versions.node);process.exit(1)}"

app-deps: app-node-check $(APP_DEPS_STAMP)

backend-test: backend-deps
	cd backend && PYTHONPATH=src "$(CURDIR)/$(BACKEND_PYTHON)" -m pytest -q tests

backend-audit: backend-deps
	cd backend && "$(CURDIR)/$(BACKEND_VENV)/bin/ruff" format --check src tests
	cd backend && "$(CURDIR)/$(BACKEND_VENV)/bin/ruff" check src tests
	cd backend && "$(CURDIR)/$(BACKEND_VENV)/bin/bandit" -q -r src
	"$(UVX)" --from pip-audit==$(PIP_AUDIT_VERSION) pip-audit -r backend/requirements.lock
	cd backend && APPLE_ID=ci@example.invalid API_TOKEN=00000000000000000000000000000000 TARGET_DEVICE_ID=ci-target $(DOCKER_COMPOSE) config --quiet
	cd backend && APPLE_ID=ci@example.invalid API_TOKEN=00000000000000000000000000000000 TARGET_DEVICE_ID=ci-target $(DOCKER_COMPOSE) -f docker-compose.yaml -f docker-compose.local.yaml config --quiet
	cd backend && APPLE_ID=ci@example.invalid API_TOKEN=00000000000000000000000000000000 TARGET_DEVICE_ID=ci-target $(DOCKER_COMPOSE) -f docker-compose.yaml -f docker-compose.secrets.yaml config --quiet

app-test: app-deps
	cd app && "$(NPM)" test

app-eslint: app-deps
	cd app && "$(NPM)" run lint

app-audit: app-deps
	cd app && "$(NPM)" audit --omit=dev
	cd app && "$(NPM)" audit

backend-build:
	@if test -n "$(BACKEND_PLATFORMS)"; then \
		"$(DOCKER)" buildx build --platform "$(BACKEND_PLATFORMS)" $(BACKEND_BUILD_FLAGS) --build-arg "PYTHON_BASE_IMAGE=$(PYTHON_BASE_IMAGE)" --build-arg "IMAGE_VERSION=$(BACKEND_TAG)" --tag "$(BACKEND_IMAGE):$(BACKEND_TAG)" --file backend/Dockerfile .; \
	else \
		"$(DOCKER)" build $(BACKEND_BUILD_FLAGS) --build-arg "PYTHON_BASE_IMAGE=$(PYTHON_BASE_IMAGE)" --build-arg "IMAGE_VERSION=$(BACKEND_TAG)" --tag "$(BACKEND_IMAGE):$(BACKEND_TAG)" --file backend/Dockerfile .; \
	fi

app-build: app-deps
	cd app && "$(NPM)" run build

app-qemu:
	@command -v "$(PEBBLE)" >/dev/null 2>&1 || { printf '%s\n' 'error: pebble CLI is required'; exit 1; }
	@test -f "$(PBW)" || { printf 'error: PBW not found: %s\nRun make app-build first or set PBW=/path/to/app.pbw\n' "$(PBW)"; exit 1; }
	"$(PEBBLE)" install "$(PBW)" --emulator "$(PLATFORM)" $(QEMU_FLAGS)

app-install:
	@command -v "$(PEBBLE)" >/dev/null 2>&1 || { printf '%s\n' 'error: pebble CLI is required'; exit 1; }
	@test -f "$(PBW)" || { printf 'error: PBW not found: %s\nRun make app-build first or set PBW=/path/to/app.pbw\n' "$(PBW)"; exit 1; }
	@if test -n "$(IP)"; then \
		printf 'Using local Pebble developer connection at %s\n' "$(IP)"; \
		"$(PEBBLE)" ping --phone "$(IP)"; \
		"$(PEBBLE)" install "$(PBW)" --phone "$(IP)"; \
		"$(PEBBLE)" logs --phone "$(IP)" $(LOG_FLAGS); \
	else \
		"$(PEBBLE)" login --status >/dev/null 2>&1 || { printf '%s\n' 'error: Pebble CLI is not logged in; run pebble login'; exit 1; }; \
		"$(PEBBLE)" ping --cloudpebble; \
		"$(PEBBLE)" install "$(PBW)" --cloudpebble; \
		"$(PEBBLE)" logs --cloudpebble $(LOG_FLAGS); \
	fi
