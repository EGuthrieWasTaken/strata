# syntax=docker/dockerfile:1
#
# openspec:container-image. One image that runs every `strata` command and the local web UI
# against a repository mounted at /review. Build:
#
#   docker build -t strata .
#
# The base image should be pinned by digest (`python:3.12-slim@sha256:...`); dependabot's docker
# ecosystem keeps a pinned digest current. Until a digest is recorded here the tag floats, which
# openspec:container-image#published-multi-architecture-image does not allow for a release image.
ARG PYTHON_IMAGE=python:3.12-slim

# ---- build: the locked dependency set and the package, with the tools that need to compile ----
FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.11.32 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/strata
WORKDIR /src
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
# --frozen: exactly the versions in uv.lock, never re-resolved. No dev dependencies, not editable.
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime: the virtualenv and git, nothing to build with ----
FROM ${PYTHON_IMAGE}
# git is whatever the base image's Debian release ships (the spec asks for 2.23 or newer, not an
# exact version), so the apt package is deliberately unpinned.
# hadolint ignore=DL3008
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    # Mounted repositories belong to whoever mounted them, not to uid 10001, and git refuses a
    # repository owned by another uid ("dubious ownership"). The setting lives in the container's
    # system config, which only ever sees repositories the operator chose to mount.
    && git config --system --add safe.directory '*' \
    && useradd --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin strata \
    # HOME must be writable under any `--user uid:gid` so git can run; sticky and world-writable
    # like /tmp, and empty: it holds no credentials and nothing the image needs.
    && mkdir -m 1777 /home-strata /review \
    && chown 10001:10001 /review

COPY --from=build /opt/strata /opt/strata
COPY docker/entrypoint.sh /usr/local/bin/strata-entrypoint

ENV PATH=/opt/strata/bin:$PATH \
    HOME=/home-strata \
    PYTHONUNBUFFERED=1 \
    STRATA_PORT=8765

USER 10001:10001
WORKDIR /review
EXPOSE 8765

# Meaningful when the container runs `serve`; a one-off command has exited long before the first probe.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('STRATA_PORT', '8765'), timeout=4)"]

ENTRYPOINT ["strata-entrypoint"]
CMD ["--help"]
