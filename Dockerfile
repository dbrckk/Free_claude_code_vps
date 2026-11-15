FROM node:24.22.1-trixie-slim@sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a AS node
WORKDIR /opt/harness/runtime
COPY runtime/package*.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM python:3.14.10-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f
ARG TARGETARCH
ARG FCC_VERSION=6.19.31
ARG FCC_SHA256=457d3a4ce9cd50534633fcf149fd3ec981dec9dc4a4b25886fca8e085672a620
ARG CADDY_VERSION=2.11.9
ENV PATH="/opt/harness/runtime/node_modules/.bin:${PATH}" \
    HOME=/data/home DATA_DIR=/data PORT=10000 PYTHONUNBUFFERED=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl fd-find ffmpeg gh git jq openssh-client ripgrep tini \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd \
    && useradd --uid 10001 --user-group --home-dir /data/home --no-create-home --shell /bin/bash harness \
    && install -d -o harness -g harness -m 0700 /data /data/home
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx
COPY --from=node /opt/harness/runtime /opt/harness/runtime
COPY runtime/fcc-dependencies.txt /tmp/fcc-dependencies.txt
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) caddy_sha=5b8cb7faf8726a2028ad96a66e54e6e81e8f361bc6175e5d22bbd997cc5177fb ;; \
      arm64) caddy_sha=5e377cff994fc9362a6fcf695c53f226cfca3a3ef85bd3a3687cf252d6310165 ;; \
      *) echo "Unsupported architecture: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    curl -fsSL --retry 3 "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_${TARGETARCH}.tar.gz" -o /tmp/caddy.tar.gz; \
    echo "${caddy_sha}  /tmp/caddy.tar.gz" | sha256sum -c -; \
    tar -xzf /tmp/caddy.tar.gz -C /usr/local/bin caddy; \
    wheel="free_claude_code-${FCC_VERSION}-py3-none-any.whl"; \
    curl -fsSL --retry 3 "https://github.com/Alishahryar1/free-claude-code/releases/download/v${FCC_VERSION}/${wheel}" -o "/tmp/${wheel}"; \
    echo "${FCC_SHA256}  /tmp/${wheel}" | sha256sum -c -; \
    pip install --no-cache-dir -c /tmp/fcc-dependencies.txt "/tmp/${wheel}" python-docx python-pptx openpyxl pypdf; \
    pip check; \
    rm -f /tmp/caddy.tar.gz "/tmp/${wheel}" /tmp/fcc-dependencies.txt
WORKDIR /opt/harness
COPY config config
COPY scripts scripts
USER harness
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=150s --retries=3 \
  CMD ["python", "/opt/harness/scripts/run.py", "health"]
ENTRYPOINT ["/usr/bin/tini", "--", "python", "/opt/harness/scripts/run.py"]
