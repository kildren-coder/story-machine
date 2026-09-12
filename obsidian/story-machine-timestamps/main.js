"use strict";

const obsidian = require("obsidian");
const { Plugin, TFile, MarkdownView } = obsidian;
// Obsidian 把 @codemirror/* 作为外部模块提供给插件。真拿不到时宁可只剩阅读视图，
// 也不能让整个插件加载失败——那会把本来能用的那条路也一起弄没。
let CM = null;
try {
  CM = { ...require("@codemirror/view"), ...require("@codemirror/language") };
} catch (e) {
  console.warn("[sm-ts] 拿不到 CodeMirror，实时预览里的时间戳不会变按钮", e);
}

// 两条渲染路径，因为 Obsidian 有两套渲染器：
//   阅读视图 → registerMarkdownPostProcessor，走 DOM 文本节点（下面的 decorate）
//   实时预览 → CodeMirror 6 装饰，post processor **完全不跑**（下面的编辑器扩展）
// 只做前者的话，「一边审草稿一边点时间戳听原话」这个阶段 3 的主场景是废的
// ——阅读视图改不了字，编辑模式点不动按钮。

// MM:SS 或 HH:MM:SS。分钟允许到三位（141 分钟的一集写成 135:00 也认）。
// 前后的 (?<![\d:]) / (?![\d:]) 挡住 1350:00 这类越界写法和被截断的匹配。
const TS_RE = /(?<![\d:])(\d{1,3}):([0-5]\d)(?::([0-5]\d))?(?![\d:])/g;

// 限定符：EP01@60:00 —— 指名道姓说这个时间戳属于哪一集，不跟着本笔记走。
const QUALIFIER_RE = /([\w一-龥.\-]{1,40})@$/;

// 「字段」模式下，只有这些 key 的值才会变成按钮。
const FIELD_KEYS = new Set(["录音时间戳", "播放位置", "timestamp"]);

// 这些容器里的文本一律不动：
//   code/pre —— 代码。也是**逃生舱**：`60:00` 加反引号就不会变按钮
//   a        —— 已经是链接
//   .sm-ts   —— 我们自己造的按钮，防重入
//   .block-language-dataview(js) —— 查询结果里的行可能来自别的集，
//                                    本插件按「本笔记的 frontmatter」绑音频，对跨集行会绑错。
//                                    跨集阅读面走 dataviewjs 自绘，不归这里管。
//   .metadata-container / .frontmatter —— 属性面板
const SKIP = "code,pre,a,.sm-ts,.block-language-dataview,.block-language-dataviewjs,.metadata-container,.frontmatter";

// Dataview 会在我们装好按钮之后重画 inline field，把按钮抹掉。
// 所以除了排到最后跑，还要盯着 DOM 变化补一遍。
const POST_PROCESSOR_ORDER = 200;
const REDECORATE_DEBOUNCE_MS = 80;

