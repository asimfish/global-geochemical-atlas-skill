FROM python:3.12-slim

ARG OPENCODE_VERSION=1.18.14

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git nodejs npm \
    && rm -rf /var/lib/apt/lists/* \
    && npm install --global "opencode-ai@${OPENCODE_VERSION}" \
    && npm cache clean --force \
    && groupadd --gid 1000 opencode \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/sh opencode \
    && mkdir -p /run/secrets \
    && chown -R 1000:1000 /run/secrets

COPY opencode.json /opt/model-gateway/opencode.json
COPY model-policy.json /opt/model-gateway/model-policy.json
COPY probe.py /opt/model-gateway/probe.py
COPY container-entrypoint.sh /usr/local/bin/model-gateway-entrypoint

RUN chmod 0555 /usr/local/bin/model-gateway-entrypoint \
    && chmod 0444 /opt/model-gateway/opencode.json \
                  /opt/model-gateway/model-policy.json \
                  /opt/model-gateway/probe.py

USER 1000:1000
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/model-gateway-entrypoint"]
CMD ["probe"]
