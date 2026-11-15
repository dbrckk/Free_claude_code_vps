FROM python:3.12.14-slim-trixie@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f AS project-python
FROM eclipse-temurin:17-jdk-noble@sha256:1bedb04434bd275ef072355e9caec2a22be5240fbe82ad51a59323f2bbcab4a6 AS java

FROM node:24.22.1-trixie-slim@sha256:89c5244bc22a9bc3287d89ebc7e49b9cb5bb84cd40e6175ac3421d5a9f68b95a AS node
WORKDIR /opt/harness/runtime
COPY runtime/package*.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM debian:trixie-slim AS portfolio-tools
ARG TARGETARCH
COPY scripts/install-tools.sh /tmp/install-tools.sh
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl unzip \
    && if [ "$TARGETARCH" = arm64 ]; then apt-get install -y --no-install-recommends cmake g++ make; fi
RUN sh /tmp/install-tools.sh "$TARGETARCH" /portfolio/bin
ARG STAR_LIST_REV=b1f12e3e6303762126c807c10c46af4c5cbf417b
ARG STAR_LIST_SHA=a8e4f64828a8da082e36ff74bccabf921a982c596a8e42878fec8b7d06f8b7bc
RUN curl -fsSL --retry 3 "https://codeload.github.com/dbrckk/star-list/tar.gz/$STAR_LIST_REV" -o /tmp/star-list.tgz \
    && echo "$STAR_LIST_SHA  /tmp/star-list.tgz" | sha256sum -c - \
    && mkdir -p /portfolio/star-list \
    && tar -xzf /tmp/star-list.tgz -C /portfolio/star-list --strip-components=1 --wildcards \
        '*/catalog.json' '*/catalog-readme-evidence.json' '*/history.json' '*/stacks.json' '*/websites.json' '*/agent-skills.json' '*/scripts/*.py' \
    && printf '%s\n' "$STAR_LIST_REV" > /portfolio/star-list/REVISION

FROM portfolio-tools AS godot-tool
RUN sh /tmp/install-tools.sh "$TARGETARCH" /godot godot

FROM python:3.14.10-slim-trixie@sha256:9aaa474097d094040649f2162a627c0049b408f52138d980916788d80f04802f AS base
ARG TARGETARCH
ARG FCC_VERSION=6.19.31
ARG FCC_SHA256=457d3a4ce9cd50534633fcf149fd3ec981dec9dc4a4b25886fca8e085672a620
ARG CADDY_VERSION=2.11.9
ENV PATH="/opt/harness/runtime/node_modules/.bin:${PATH}:/opt/python312/bin" \
    HOME=/data/home DATA_DIR=/data PORT=10000 PYTHONUNBUFFERED=1 \
    DSH_BUNDLED_SKILL_DIR=/opt/harness/config/skills UV_PYTHON=/opt/python312/bin/python3.12
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl espeak-ng fd-find ffmpeg fonts-dejavu-core gh git jq openssh-client ripgrep shellcheck tini unzip \
    && rm -rf /var/lib/apt/lists/* \
    && ln -s /usr/bin/fdfind /usr/local/bin/fd \
    && useradd --uid 10001 --user-group --home-dir /data/home --no-create-home --shell /bin/bash harness \
    && install -d -o harness -g harness -m 0700 /data /data/home
COPY --from=project-python /usr/local /opt/python312
COPY --from=portfolio-tools /portfolio/bin /usr/local/bin
COPY --from=portfolio-tools /portfolio/star-list /opt/harness/star-list
RUN ln -s /opt/python312/bin/python3.12 /usr/local/bin/python3.12 \
    && printf "%s\n" /opt/python312/lib > /etc/ld.so.conf.d/python312.conf \
    && ldconfig \
    && python3.12 --version
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
RUN install -m 0755 scripts/star-list scripts/portfolio-doctor /usr/local/bin/ \
    && rojo --version \
    && luau-compile --help >/dev/null \
    && uv --version \
    && ast-grep --version \
    && repomix --version \
    && star-list "Roblox Luau" --top 1 --json >/dev/null
USER harness
EXPOSE 10000
HEALTHCHECK --interval=30s --timeout=5s --start-period=150s --retries=3 \
  CMD ["python", "/opt/harness/scripts/run.py", "health"]
ENTRYPOINT ["/usr/bin/tini", "--", "python", "/opt/harness/scripts/run.py"]

FROM base AS vps
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends blender chromium fonts-liberation libasound2t64 libfontconfig1 libgl1 libx11-6 libxcursor1 libxi6 libxinerama1 libxrandr2 libxrender1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=godot-tool /godot/ /usr/local/bin/
COPY --from=java /opt/java/openjdk /opt/java/openjdk
ENV JAVA_HOME=/opt/java/openjdk PATH="/opt/java/openjdk/bin:${PATH}" CHROME_PATH=/usr/bin/chromium
RUN godot-4.5.1 --version && godot-4.6 --version && java -version
USER harness

FROM base AS render
