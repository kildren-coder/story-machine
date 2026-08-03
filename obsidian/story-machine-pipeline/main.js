/*
 * story-machine-pipeline — 流水线控制台
 *
 * 在笔记里放一个 ```sm-pipeline 代码块，就得到一个面板：粘链接入队、点「运行」
 * 拉起 worker、看着每一集从「待下载」走到「完成」。
 *
 * 分工（和 worker.ps1 是同一套契约）：
 *   - **队列笔记是唯一状态**。本插件不持有任何进度状态，只是把队列文件渲染出来。
 *   - worker 每完成一步就改写队列文件 → vault 的 modify 事件 → 面板重画。
 *     所以进度不需要插件和 worker 之间有任何通道，进程日志只是排障用的副产物。
 *
 * 与 story-machine-timestamps 分开成两个插件，是因为这里要 require('child_process')，
 * 必须标 isDesktopOnly；没必要让纯渲染的时间戳插件跟着降级。
 */

const { Plugin, MarkdownRenderChild, Notice, TFile, normalizePath } = require("obsidian");

const ROW_RE = /^(\s*)-\s+(https?:\/\/\S+)(.*)$/;
const FIELD_RE = /\[([^\[\]:]+?)::\s*([^\]]*)\]/g;

const BUSY = ["下载中", "转写中", "取回中", "建笔记中"];
const STAGE_CLASS = {
  待下载: "wait", 待转写: "wait", 待取回: "wait", 待建笔记: "wait",
  下载中: "busy", 转写中: "busy", 取回中: "busy", 建笔记中: "busy",
  完成: "done", 失败: "fail",
};

module.exports = class PipelinePlugin extends Plugin {
  onload() {
    this.proc = null;
    this.panels = new Set();
    this.registerMarkdownCodeBlockProcessor("sm-pipeline", (src, el, ctx) => {
      const panel = new Panel(this, el, parseConfig(src));
      ctx.addChild(panel);
    });
    this.registerEvent(
      this.app.vault.on("modify", (f) => {
        for (const p of this.panels) if (p.cfg.queue === f.path) p.render();
      })
    );
    this.addCommand({
      id: "run-worker",
      name: "运行流水线 worker",
      callback: () => {
        const p = this.panels.values().next().value;
        if (p) p.run(); else new Notice("没有打开的 sm-pipeline 面板");
      },
    });
  }

  onunload() {
    if (this.proc) { try { this.proc.kill(); } catch (e) { /* 已退出 */ } }
  }

  vaultBase() {
    const a = this.app.vault.adapter;
    return a.basePath || a.getBasePath?.() || "";
  }
};

