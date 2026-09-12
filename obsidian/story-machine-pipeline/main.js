/*
 * story-machine-pipeline — 流水线控制台 + EP 笔记状态条
 *
 * 两个代码块：
 *   ```sm-pipeline  控制台面板：粘链接入队、点「运行」拉起 worker、看每一集走到哪
 *   ```sm-ep        EP 笔记顶上的状态条：这一集现在卡在哪一阶段，下一步该点什么
 *
 * 分工（和 worker.ps1 是同一套契约）：
 *   - **状态全在文件里**，插件不持有任何进度状态，只是把文件渲染出来。
 *     队列进度看 `_pipeline/队列.md`，点名进度看 EP 笔记自己的说话人小表。
 *   - worker 每完成一步就改写文件 → vault 的 modify 事件 → 面板重画。
 *     所以不需要插件和 worker 之间有任何通道，进程日志只是排障用的副产物。
 *
 * 为什么状态条要长在笔记里、而不是只在控制台：人点开一集看到的是一份空笔记，
 * 「接下来该干什么」必须在他眼睛已经在的地方回答，否则他只能回来问人。
 *
 * 与 story-machine-timestamps 分开成两个插件，是因为这里要 require('child_process')，
 * 必须标 isDesktopOnly；没必要让纯渲染的时间戳插件跟着降级。
 */

const { Plugin, MarkdownRenderChild, Notice, TFile, normalizePath } = require("obsidian");

/*
 * 行尾那个 `\r?` 不是可有可无的。worker 用 .NET 的 File.WriteAllLines 写盘，
 * 换行是 CRLF；而 JS 里 `.` **不匹配 CR**（CR 是 LineTerminator），`$` 在没有
 * m 标志时又只认字符串结尾——于是 `(.*)$` 撞上 `…]\r` 必然失配，
 * split("\n") 出来的每一行都解析不出来，面板会一直显示「队列是空的」。
 * 同理，凡是拿整行做等值比较的地方（说话人小表的注释标记）都要先 trim。
 */
const ROW_RE = /^(\s*)-\s+(https?:\/\/\S+)(.*)\r?$/;
const FIELD_RE = /\[([^\[\]:]+?)::\s*([^\]]*)\]/g;

const BUSY = ["下载中", "转写中", "分离中", "取回中", "建笔记中"];
const STAGE_CLASS = {
  待下载: "wait", 待转写: "wait", 待分离: "wait", 待取回: "wait", 待建笔记: "wait",
  下载中: "busy", 转写中: "busy", 分离中: "busy", 取回中: "busy", 建笔记中: "busy",
  完成: "done", 失败: "fail",
};

// 队列里的「完成」只是**阶段 0** 完成，不是这一集完事了。原样显示会让人以为
// 没事干了，而实际上后面还有点名、抽取、审核。控制台按这张表改口。
const STAGE_LABEL = { 完成: "阶段 0 完成" };

// SPEC §4 的全流程。`built` 标记这一阶段的代码写了没有——没写的照样列出来，
// 因为「还没做」和「做了但没轮到」对人是两回事，含糊过去只会让人反复来问。
const EP_CHAIN = [
  { key: "asr", label: "阶段 0 转写", built: true },
  { key: "name", label: "点名", built: true },
  { key: "extract", label: "阶段 1–2 抽取", built: true },
  { key: "review", label: "阶段 3 审核", built: false },
  { key: "store", label: "阶段 4 落库", built: false },
  { key: "write", label: "阶段 5 你写脉络", built: false },
];

const SPK_BEGIN = "<!-- speakers:auto -->";
const SPK_END = "<!-- /speakers -->";

