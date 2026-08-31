.POSIX:
SHELL = /bin/sh

include toolchain.env

PYTHON ?= $(PYTHON_VERSION)
UV ?= uv
UVX ?= uvx
GO ?= go
NPM ?= npm
NODE ?= node
PEBBLE ?= pebble
DOCKER ?= docker
DOCKER_COMPOSE ?= docker compose

BACKEND_VENV ?= backend/.venv
BACKEND_PYTHON = $(BACKEND_VENV)/bin/python
BACKEND_DEPS_STAMP = $(BACKEND_VENV)/.requirements-dev.stamp
APP_DEPS_STAMP = app/node_modules/.package-lock.stamp
NODE_BIN_DIR = $(shell command -v "$(NODE)" 2>/dev/null | sed 's,/[^/]*$$,,')

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

.PHONY: help backend-deps app-node-check app-deps backend-test backend-audit \
	workflow-audit app-test app-eslint app-audit backend-build app-build app-qemu app-install

help:
	@printf '%s\n' \
		'Development targets:' \
		'  make backend-test                 Run backend unit/integration tests' \
		'  make backend-audit                Run backend lint, security and dependency audits' \
		'  make workflow-audit               Lint and security-audit GitHub Actions workflows' \
		'  make app-test                     Run PebbleKit JS tests' \
		'  make app-eslint                   Run ESLint for the Pebble app' \
		'  make app-audit                    Audit app production and development dependencies' \
		'  make backend-build [BACKEND_IMAGE=name] [BACKEND_TAG=tag] [BACKEND_PLATFORMS=list]' \
		'  make app-build                    Build app/build/app.pbw' \
		'  make app-qemu [PLATFORM=emery] [PBW=path] [QEMU_FLAGS=--vnc]' \
		'  make app-install [IP=phone-ip] [PBW=path] [LOG_FLAGS=--no-color]'

$(BACKEND_DEPS_STAMP): backend/requirements.txt backend/requirements.lock \
		backend/requirements-dev.txt backend/requirements-dev.lock \
		.github/scripts/verify_python_locks.py
	@command -v "$(UV)" >/dev/null 2>&1 || { printf '%s\n' 'error: uv is required'; exit 1; }
	@python3 .github/scripts/verify_python_locks.py \
		backend/requirements.txt backend/requirements.lock \
		backend/requirements-dev.txt backend/requirements-dev.lock
	@test -x "$(BACKEND_PYTHON)" || "$(UV)" venv --python "$(PYTHON)" "$(BACKEND_VENV)"
	"$(UV)" pip install --python "$(BACKEND_PYTHON)" --require-hashes \
		-r backend/requirements-dev.lock
	@touch "$(BACKEND_DEPS_STAMP)"

backend-deps: $(BACKEND_DEPS_STAMP)

$(APP_DEPS_STAMP): app/package.json app/package-lock.json
	@command -v "$(NPM)" >/dev/null 2>&1 || { printf '%s\n' 'error: npm is required'; exit 1; }
	cd app && PATH="$(NODE_BIN_DIR):$$PATH" "$(NPM)" ci --no-audit --no-fund
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
	"$(UVX)" --from pip-audit==$(PIP_AUDIT_VERSION) pip-audit --no-deps --disable-pip -r backend/requirements.lock
	"$(UVX)" --from pip-audit==$(PIP_AUDIT_VERSION) pip-audit --no-deps --disable-pip -r backend/requirements-dev.lock
	"$(UV)" pip check --python "$(BACKEND_PYTHON)"
	@test "$$(sed -n 's/^ARG PYTHON_BASE_IMAGE=//p' backend/Dockerfile)" = "$(PYTHON_BASE_IMAGE)" || { printf '%s\n' 'error: backend/Dockerfile base image must match toolchain.env'; exit 1; }
	cd backend && APPLE_ID=ci@example.invalid API_TOKEN=00000000000000000000000000000000 TARGET_DEVICE_ID=ci-target $(DOCKER_COMPOSE) config --quiet
	cd backend && APPLE_ID=ci@example.invalid API_TOKEN=00000000000000000000000000000000 TARGET_DEVICE_ID=ci-target $(DOCKER_COMPOSE) -f docker-compose.yaml -f docker-compose.local.yaml config --quiet
	cd backend && APPLE_ID=ci@example.invalid API_TOKEN=00000000000000000000000000000000 TARGET_DEVICE_ID=ci-target $(DOCKER_COMPOSE) -f docker-compose.yaml -f docker-compose.secrets.yaml config --quiet

workflow-audit:
	@command -v "$(UVX)" >/dev/null 2>&1 || { printf '%s\n' 'error: uvx is required for zizmor'; exit 1; }
	@if command -v actionlint >/dev/null 2>&1; then \
		actionlint; \
	elif command -v "$(GO)" >/dev/null 2>&1; then \
		"$(GO)" run "github.com/rhysd/actionlint/cmd/actionlint@v$(ACTIONLINT_VERSION)"; \
	elif command -v "$(DOCKER)" >/dev/null 2>&1; then \
		"$(DOCKER)" run --rm --volume "$(CURDIR):/repo:ro" --workdir /repo \
			"rhysd/actionlint:$(ACTIONLINT_VERSION)"; \
	else \
		printf '%s\n' 'error: actionlint, Go, or Docker is required for workflow audit' >&2; \
		exit 1; \
	fi
	"$(UVX)" --from "zizmor==$(ZIZMOR_VERSION)" zizmor --strict-collection .github

app-test: app-deps
	cd app && PATH="$(NODE_BIN_DIR):$$PATH" "$(NPM)" test

app-eslint: app-deps
	cd app && PATH="$(NODE_BIN_DIR):$$PATH" "$(NPM)" run lint

app-audit: app-deps
	cd app && PATH="$(NODE_BIN_DIR):$$PATH" "$(NPM)" audit --omit=dev --fetch-timeout=30000 --fetch-retries=1
	cd app && PATH="$(NODE_BIN_DIR):$$PATH" "$(NPM)" audit --fetch-timeout=30000 --fetch-retries=1

backend-build:
	@if test -n "$(BACKEND_PLATFORMS)"; then \
		"$(DOCKER)" buildx build --platform "$(BACKEND_PLATFORMS)" $(BACKEND_BUILD_FLAGS) --build-arg "PYTHON_BASE_IMAGE=$(PYTHON_BASE_IMAGE)" --build-arg "IMAGE_VERSION=$(BACKEND_TAG)" --tag "$(BACKEND_IMAGE):$(BACKEND_TAG)" --file backend/Dockerfile .; \
	else \
		"$(DOCKER)" build $(BACKEND_BUILD_FLAGS) --build-arg "PYTHON_BASE_IMAGE=$(PYTHON_BASE_IMAGE)" --build-arg "IMAGE_VERSION=$(BACKEND_TAG)" --tag "$(BACKEND_IMAGE):$(BACKEND_TAG)" --file backend/Dockerfile .; \
	fi

app-build: app-deps
	cd app && NODE="$(NODE)" NPM_CONFIG_AUDIT=false NPM_CONFIG_FUND=false \
		NPM_CONFIG_PACKAGE_LOCK=false \
		NPM_CONFIG_FETCH_TIMEOUT=30000 NPM_CONFIG_FETCH_RETRIES=1 \
		PATH="$(NODE_BIN_DIR):$$PATH" "$(NPM)" run build

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
