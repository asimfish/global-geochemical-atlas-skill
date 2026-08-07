ARG PYTHON_IMAGE=python:3.11.9-slim-bookworm
FROM ${PYTHON_IMAGE}

ARG OPENCODE_VERSION=1.18.14

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HOME=/tmp/home \
    XDG_CONFIG_HOME=/tmp/home/.config \
    XDG_DATA_HOME=/tmp/home/.local/share \
    XDG_CACHE_HOME=/tmp/home/.cache \
    OPENCODE_DISABLE_AUTOUPDATE=1 \
    OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1 \
    OPENCODE_DISABLE_EXTERNAL_SKILLS=1 \
    OPENCODE_DISABLE_LSP_DOWNLOAD=1 \
    OPENCODE_DISABLE_MODELS_FETCH=1 \
    OPENCODE_DISABLE_SHARE=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates chromium chromium-driver git nodejs npm ripgrep tini \
    && rm -rf /var/lib/apt/lists/*

RUN npm install --global "opencode-ai@${OPENCODE_VERSION}" \
    && opencode --version \
    && npm cache clean --force

COPY requirements-sandbox.txt /opt/evaluation/requirements-sandbox.txt
RUN python -m pip install --no-cache-dir -r /opt/evaluation/requirements-sandbox.txt

RUN chromium --version && chromedriver --version

COPY container/ /opt/evaluation/container/
COPY provider_profiles.json provider_profiles.schema.json provider_profiles.py /opt/evaluation/

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin candidate \
    && chmod -R a=rX /opt/evaluation

WORKDIR /workspace
USER candidate
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "/opt/evaluation/container/run_opencode.py"]