module.exports = class PipelinePlugin extends Plugin {
  onload() {
    this.proc = null;
    this.panels = new Set();
    this.epPanels = new Set();

    this.registerMarkdownCodeBlockProcessor("sm-pipeline", (src, el, ctx) => {
      ctx.addChild(new Panel(this, el, parseConfig(src)));
    });
    this.registerMarkdownCodeBlockProcessor("sm-ep", (src, el, ctx) => {
      ctx.addChild(new EpPanel(this, el, parseConfig(src), ctx.sourcePath));
    });

    this.registerEvent(
      this.app.vault.on("modify", (f) => {
        for (const p of this.panels) if (p.cfg.queue === f.path) p.render();
        // EP 面板要盯两个文件：自己这篇（人填名字）和队列（阶段 0 的进度）
        for (const p of this.epPanels) if (p.sourcePath === f.path) p.render();
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
    this.addCommand({
      id: "sync-ep",
      name: "同步当前 EP（点名入库 + 刷新状态条）",
      callback: () => {
        const p = this.epPanels.values().next().value;
        if (p) p.sync(); else new Notice("当前笔记里没有 sm-ep 状态条");
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

  /*
   * 拉起 worker。全插件只允许有一个在跑（this.proc）——两个 worker 同时改队列
   * 或同一篇笔记，就是两个进程对着一个文件互相覆盖。
   *
   * 不用 -File 而用 -Command，是为了先把 OutputEncoding 设成 UTF-8 再 & 脚本。
   * -File 模式下脚本自身的解析错误由 host 用 GBK 写出，这边按 UTF-8 解就是一屏
   * 乱码，而那恰恰是最需要看清的一类错误。放进 -Command 就赶在解析之前设好了。
   */
  runWorker({ worker, pwsh, vault, args = [], logEl, onClose }) {
    if (this.proc) { new Notice("worker 已在运行"); return false; }
    if (!worker) { new Notice("代码块里没写 worker: 路径"); return false; }

    const q = (s) => "'" + String(s).replace(/'/g, "''") + "'";
    const psCmd = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " +
      "& " + q(worker) + " -Vault " + q(vault) +
      (args.length ? " " + args.map((a) => (a.startsWith("-") ? a : q(a))).join(" ") : "");

    const { spawn } = require("child_process");
    let proc;
    try {
      proc = spawn(pwsh, ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", psCmd],
        { windowsHide: true });
    } catch (err) {
      new Notice("拉起 worker 失败：" + err.message);
      return false;
    }
    this.proc = proc;

    const append = (buf) => {
      if (!logEl) return;
      logEl.appendText(buf.toString("utf8"));
      logEl.scrollTop = logEl.scrollHeight;
    };
    proc.stdout.on("data", append);
    proc.stderr.on("data", append);
    proc.on("error", (err) => {
      append(Buffer.from("\n[spawn 失败] " + err.message + "\n"));
      new Notice("拉起 worker 失败：" + err.message);
      this.proc = null;
      onClose?.(-1);
    });
    proc.on("close", (code) => {
      append(Buffer.from(`\n[worker 退出，code ${code}]\n`));
      this.proc = null;
      onClose?.(code);
    });
    return true;
  }
};

function parseConfig(src) {
  const cfg = { queue: "", worker: "", ep: "", pwsh: "powershell.exe" };
  for (const line of src.split("\n")) {
    const m = line.match(/^\s*([^:#]+?)\s*:\s*(.+?)\s*$/);
    if (!m) continue;
    const k = m[1].trim(), v = m[2].trim();
    if (k === "队列" || k === "queue") cfg.queue = normalizePath(v);
    else if (k === "worker") cfg.worker = v;
    else if (k === "ep") cfg.ep = v;
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

/*
 * 从 EP 笔记正文读点名进度。三种状态要分开，因为对人的指令完全不同：
 *   未知N + 方括号空   → 还没点名：去听两句，填名字
 *   未知N + 方括号有名 → 填了但没入库：worker 还没跑过，点一下按钮就完
 *   没有未知N          → 都入库了
 * 「未知N」是 worker 写的字样，入库后会被换成真名——所以它就是「入没入库」的判据，
 * 不需要去读声纹库，也就不需要插件碰 _assets/。
 */
function readSpeakers(text) {
  const lines = text.split("\n");
  const b = lines.findIndex((l) => l.trim() === SPK_BEGIN);   // trim：文件是 CRLF
  const e = lines.findIndex((l) => l.trim() === SPK_END);
  const st = { total: 0, todo: 0, pending: 0, has: b >= 0 && e > b };
  if (!st.has) return st;
  for (const l of lines.slice(b + 1, e)) {
    if (!/`SPEAKER_\d+`/.test(l)) continue;
    st.total++;
    if (!/未知\d+/.test(l)) continue;
    const f = l.match(/\[SPEAKER_\d+::\s*([^\]]*)\]/);
    if (f && f[1].trim()) st.pending++; else st.todo++;
  }
  return st;
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

  // vault 根下的项目目录：队列在 <root>/_pipeline/队列.md
  root() {
    return this.cfg.queue.split("/").slice(0, -2).join("/");
  }

  // EP 笔记的文件名带标题（`EP03 阻力最小路线….md`），只能按前缀找
  epNote(ep) {
    if (!ep) return null;
    const dir = this.root() + "/10-Episodes/";
    return this.app.vault.getFiles()
      .find((f) => f.path.startsWith(dir) && f.basename.startsWith(ep)) || null;
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
    for (const r of rows) await this.renderRow(this.body.createDiv({ cls: "sm-pipe-row" }), r);
  }

  async renderRow(el, r) {
    const stage = r.f["阶段"] || "未入队";
    el.addClass("sm-stage-" + (STAGE_CLASS[stage] || "wait"));

    const head = el.createDiv({ cls: "sm-pipe-head" });
    head.createSpan({ cls: "sm-pipe-ep", text: r.f["ep"] || "—" });
    head.createSpan({
      cls: "sm-pipe-title",
      text: r.f["标题"] || r.url.replace(/^https?:\/\//, ""),
    });
    head.createSpan({ cls: "sm-pipe-stage", text: STAGE_LABEL[stage] || stage });

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

    // 阶段 0 走完之后活儿转移到 EP 笔记上，控制台得把人送过去，
    // 否则「完成」两个字就是一条死路。
    if (stage === "完成") await this.renderNext(el, r.f["ep"]);

    if (stage === "失败") {
      el.createEl("button", { text: "重试", cls: "sm-pipe-btn sm-pipe-mini" })
        .addEventListener("click", () => this.retry(r));
    }
  }

  async renderNext(el, ep) {
    const note = this.epNote(ep);
    const line = el.createDiv({ cls: "sm-pipe-next" });
    if (!note) { line.setText("下一步：找不到 EP 笔记"); return; }

    const spk = readSpeakers(await this.app.vault.cachedRead(note));
    let what;
    if (spk.pending) what = `${spk.pending} 个名字填好了，等入库`;
    else if (spk.todo) what = `还有 ${spk.todo} 位没点名`;
    else what = "点名齐了，等阶段 2 抽取（未实现）";

    line.appendText("下一步：" + what + " → ");
    const a = line.createEl("a", { text: note.basename, cls: "sm-pipe-link" });
    a.addEventListener("click", (e) => {
      e.preventDefault();
      this.app.workspace.openLinkText(note.path, "", false);
    });
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
    const path = require("path");
    // 队列在 <vault>/story-machine/_pipeline/队列.md → worker 的 -Vault 是它的爷爷目录
    const vault = path.join(this.plugin.vaultBase(),
      path.dirname(path.dirname(this.cfg.queue)));

    this.logEl.setText("");
    this.logEl.show();
    const ok = this.plugin.runWorker({
      worker: this.cfg.worker, pwsh: this.cfg.pwsh, vault, logEl: this.logEl,
      onClose: (code) => {
        this.setRunning(false);
        this.render();
        new Notice(code === 0 ? "流水线跑完了" : `worker 异常退出（code ${code}）`);
      },
    });
    if (ok) this.setRunning(true);
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

/*
 * EP 笔记顶上的状态条。由 worker 写进笔记的 ```sm-ep 代码块拉起（见 Get-EpBlock）。
 * 只读笔记自己 + `_review/` 目录，不碰队列——这一集走到哪，笔记里全看得出来。
 */
class EpPanel extends MarkdownRenderChild {
  constructor(plugin, el, cfg, sourcePath) {
    super(el);
    this.plugin = plugin;
    this.app = plugin.app;
    this.cfg = cfg;
    this.sourcePath = sourcePath;
  }

  onload() {
    this.plugin.epPanels.add(this);
    this.build();
    this.render();
  }

  onunload() {
    this.plugin.epPanels.delete(this);
  }

  build() {
    const root = this.containerEl;
    root.empty();
    root.addClass("sm-ep");
    this.chainEl = root.createDiv({ cls: "sm-ep-chain" });
    this.nowEl = root.createDiv({ cls: "sm-ep-now" });
    this.actEl = root.createDiv({ cls: "sm-ep-act" });
    this.logEl = root.createEl("pre", { cls: "sm-pipe-log" });
    this.logEl.hide();
  }

  // <root>/10-Episodes/EP03 ….md → <root>
  root() {
    return this.sourcePath.split("/").slice(0, -2).join("/");
  }

  // `_review/EP03-A.draft.md` 这类草稿的篇数。前缀要带 `-`，否则 EP0 会吃到 EP03
  reviewCount() {
    const dir = this.root() + "/_review/";
    return this.app.vault.getFiles()
      .filter((f) => f.path.startsWith(dir) && f.basename.startsWith(this.cfg.ep + "-"))
      .length;
  }

  async render() {
    const file = this.app.vault.getAbstractFileByPath(this.sourcePath);
    if (!(file instanceof TFile)) return;
    const spk = readSpeakers(await this.app.vault.cachedRead(file));

    // 笔记存在就说明阶段 0 走完了——它是阶段 0 最后一步的产物。
    const drafts = this.reviewCount();
    let at, now, action = null;
    if (!spk.has) {
      at = "name";
      now = "还没有说话人小表。多半是这一集分离于声纹库之前——重跑一次分离即可。";
    } else if (spk.pending) {
      at = "name";
      now = `${spk.pending} 个名字填好了，还没入库。入库之后往后各集会自动认出这些人。`;
      action = { text: `✓ 入库 ${spk.pending} 个名字`, primary: true, args: ["-Name"] };
    } else if (spk.todo) {
      at = "name";
      now = `还有 ${spk.todo} 位没点名。点小表里的首次出现时间戳听两句，` +
        "把名字填进行尾的方括号，回来点入库。";
      action = { text: "↻ 重新同步", primary: false, args: ["-Name"] };
    } else if (drafts) {
      at = "review";
      now = `${spk.total} 位都已入库。\`_review/\` 里有 ${drafts} 篇草稿等你审` +
        "——审完把文件挪出 `_review/` 就算通过。";
      action = { text: "↻ 重新抽取（覆盖草稿）", primary: false,
                 args: ["-Extract", "-Redo"], confirm: "会覆盖现有草稿，你审过的改动会没。确定？" };
    } else {
      at = "extract";
      now = `${spk.total} 位都已入库，阶段 0 全部完成。下一步是抽取——` +
        "本版只抽 `channel`（他让你去哪查、该看谁），一块要跑几分钟，走订阅额度。";
      action = { text: "▶ 阶段 1–2 抽取", primary: true, args: ["-Extract"] };
    }

    this.chainEl.empty();
    const cur = EP_CHAIN.findIndex((s) => s.key === at);
    EP_CHAIN.forEach((s, i) => {
      if (i) this.chainEl.createSpan({ cls: "sm-ep-sep", text: "›" });
      const cls = ["sm-ep-step"];
      if (i < cur) cls.push("is-done");
      else if (i === cur) cls.push("is-now");
      if (!s.built) cls.push("is-todo");
      const step = this.chainEl.createSpan({ cls: cls.join(" "), text: s.label });
      if (i < cur) step.appendText(" ✓");
      if (!s.built) step.setAttr("title", "这一阶段还没实现");
    });

    this.nowEl.setText("现在：" + now);

    this.actEl.empty();
    if (!action) return;
    const btn = this.actEl.createEl("button", {
      text: action.text,
      cls: "sm-pipe-btn" + (action.primary ? " sm-pipe-run" : ""),
    });
    if (action.disabled) {
      btn.disabled = true;
      btn.setAttr("title", action.disabled);
      this.actEl.createSpan({ cls: "sm-ep-hint", text: "（" + action.disabled + "）" });
      return;
    }
    btn.addEventListener("click", () => {
      if (action.confirm && !window.confirm(action.confirm)) return;
      this.run(action, btn);
    });
  }

  /* worker 的 EP 级开关都是 `-开关 EP03` 的形状，所以这里只需要把第一个
     参数后面插上集号：["-Extract", "-Redo"] → ["-Extract", "EP03", "-Redo"]。*/
  run(action, btn) {
    if (!this.cfg.ep) { new Notice("sm-ep 代码块里没写 ep:"); return; }
    const path = require("path");
    // 笔记在 <vault>/story-machine/10-Episodes/EP03 ….md → -Vault 是它的爷爷目录
    const vault = path.join(this.plugin.vaultBase(),
      path.dirname(path.dirname(this.sourcePath)));
    const args = action.args.slice();
    args.splice(1, 0, this.cfg.ep);
    const long = args[0] === "-Extract";

    this.logEl.setText(long ? "跑起来了。抽取要几分钟，日志会一行行往下走…\n" : "");
    this.logEl.show();
    const started = this.plugin.runWorker({
      worker: this.cfg.worker, pwsh: this.cfg.pwsh, vault,
      args, logEl: this.logEl,
      onClose: (code) => {
        this.render();
        new Notice(code === 0
          ? `${this.cfg.ep} ${long ? "抽取完成，去 _review/ 看草稿" : "已同步"}`
          : `${this.cfg.ep} ${long ? "抽取" : "同步"}失败（code ${code}），看日志`);
      },
    });
    // 跑起来就把按钮锁上：抽取几分钟内没有可见变化，不锁必然被点第二下
    if (started) {
      btn.disabled = true;
      btn.setText(long ? "抽取中…" : "同步中…");
    }
  }
}