function parseConfig(src) {
  const cfg = { queue: "", worker: "", pwsh: "powershell.exe" };
  for (const line of src.split("\n")) {
    const m = line.match(/^\s*([^:#]+?)\s*:\s*(.+?)\s*$/);
    if (!m) continue;
    const k = m[1].trim(), v = m[2].trim();
    if (k === "队列" || k === "queue") cfg.queue = normalizePath(v);
    else if (k === "worker") cfg.worker = v;
    else if (k === "pwsh") cfg.pwsh = v;
  }
  return cfg;
}

function parseQueue(text) {
  const rows = [];
  for (const line of text.split("\n")) {
    const m = line.match(ROW_RE);
    if (!m) continue;
    const f = {};
    let fm;
    FIELD_RE.lastIndex = 0;
    while ((fm = FIELD_RE.exec(m[3])) !== null) f[fm[1].trim()] = fm[2].trim();
    rows.push({ url: m[2], f });
  }
  return rows;
}

class Panel extends MarkdownRenderChild {
  constructor(plugin, el, cfg) {
    super(el);
    this.plugin = plugin;
    this.app = plugin.app;
    this.cfg = cfg;
  }

  onload() {
    this.plugin.panels.add(this);
    this.build();
    this.render();
  }

  onunload() {
    this.plugin.panels.delete(this);
  }

  build() {
    const root = this.containerEl;
    root.empty();
    root.addClass("sm-pipe");

    const bar = root.createDiv({ cls: "sm-pipe-bar" });
    this.input = bar.createEl("input", {
      attr: { type: "text", placeholder: "粘贴 B 站链接，回车入队" },
      cls: "sm-pipe-input",
    });
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); this.enqueue(); }
    });
    bar.createEl("button", { text: "＋ 入队", cls: "sm-pipe-btn" })
      .addEventListener("click", () => this.enqueue());
    this.runBtn = bar.createEl("button", { text: "▶ 运行", cls: "sm-pipe-btn sm-pipe-run" });
    this.runBtn.addEventListener("click", () => (this.plugin.proc ? this.stop() : this.run()));

    this.body = root.createDiv({ cls: "sm-pipe-body" });
    this.logEl = root.createEl("pre", { cls: "sm-pipe-log" });
    this.logEl.hide();
  }

  queueFile() {
    const f = this.app.vault.getAbstractFileByPath(this.cfg.queue);
    return f instanceof TFile ? f : null;
  }

  async render() {
    const file = this.queueFile();
    this.body.empty();
    if (!file) {
      this.body.createDiv({ cls: "sm-pipe-empty", text: `找不到队列笔记：${this.cfg.queue}` });
      return;
    }
    const rows = parseQueue(await this.app.vault.cachedRead(file));
    if (!rows.length) {
      this.body.createDiv({ cls: "sm-pipe-empty", text: "队列是空的。粘一个链接进去。" });
      return;
    }
    for (const r of rows) this.renderRow(this.body.createDiv({ cls: "sm-pipe-row" }), r);
  }

  renderRow(el, r) {
    const stage = r.f["阶段"] || "未入队";
    el.addClass("sm-stage-" + (STAGE_CLASS[stage] || "wait"));

    const head = el.createDiv({ cls: "sm-pipe-head" });
    head.createSpan({ cls: "sm-pipe-ep", text: r.f["ep"] || "—" });
    head.createSpan({
      cls: "sm-pipe-title",
      text: r.f["标题"] || r.url.replace(/^https?:\/\//, ""),
    });
    head.createSpan({ cls: "sm-pipe-stage", text: stage });

    // 进度条：只在「*中」显示。百分比从 [进度:: 43% (…)] 里取前导整数。
    if (BUSY.includes(stage)) {
      const pct = parseInt((r.f["进度"] || "").match(/(\d+)\s*%/)?.[1] ?? "0", 10);
      const track = el.createDiv({ cls: "sm-pipe-track" });
      track.createDiv({ cls: "sm-pipe-fill" }).style.width = pct + "%";
      if (r.f["进度"]) el.createDiv({ cls: "sm-pipe-detail", text: r.f["进度"] });
    }
    if (r.f["错误"]) el.createDiv({ cls: "sm-pipe-err", text: "✗ " + r.f["错误"] });
    if (r.f["备注"]) el.createDiv({ cls: "sm-pipe-note", text: "· " + r.f["备注"] });

    const meta = [];
    if (r.f["时长"]) meta.push(r.f["时长"]);
    if (r.f["更新"]) meta.push("更新 " + r.f["更新"]);
    if (meta.length) el.createDiv({ cls: "sm-pipe-meta", text: meta.join("　") });

    if (stage === "失败") {
      el.createEl("button", { text: "重试", cls: "sm-pipe-btn sm-pipe-mini" })
        .addEventListener("click", () => this.retry(r));
    }
  }

  async enqueue() {
    const url = this.input.value.trim();
    if (!/^https?:\/\//.test(url)) { new Notice("需要一个 http(s) 链接"); return; }
    const file = this.queueFile();
    if (!file) { new Notice("找不到队列笔记：" + this.cfg.queue); return; }
    // 只追加裸链接，ep 编号和阶段由 worker 补——入队的契约越薄越不容易和 worker 打架
    await this.app.vault.process(file, (text) =>
      text.replace(/\s*$/, "") + "\n- " + url + "\n");
    this.input.value = "";
    new Notice("已入队。点「运行」开始。");
  }

  async retry(r) {
    const file = this.queueFile();
    if (!file) return;
    await this.app.vault.process(file, (text) =>
      text.split("\n").map((line) => {
        const m = line.match(ROW_RE);
        if (!m || m[2] !== r.url) return line;
        return line
          .replace(/\[阶段::\s*[^\]]*\]/, "[阶段:: 待下载]")
          .replace(/\s*\[错误::\s*[^\]]*\]/, "")
          .replace(/\s*\[进度::\s*[^\]]*\]/, "");
      }).join("\n"));
    new Notice(`${r.f["ep"] || ""} 已重置为待下载`);
  }

  run() {
    if (this.plugin.proc) { new Notice("worker 已在运行"); return; }
    if (!this.cfg.worker) { new Notice("代码块里没写 worker: 路径"); return; }

    // 队列在 <vault>/story-machine/_pipeline/队列.md → worker 的 -Vault 是它的爷爷目录
    const base = this.plugin.vaultBase();
    const path = require("path");
    const vaultArg = path.join(base, path.dirname(path.dirname(this.cfg.queue)));

    this.logEl.setText("");
    this.logEl.show();
    this.setRunning(true);

    // 不用 -File 而用 -Command，是为了先把 OutputEncoding 设成 UTF-8 再 & 脚本。
    // -File 模式下脚本自身的解析错误由 host 用 GBK 写出，这边按 UTF-8 解就是一屏乱码，
    // 而那恰恰是最需要看清的一类错误。放进 -Command 就赶在解析之前设好了。
    const q = (s) => "'" + String(s).replace(/'/g, "''") + "'";
    const psCmd = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " +
      "& " + q(this.cfg.worker) + " -Vault " + q(vaultArg);

    const { spawn } = require("child_process");
    const proc = spawn(this.cfg.pwsh,
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", psCmd],
      { windowsHide: true });
    this.plugin.proc = proc;

    const append = (buf) => {
      this.logEl.appendText(buf.toString("utf8"));
      this.logEl.scrollTop = this.logEl.scrollHeight;
    };
    proc.stdout.on("data", append);
    proc.stderr.on("data", append);
    proc.on("error", (err) => {
      this.logEl.appendText("\n[spawn 失败] " + err.message + "\n");
      new Notice("拉起 worker 失败：" + err.message);
      this.plugin.proc = null;
      this.setRunning(false);
    });
    proc.on("close", (code) => {
      this.logEl.appendText(`\n[worker 退出，code ${code}]\n`);
      this.plugin.proc = null;
      this.setRunning(false);
      this.render();
      new Notice(code === 0 ? "流水线跑完了" : `worker 异常退出（code ${code}）`);
    });
  }

  stop() {
    if (!this.plugin.proc) return;
    this.plugin.proc.kill();
    new Notice("已停止。当前阶段会在下次运行时重跑。");
  }

  setRunning(on) {
    this.runBtn.setText(on ? "■ 停止" : "▶ 运行");
    this.runBtn.toggleClass("sm-pipe-stop", on);
  }
}