module.exports = class StoryMachineTimestamps extends Plugin {
  async onload() {
    this.player = null;
    this.activeBtn = null;
    this.currentUrl = null;
    this.observers = new Set();
    this.debug = false;

    // 事件委托 + pointerdown。
    // 不给每个按钮挂 listener 是因为 Dataview 会重画那一行、把按钮整个换掉；
    // 用 click 则会碰上 mousedown 和 mouseup 落在不同元素上、click 根本不触发。
    this.registerDomEvent(document, "pointerdown", (e) => this.onPointerDown(e), true);

    this.registerMarkdownPostProcessor((el, ctx) => {
      const audio = this.resolveAudio(ctx.sourcePath);
      if (!audio) return; // 笔记没声明「音频:」就完全不介入
      const fm = this.frontmatter(ctx.sourcePath);
      this.debug = this.debug || fm?.["时间戳调试"] === true;
      const mode = this.resolveMode(fm);
      this.decorate(el, audio, mode, ctx.sourcePath);
      this.watch(el, audio, mode, ctx.sourcePath);
    }, POST_PROCESSOR_ORDER);

    if (CM) this.registerEditorExtension(this.editorExtension());
  }

  // —— 实时预览：CM6 装饰 ——
  //
  // 只处理视口内的行；光标落在某个时间戳里时**不装饰它**，好让你能改字
  // （这是 Live Preview 的通行做法，也是「审草稿时要能编辑」的前提）。
  editorExtension() {
    const self = this;
    const { ViewPlugin, Decoration, WidgetType, EditorView } = CM;

    class TsWidget extends WidgetType {
      constructor(raw, sec, audio) {
        super();
        this.raw = raw;
        this.sec = sec;
        this.audio = audio;
      }
      eq(o) {
        return o.raw === this.raw && o.sec === this.sec && o.audio.url === this.audio.url;
      }
      toDOM() { return self.makeBtn(this.raw, this.sec, this.audio); }
      // 返回 false：让 pointerdown 照常冒泡到我们的委托监听（jump 在那儿）
      ignoreEvent() { return false; }
    }

    const build = (view) => {
      const audio = self.audioForEditor(view);
      if (!audio) return Decoration.none;
      const mode = self.resolveMode(self.frontmatter(self.pathForEditor(view)));
      const ranges = [];
      const sel = view.state.selection.main;
      let lastEnd = -1;
      for (const { from, to } of view.visibleRanges) {
        const text = view.state.sliceDoc(from, to);
        TS_RE.lastIndex = 0;
        let m;
        while ((m = TS_RE.exec(text)) !== null) {
          const [raw, a, b, c] = m;
          let start = from + m.index;
          let end = start + raw.length;
          let target = audio;

          const q = text.slice(Math.max(0, m.index - 41), m.index).match(QUALIFIER_RE);
          if (q) {
            const named = self.resolveByName(q[1], self.pathForEditor(view) ?? "");
            if (named) { target = named; start -= q[1].length + 1; }
          } else if (mode === "字段" && !FIELD_KEYS.has(self.keyBefore(text, m.index))) {
            continue;
          }
          // 光标或选区碰到这一段就露出原文，否则没法编辑
          if (sel.to >= start - 1 && sel.from <= end + 1) continue;
          if (self.inSkippedSyntax(view, start)) continue;
          // 限定符会把起点往前挪，理论上能和上一处叠上；replace 装饰不许重叠
          if (start < lastEnd) continue;
          lastEnd = end;

          const sec = c === undefined
            ? Number(a) * 60 + Number(b)
            : Number(a) * 3600 + Number(b) * 60 + Number(c);
          ranges.push(Decoration.replace({ widget: new TsWidget(raw, sec, target) })
            .range(start, end));
        }
      }
      return Decoration.set(ranges, true);
    };

    return ViewPlugin.fromClass(class {
      constructor(view) { this.decos = this.safe(view); }
      update(u) {
        if (u.docChanged || u.viewportChanged || u.selectionSet) {
          this.decos = this.safe(u.view);
        }
      }
      // 装饰算错了大不了不显示按钮；把编辑器整个搞崩就是另一回事了
      safe(view) {
        try { return build(view); } catch (e) { self.log("CM6 装饰失败", e); return Decoration.none; }
      }
    }, {
      decorations: (v) => v.decos,
      provide: (p) => EditorView.atomicRanges.of((v) => v.plugin(p)?.decos || Decoration.none),
    });
  }

  // 代码块、行内代码、frontmatter、已有链接里的数字一概不碰——和阅读视图的
  // SKIP 选择器是同一份意图，只是这边只能问语法树。
  inSkippedSyntax(view, pos) {
    let hit = false;
    CM.syntaxTree(view.state).iterate({
      from: pos, to: pos + 1,
      enter: (n) => {
        if (/code|frontmatter|url|link|math|hashtag/i.test(n.name)) hit = true;
      },
    });
    return hit;
  }

  pathForEditor(view) {
    const field = obsidian.editorInfoField;
    if (field) {
      const info = view.state.field(field, false);
      if (info?.file) return info.file.path;
    }
    let path = null;
    this.app.workspace.iterateAllLeaves((leaf) => {
      if (path) return;
      const v = leaf.view;
      if (v instanceof MarkdownView && v.editor?.cm === view && v.file) path = v.file.path;
    });
    return path;
  }

  audioForEditor(view) {
    const path = this.pathForEditor(view);
    return path ? this.resolveAudio(path) : null;
  }

  onunload() {
    for (const obs of this.observers) obs.disconnect();
    this.observers.clear();
    if (this.player) this.player.bar.remove();
    this.player = null;
    this.activeBtn = null;
    this.currentUrl = null;
  }

  log(...args) {
    if (this.debug) console.log("[sm-ts]", ...args);
  }

  frontmatter(sourcePath) {
    if (!sourcePath) return null;   // 编辑器扩展那边可能问不出笔记路径
    const src = this.app.vault.getAbstractFileByPath(sourcePath);
    if (!(src instanceof TFile)) return null;
    return this.app.metadataCache.getFileCache(src)?.frontmatter ?? null;
  }

  // —— 音频绑定：数据驱动，和 DOM 位置无关 ——
  resolveAudio(sourcePath) {
    const fm = this.frontmatter(sourcePath);
    const name = fm?.["音频"] ?? fm?.audio;
    if (!name) return null;
    return this.resolveByName(String(name), sourcePath);
  }

  // 名字可以是音频文件（EP01.m4a / EP01），也可以是一篇声明了「音频:」的集笔记。
  resolveByName(name, sourcePath) {
    for (const cand of [name, `${name}.m4a`]) {
      const f = this.app.metadataCache.getFirstLinkpathDest(cand, sourcePath);
      if (!(f instanceof TFile)) continue;
      if (f.extension === "md") {
        const sub = this.resolveAudio(f.path);
        if (sub) return sub;
        continue;
      }
      return { url: this.app.vault.getResourcePath(f), label: f.basename };
    }
    return null;
  }

  // 「全文」（默认）＝ 正文里任何 MM:SS / HH:MM:SS 都变按钮。
  // 「字段」          ＝ 只认 [录音时间戳:: 27:04] 这类字段值。
  resolveMode(fm) {
    const raw = String(fm?.["时间戳范围"] ?? fm?.timestampScope ?? "全文").trim();
    return raw === "字段" || raw === "fields" ? "字段" : "全文";
  }

  // —— 扫全部文本节点，不只是 <p> ——
  decorate(root, audio, mode, sourcePath) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => {
        if (!n.nodeValue || n.nodeValue.indexOf(":") === -1) return NodeFilter.FILTER_REJECT;
        const parent = n.parentElement;
        if (!parent || parent.closest(SKIP)) return NodeFilter.FILTER_REJECT;
        return NodeFilter.FILTER_ACCEPT;
      },
    });
    const targets = [];
    while (walker.nextNode()) targets.push(walker.currentNode);
    for (const node of targets) this.replaceIn(node, audio, mode, sourcePath);
  }

  // Dataview 已经把 [k:: v] 渲染成 span 了：从祖先节点上读 key。
  fieldKeyOf(node) {
    const wrap = node.parentElement?.closest(".inline-field");
    if (!wrap) return null;
    return wrap.querySelector(".inline-field-key")?.textContent?.trim() ?? null;
  }

  // Dataview 还没渲染（或关掉了渲染）：从同一个文本节点里向前找 [k::。
  keyBefore(text, idx) {
    const head = text.slice(Math.max(0, idx - 40), idx);
    const m = head.match(/\[([^\[\]:]{1,24})::[^\[\]]{0,12}$/);
    return m ? m[1].trim() : null;
  }

  replaceIn(node, audio, mode, sourcePath) {
    const text = node.nodeValue;
    const wrapKey = mode === "字段" ? this.fieldKeyOf(node) : null;

    TS_RE.lastIndex = 0;
    let m, last = 0, frag = null;
    while ((m = TS_RE.exec(text)) !== null) {
      const [raw, a, b, c] = m;

      // EP01@60:00 —— 限定符优先于本笔记的音频
      let target = audio;
      let start = m.index;
      const q = text.slice(Math.max(0, m.index - 41), m.index).match(QUALIFIER_RE);
      if (q) {
        const named = this.resolveByName(q[1], sourcePath);
        if (named) {
          target = named;
          start = m.index - (q[1].length + 1); // 把 "EP01@" 一起吃掉
        } else {
          this.log("限定符解析失败", q[1]);
        }
      } else if (mode === "字段") {
        const key = wrapKey ?? this.keyBefore(text, m.index);
        if (!key || !FIELD_KEYS.has(key)) continue; // 正文里顺口提到的数字不碰
      }

      const sec = c === undefined
        ? Number(a) * 60 + Number(b)
        : Number(a) * 3600 + Number(b) * 60 + Number(c);
      if (start < last) continue;

      if (!frag) frag = document.createDocumentFragment();
      if (start > last) frag.appendChild(document.createTextNode(text.slice(last, start)));
      frag.appendChild(this.makeBtn(raw, sec, target));
      last = m.index + raw.length;
    }
    if (!frag) return;
    if (last < text.length) frag.appendChild(document.createTextNode(text.slice(last)));
    node.parentNode?.replaceChild(frag, node);
  }

  // —— 补画：Dataview 重画 inline field 会把按钮抹掉 ——
  watch(root, audio, mode, sourcePath) {
    let timer = null;
    let busy = false;
    const obs = new MutationObserver(() => {
      if (busy || timer !== null) return;
      timer = window.setTimeout(() => {
        timer = null;
        if (!root.isConnected) {
          obs.disconnect();
          this.observers.delete(obs);
          return;
        }
        busy = true;
        try {
          this.decorate(root, audio, mode, sourcePath);
        } finally {
          busy = false;
        }
      }, REDECORATE_DEBOUNCE_MS);
    });
    obs.observe(root, { childList: true, subtree: true, characterData: true });
    this.observers.add(obs);
  }

  makeBtn(raw, sec, audio) {
    const btn = createSpan({ cls: "sm-ts" });
    btn.setAttribute("role", "button");
    btn.setAttribute("aria-label", `${audio.label} @ ${raw}`);
    btn.dataset.smSrc = audio.url;
    btn.dataset.smSec = String(sec);
    btn.dataset.smRaw = raw;
    btn.dataset.smLabel = audio.label;
    btn.createSpan({ cls: "sm-ts-icon", text: "▶" });
    btn.createSpan({ cls: "sm-ts-time", text: raw });
    return btn;
  }

  onPointerDown(e) {
    if (e.button !== undefined && e.button !== 0) return;
    const btn = e.target instanceof Element ? e.target.closest(".sm-ts") : null;
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    this.jump(btn);
  }

  // —— 播放器：插件自己持有一个，不去 DOM 里捞嵌入（嵌入是懒加载的，捞不到）——
  ensurePlayer() {
    if (this.player && this.player.bar.isConnected) return this.player;
    const bar = document.body.createDiv({ cls: "sm-player" });
    const head = bar.createDiv({ cls: "sm-player-head" });
    const label = head.createSpan({ cls: "sm-player-label", text: "" });
    const close = head.createSpan({ cls: "sm-player-close", text: "✕" });
    const el = bar.createEl("audio");
    el.controls = true;
    el.preload = "metadata";

    close.addEventListener("click", () => {
      el.pause();
      bar.remove();
      this.player = null;
      this.setIcon(this.activeBtn, false);
      this.activeBtn = null;
      this.currentUrl = null;
    });
    el.addEventListener("play", () => this.setIcon(this.activeBtn, true));
    el.addEventListener("pause", () => this.setIcon(this.activeBtn, false));
    // 静默失败是这类东西最难查的地方，一律显示出来
    el.addEventListener("error", () => {
      const code = el.error?.code;
      label.setText(`✗ 加载失败（code ${code ?? "?"}）`);
      this.log("audio error", code, el.currentSrc);
    });

    this.player = { bar, label, el };
    return this.player;
  }

  setIcon(btn, playing) {
    if (!btn || !btn.isConnected) return;
    const icon = btn.querySelector(".sm-ts-icon");
    if (icon) icon.textContent = playing ? "⏸" : "▶";
    btn.toggleClass("sm-ts-active", !!playing);
  }

  jump(btn) {
    const url = btn.dataset.smSrc;
    const sec = Number(btn.dataset.smSec);
    const raw = btn.dataset.smRaw;
    const label = btn.dataset.smLabel;
    if (!url || Number.isNaN(sec)) return;

    const p = this.ensurePlayer();
    this.log("jump", label, raw, sec, "readyState", p.el.readyState);

    // 同一个按钮再点 = 暂停/继续。activeBtn 只由点击改变，
    // 不像 timestamp-player 那样跟着播放进度乱跑。
    if (this.activeBtn === btn && this.currentUrl === url) {
      if (p.el.paused) p.el.play().catch((err) => this.log("play rejected", err));
      else p.el.pause();
      return;
    }

    this.setIcon(this.activeBtn, false);
    this.activeBtn = btn;
    p.label.setText(`${label} @ ${raw}`);

    const seekAndPlay = () => {
      const d = p.el.duration;
      p.el.currentTime = Number.isFinite(d) ? Math.min(sec, Math.max(0, d - 0.25)) : sec;
      p.el.play().catch((err) => this.log("play rejected", err));
    };

    if (this.currentUrl !== url) {
      this.currentUrl = url;
      p.el.src = url;
      p.el.load();
    }
    // readyState >= HAVE_METADATA 时事件早就过去了，再等 loadedmetadata 会永远等下去
    if (p.el.readyState >= 1) seekAndPlay();
    else p.el.addEventListener("loadedmetadata", seekAndPlay, { once: true });
  }
};
