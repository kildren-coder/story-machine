# AFK 沙箱镜像(sandcastle)。本仓库的可测代码是 Python(scripts/、pc/),全部
# 只用标准库;沙箱内跑 `bash scripts/test.sh` 即可,不需要 vault、不需要联网。
# 构建(必须在仓库根目录执行,docker provider 只认 `sandcastle:story-machine`):
#   ./.sandcastle/node_modules/.bin/sandcastle docker build-image
FROM python:3.11-slim

# git: sandcastle worktree 操作。gh: agent 受阻时评论 issue。node: Claude Code
# CLI 的运行时。jq/curl: prompt 与 agent 的常用工具。
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl jq ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

# Claude Code 拒绝以 root 跑 bypassPermissions。UID 必须钉在 1000:sandcastle 在
# Windows 宿主上拿不到 uid(process.getuid 不存在),固定以 --user 1000 起容器;
# 用户 uid 对不上,/home/agent 对运行时不可写,沙箱 git config 第一步就 Permission
# denied(story-machine 2026-07 research 版实测)。
RUN useradd -m -u 1000 agent
USER agent
WORKDIR /home/agent

# 预装 pytest,让将来 tests/ 目录下的 pytest 用例离线可跑。仓库代码本身零第三方
# 依赖;若某天引入了,同步加到这里并重建镜像,否则沙箱内 import 失败白烧一轮。
ENV VIRTUAL_ENV=/home/agent/venv
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
RUN python -m venv "$VIRTUAL_ENV" && pip install --no-cache-dir "pytest>=8.0"

# sandcastle 起容器时不带命令覆盖,要求容器常驻;python 基础镜像默认进 REPL 会
# 立刻退出。
CMD ["sleep", "infinity"]
