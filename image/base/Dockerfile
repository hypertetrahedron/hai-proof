# hai-proof control image: plain Claude Code on a pinned toolchain. Nothing treatment-specific.
ARG CLAUDE_CODE_VERSION
FROM python:3.12-slim-bookworm

# Re-declare after FROM so it is visible inside the build stage.
ARG CLAUDE_CODE_VERSION
ARG NODE_VERSION=22.12.0
ARG UV_VERSION=0.8.0

RUN test -n "${CLAUDE_CODE_VERSION}" || (echo "CLAUDE_CODE_VERSION build arg is required" >&2; exit 1)

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates procps tini \
 && rm -rf /var/lib/apt/lists/*

# Node.js (official binary tarball, arch-aware, pinned)
RUN set -eux; \
    case "$(dpkg --print-architecture)" in \
      amd64) NODE_ARCH=x64 ;; \
      arm64) NODE_ARCH=arm64 ;; \
      *) echo "unsupported architecture" >&2; exit 1 ;; \
    esac; \
    curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${NODE_ARCH}.tar.gz" -o /tmp/node.tgz; \
    tar -xzf /tmp/node.tgz -C /usr/local --strip-components=1 --no-same-owner; \
    rm /tmp/node.tgz; \
    node --version; npm --version

RUN pip install --no-cache-dir "uv==${UV_VERSION}"

RUN npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
 && npm cache clean --force \
 && claude --version

# Non-root user (Claude Code refuses bypassPermissions as root)
RUN groupadd -g 1000 agent \
 && useradd -m -u 1000 -g 1000 -s /bin/bash -d /home/agent agent \
 && mkdir -p /home/agent/.claude /work /out /tp \
 && python -m venv /opt/venv \
 && chown -R agent:agent /home/agent /work /out /tp /opt/venv

ENV HOME=/home/agent \
    VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:$PATH \
    DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    CLAUDE_CODE_DISABLE_AUTO_MEMORY=1

COPY hai_proof_wrap.py hai_proof_grade.py /usr/local/bin/
RUN chmod 0755 /usr/local/bin/hai_proof_wrap.py /usr/local/bin/hai_proof_grade.py

USER agent
RUN git config --global user.name hai-proof \
 && git config --global user.email hai-proof@localhost \
 && git config --global init.defaultBranch main \
 && git config --global --add safe.directory "*"

WORKDIR /work
LABEL hai-proof.role=base
ENTRYPOINT ["tini","--"]
CMD ["sleep","infinity"]
