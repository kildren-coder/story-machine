# Sandbox image for AFK research runs (sandcastle). story-machine has no code
# yet — the research agent only needs git/gh + the Claude Code CLI, plus web
# egress for research (WebFetch/curl). When the MVP coding phase starts, add
# the project's Python layer here (mirroring the pipeline's runtime image).
FROM node:22-slim

# git: sandcastle worktree ops. gh: agent comments on issues when blocked.
# jq/curl: prompt & agent tooling (and source-link spot checks).
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl jq ca-certificates \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

# Claude Code refuses to run with permissions bypassed as root.
RUN useradd -m agent
USER agent
WORKDIR /home/agent

# sandcastle creates the container without a command override and expects it
# to stay alive; the node base image's default (node REPL) exits immediately.
CMD ["sleep", "infinity"]
