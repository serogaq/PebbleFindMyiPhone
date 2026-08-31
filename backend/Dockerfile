# Fallback for direct Docker builds; make backend-build overrides this value
# from the repository's toolchain.env.
ARG PYTHON_BASE_IMAGE=python:3.12.14-slim-bookworm@sha256:0f5b26b9518d002b6173fd61daad821fa340635ebfec5bba471013f9ca114579
FROM ${PYTHON_BASE_IMAGE}

ARG IMAGE_VERSION=development

LABEL org.opencontainers.image.title="Pebble Find My iPhone backend" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.description="Authenticated Apple Find My Play Sound bridge" \
      org.opencontainers.image.authors="serogaq" \
      org.opencontainers.image.licenses="PolyForm-Noncommercial-1.0.0" \
      io.github.serogaq.required-notice="Required Notice: Copyright © serogaq (https://github.com/serogaq/PebbleFindMyiPhone)"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

RUN if command -v groupadd >/dev/null 2>&1; then \
        groupadd --gid 10001 findmy \
        && useradd --uid 10001 --gid findmy --no-create-home --home-dir /nonexistent findmy; \
    else \
        addgroup -g 10001 -S findmy \
        && adduser -u 10001 -S -D -H -h /nonexistent -G findmy findmy; \
    fi \
    && mkdir -p /app /var/lib/find-my/session \
    && chown -R findmy:findmy /app /var/lib/find-my

WORKDIR /app

COPY backend/requirements.lock ./
RUN pip install --no-cache-dir --require-hashes --requirement requirements.lock

COPY backend/src ./src
COPY LICENSE.md NOTICE /usr/share/licenses/pebble-find-my-iphone/

USER findmy

ENTRYPOINT ["python", "-m", "findmy_backend"]
CMD ["serve"]
