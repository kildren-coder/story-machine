---
type: lab
title: 时间戳跳播验证
音频: EP01.m4a
时间戳范围: 全文
音频说明: 2:21:25，69kbps，BV1cHK16EEz5
插件: story-machine-timestamps v0.1.0（原 timestamp-player v1.1.0 已停用）
日期: 2026-08-02
---

# 时间戳跳播验证

> **怎么判**：成功 = 时间戳变成带 `▶` 图标的按钮，点了音频跳到该位置并开始播放。
> 失败 = 时间戳还是纯文本，点了没反应。
> **多数结果不用播放就能判**——扫一眼有没有 `▶` 就够了。
>
> 本笔记请用**阅读视图**（Ctrl+E 切换）看，实时预览模式下 post processor 行为可能不同。

![[EP01.m4a]]

---

## 源码读出的预判

`main.js` 的处理入口只有一句：

```js
processTimestamps(el){ let ps = el.querySelectorAll("p"); ... }
```

**只扫 `<p>` 元素**。加上正则 `/(\d{1,3}:\d{2})/g` 只认 `MM:SS`，由此推出下面每一格的预期。**如果实测与预期不符，说明我读错了代码，以实测为准。**

---

## A 组：普通段落

A-1（MM:SS，预期 ✅ 跳到 29 分）：这句话里有个时间戳 29:00 ，它应该变成按钮。

A-2（HH:MM:SS，预期 ⚠️ 变成按钮但**跳错**）：这句里是 00:29:00 ，插件会只吃掉前半截 `00:29` 当成 **29 秒**，而不是 29 分。点下去如果跳到开头附近而不是 29 分，就证实了这个坑。

A-3（说话人行，预期 ✅）：下面单独一行，格式是「名字 + 空格 + MM:SS」

主播 27:04

A-4（超 60 分，预期 ✅ 跳到 1:35:30）：这句里是 95:30 。

A-5（三位数分钟，预期 ✅ 跳到 2:15:00）：这句里是 135:00 ，接近本集末尾（全长 141 分）。

A-6（超出正则上限，预期 ❌）：四位数分钟 1350:00 不该被识别。

---

## B 组：list item —— 断言行的真实形态

**这组比 Dataview 表更要紧。** SPEC §5.1 的断言是 list item，渲染成 `<li>`；紧凑列表的 `<li>` 里通常没有 `<p>` 包裹，那么 `querySelectorAll("p")` 就扫不到。

B-1（紧凑列表，预期 ❌）：

- 第一项，时间戳 27:04
- 第二项，时间戳 95:30
- 第三项，时间戳 135:00

B-2（松散列表，项间有空行，预期 ✅ —— 松散列表会包 `<p>`）：

- 第一项，时间戳 27:04

- 第二项，时间戳 95:30

- 第三项，时间戳 135:00

B-3（真实断言行）：见 [[EP-sample]]，那边有五条完整形状的断言行。

---

## C 组：Dataview 表 —— 你要的那个场景

**这是真正的杀手锏**：跨集查到一条断言，点一下时间戳直接听主播原话。

预期 ❌ ——Dataview 渲染单元格用 `renderCompactMarkdown`，"compact" 的意思就是**把 `<p>` 包裹剥掉**，内容直接进 `<span>`。

C-1 TABLE（`录音时间戳` 用 HH:MM:SS，`播放位置` 用 MM:SS，一次看两种格式）：

```dataview
TABLE WITHOUT ID L.录音时间戳 AS "录音时间戳(HH:MM:SS)", L.播放位置 AS "播放位置(MM:SS)", split(L.text, "\\[")[0] AS "断言", L.type AS "type"
FROM "story-machine/_lab"
FLATTEN file.lists AS L
WHERE L.录音时间戳 != null
SORT L.播放位置 ASC
```

C-2 LIST（换个渲染路径试，预期同样 ❌）：

```dataview
LIST WITHOUT ID L.播放位置 + " — " + split(L.text, "\\[")[0]
FROM "story-machine/_lab"
FLATTEN file.lists AS L
WHERE L.录音时间戳 != null
```

---

## 实测发现（2026-08-03，源码已复核）

C 组通过了，`<p>` 那套推断是错的——post processor 跑在 Dataview **压缩掉 `<p>` 之前**的中间 DOM 上，按钮先造好，`<p>` 再被剥掉，按钮活了下来。但实测暴露了两个源码层面的硬限制：

### 发现一：⏸ 图标跑到最后一个，暂停必须点最后一个

不是 bug，是**插件的模型和我们的用法不同**。看 `onTimeUpdate`：

```js
onTimeUpdate(){
  let i = this.getTimestampsForAudio(...).map(...).sort((a,b)=>a.seconds-b.seconds), t=null;
  for(let s of i) if(s.seconds<=e) t=s.el; else break;   // 取「最后一个 <= 当前进度」的
  t && t!==this.activeBtn && this.setActiveBtn(t)
}
```

播放中每秒约 4 次，它把 `activeBtn` 重设为**「最后一个 seconds ≤ 当前进度」的按钮**。插件假设一篇笔记是**逐字稿**：时间戳递增、不重复，`activeBtn` 就是「播放头现在读到哪一行」，高亮跟着走——那个场景下这是特性。

我们的用法违反了两条假设：
1. **时间戳重复**——同一个 `05:00` 在 EP-sample、C-1、C-2 里各出现一次，`data-seconds` 全是 `300`，排序稳定 → **文档顺序最后那个赢**，也就是 C-2 里的那个。
2. **不递增**——Dataview 表是按查询排的，不是按时间排的。

然后 `togglePlay` 第一行：

```js
if(this.activeBtn===e && this.activeAudio){ /* 暂停/继续 */ return }
```

点 A-1 的按钮时 `activeBtn` 是 C-2 的，判等失败 → 走下面的 seek 分支 → **从 05:00 重新播**。完全对上实测。

> ⚠️ 就算时间戳不重复这条也躲不掉：点 `27:04` 播到 29 分时，`activeBtn` 会自己跳到 `29:00` 那个按钮，再点 `27:04` 同样不会暂停。**「点同一个按钮暂停」只在播到下一个时间戳之前有效。**

### 发现二：时间戳不认音频源，只认 DOM 位置 —— 这条是致命的

```js
findAudioForBtn(e,i){
  let t=Array.from(e.querySelectorAll("audio, .tsp-timestamp")), s=null;
  for(let n of t)
    if(n.tagName==="AUDIO") s=n;      // 记住最近见过的 audio
    else if(n===i) return s;          // 走到目标按钮，返回它
  return s
}
```

**绑定规则 = 文档顺序里「我上面最近的那个 `<audio>`」。和这条断言出自哪一集毫无关系。**

回答你的问题：**是的，两集的 `04:00` 放进同一张 Dataview 表一定出问题**，而且是最坏的一种：

- 表在哪个 `<audio>` 下面，**表里所有行就都播那一个音频**。
- 你点 EP07 的 `04:00`，它播 EP01 的 4 分 00 秒。**有声音、位置也对，就是集数错了**——不报错，只是放的不是那句话。
- 如果跨集查询笔记里根本没嵌音频，`findAudioForBtn` 返回 `null`，点了没反应。

也就是说：**timestamp-player 只能撑单集 EP 笔记**（一个音频、一集断言，位置绑定碰巧总是对的）。SPEC §5.1 想要的那个「跨集查到一条断言、点一下听原话」的阅读面，它撑不住。

---

## C-3（重写）：dataviewjs 自绘 —— 按数据绑音频，不按 DOM 位置

上一版写成 `querySelector("audio")` 去 DOM 里捞现成的播放器，实测报「找不到 audio」（嵌入是懒加载的，不在视口里就没有 `<audio>` 元素）。**这版不捞了，自己造一个播放器，`src` 按行所属的那一集切换。**

每行怎么知道自己是哪一集：读该集笔记 frontmatter 的 `音频:` 字段（缺省回落到 `<episode>.m4a`），
经 `metadataCache.getFirstLinkpathDest` 解析成 `TFile`，再取 `vault.getResourcePath`。
**这条链路是数据驱动的，笔记里嵌不嵌音频、嵌的是哪一集，都不影响。**

判据：`EP-sample` 和 `EP-sample2` 各有一行 `05:00`（EP02 是 EP01 的 60:00–70:00 切片，
所以它的 05:00 = EP01 的 65:00）。**两行点下去应该听到两段不同的话**——听一句就知道有没有串。

```dataviewjs
const SRC = '"story-machine/_lab"';

const toSec = (ts) => {
  const p = String(ts).trim().split(":").map(Number);
  if (p.length === 3) return p[0]*3600 + p[1]*60 + p[2];
  if (p.length === 2) return p[0]*60 + p[1];
  return 0;
};
const fmt = (s) => {
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60), x = Math.floor(s%60);
  return `${h}:${String(m).padStart(2,"0")}:${String(x).padStart(2,"0")}`;
};

// —— 每行认自己那一集的音频，和 DOM 位置无关 ——
const resolveAudio = (page) => {
  const name = page.音频 ?? page.audio ?? `${page.episode}.m4a`;
  const f = app.metadataCache.getFirstLinkpathDest(String(name), page.file.path);
  return f ? { url: app.vault.getResourcePath(f), name: f.name } : null;
};

const rows = [];
for (const p of dv.pages(SRC)) {
  if (p.file.path === dv.current().file.path) continue;
  const a = resolveAudio(p);
  for (const L of (p.file.lists ?? [])) {
    if (L.录音时间戳 == null) continue;
    rows.push({ L, page: p, audio: a });
  }
}
rows.sort((x, y) =>
  String(x.page.episode).localeCompare(String(y.page.episode))
  || toSec(x.L.录音时间戳) - toSec(y.L.录音时间戳));

// —— 自带播放器：一个 <audio>，src 随行切换 ——
const bar = dv.container.createDiv();
const nowLabel = bar.createEl("div", { text: "（未加载）" });
nowLabel.style.cssText = "font-size:0.85em;opacity:0.7;margin-bottom:4px";
const audio = bar.createEl("audio");
audio.controls = true;
audio.preload = "none";
audio.style.width = "100%";

let activeBtn = null;
const setIcon = (btn, playing) => { if (btn) btn.firstChild.textContent = playing ? "⏸ " : "▶ "; };
audio.addEventListener("play",  () => setIcon(activeBtn, true));
audio.addEventListener("pause", () => setIcon(activeBtn, false));

const jump = (btn, url, label, sec) => {
  if (activeBtn === btn && audio.dataset.src === url) {      // 同一个按钮再点 = 暂停/继续
    audio.paused ? audio.play().catch(() => {}) : audio.pause();
    return;
  }
  setIcon(activeBtn, false);
  activeBtn = btn;
  nowLabel.setText(`正在播放：${label} @ ${fmt(sec)}`);
  if (audio.dataset.src !== url) {
    audio.dataset.src = url;
    audio.src = url;
    audio.addEventListener("loadedmetadata", () => {
      audio.currentTime = sec;
      audio.play().catch(() => {});
    }, { once: true });
    audio.load();
  } else {
    audio.currentTime = sec;
    audio.play().catch(() => {});
  }
};

const table = dv.container.createEl("table", { cls: "dataview table-view-table" });
const hr = table.createEl("thead").createEl("tr");
["跳播", "集", "音频文件", "解析为", "断言"].forEach(h => hr.createEl("th", { text: h }));
const tb = table.createEl("tbody");

for (const { L, page, audio: a } of rows) {
  const sec = toSec(L.录音时间戳);
  const tr = tb.createEl("tr");
  const cell = tr.createEl("td");

  if (!a) {
    cell.setText("✗ 找不到音频文件");
  } else {
    const btn = cell.createEl("span");
    btn.createSpan({ text: "▶ " });
    btn.createSpan({ text: String(L.录音时间戳) });
    btn.style.cssText = "cursor:pointer;color:var(--text-accent);user-select:none";
    btn.onclick = () => jump(btn, a.url, String(page.episode), sec);
  }

  tr.createEl("td", { text: String(page.episode) });
  tr.createEl("td", { text: a ? a.name : "—" });
  tr.createEl("td", { text: fmt(sec) });
  tr.createEl("td", { text: String(L.text).split("[")[0].trim().slice(0, 32) });
}
```

---

## 结果回填

点完把 ❓ 改成 ✅ / ❌，不符预期的写一句现象就行。

| 编号  | 场景               | 预期          | 实测      | 备注         |
| --- | ---------------- | ----------- | ------- | ---------- |
| A-1 | 段落内联 MM:SS       | ✅           | ✅<br>   |            |
| A-2 | 段落内联 HH:MM:SS    | ⚠️ 跳错到 29 秒 | ✅跳错到29秒 |            |
| A-3 | 说话人行             | ✅           | ✅       |            |
| A-4 | 95:30 超 60 分     | ✅           | ✅       |            |
| A-5 | 135:00 三位数       | ✅           | ✅       |            |
| A-6 | 1350:00 四位数      | ❌           | ❌       |            |
| B-1 | 紧凑列表             | ❌           | ❌       |            |
| B-2 | 松散列表             | ✅           | ✅       |            |
| B-3 | 真实断言行（EP-sample） | ❌           | ✅       | 阅读模式下，没有问题 |
| C-1 | Dataview TABLE   | ❌           | ✅       |            |
| C-2 | Dataview LIST    | ❌           | ✅       |            |
| C-3 | dataviewjs 自绘（旧版）    | ✅           | ❌       | 显示找不到audio；懒加载导致 DOM 里没有 `<audio>` |

### 第二轮（2026-08-03）

`_lab` 里加了 `EP-sample2`（音频 = EP01 的 60:00–70:00 切片），C-1/C-2 现在是跨集表。

| 编号  | 场景                                             | 预期                               | 实测          | 备注                                    |
| --- | ---------------------------------------------- | -------------------------------- | ----------- | ------------------------------------- |
| D-1 | C-1 表里点 `EP-sample2 / 05:00`                   | ⚠️ 串成 EP01 的 05:00               | ✅<br>       | 听内容判断：若和 EP-sample 的 05:00 是同一段话 → 串了 |
| D-2 | C-3 新版点 `EP-sample / 05:00`                    | ✅ 播 EP01 @ 05:00                 | ✅           | 表格「音频文件」列应显示 EP01.m4a                 |
| D-3 | C-3 新版点 `EP-sample2 / 05:00`                   | ✅ 播 EP02 @ 05:00（= EP01 的 65:00） | ✅           | **和 D-2 必须是两段不同的话**                   |
| D-4 | C-3 新版 同一按钮再点一次                                | ✅ 暂停                             | ✅           | 不再受「⏸ 跑到最后一个」影响                       |
| D-5 | C-3 新版 HH:MM:SS 行（EP-sample A-02 的 `00:29:00`） | ✅ 正确跳到 29 分                      | ✅ 正确跳到 29 分 | 「解析为」列应显示 `0:29:00`                   |

### 第三轮（2026-08-03）：自研插件 story-machine-timestamps v0.1.0

**目标：正文里的时间戳直接可点，不靠底部塞 dataviewjs 块。**

已停用 `timestamp-player`，启用 `story-machine-timestamps`。**必须重启 Obsidian**（Ctrl+P → `Reload app without saving`）才生效。

和旧插件的四处不同：
1. 音频按**本笔记 frontmatter 的 `音频:` 字段**解析 → 和 DOM 位置无关；没声明 `音频:` 的笔记完全不介入。
2. 用 TreeWalker 扫**全部文本节点**，不只是 `<p>` → 紧凑列表、表格单元格都吃得下。
3. 正则认 `MM:SS` **和** `HH:MM:SS` → SPEC §5.3 的格式原生可用。
4. `activeBtn` 只由点击改变，**不跟播放进度跑** → 点同一个按钮一定是暂停。
5. 播放器是插件自己造的右下角浮动条 → 不受嵌入懒加载影响，笔记里不用再写 `![[EP01.m4a]]`。

还有一处**故意的不作为**：Dataview 查询块（`.block-language-dataview(js)`）里的内容一律跳过。
因为查询结果的行可能来自别的集，而本插件只认「本笔记的 frontmatter」，接管了就会串音频（D-1 那个坑）。
**跨集阅读面仍然走 C-3 的 dataviewjs 自绘。** 这是分工，不是缺陷。

| 编号  | 场景                                  | 预期                            | 实测                                  | 备注              |
| --- | ----------------------------------- | ----------------------------- | ----------------------------------- | --------------- |
| E-1 | 本笔记 A-1 正文段落 `29:00`                | ✅ 可点，跳 29 分                   | ✅                                   |                 |
| E-2 | 本笔记 A-2 正文 `00:29:00`               | ✅ **跳 29 分**（旧插件跳 29 秒）       | ✅                                   | 这条是旧插件最大的坑，重点看  |
| E-3 | 本笔记 B-1 紧凑列表 `27:04`                | ✅ 可点（旧插件 ❌）                   | ✅                                   |                 |
| E-4 | [[EP-sample]] 断言行 `[录音时间戳:: 27:04]` | ✅ 就地可点                        | 断言行的点不了，松散的可以点                      | **你要的那个「直接能点」** |
| E-5 | [[EP-sample2]] 断言行 `05:00`          | ✅ 播 EP02（≠ EP-sample 的 05:00） | 下方的播放条始终是EP02，点击60：00也是EP02，而不是EP01 | 两篇笔记各自绑各自的音频    |
| E-6 | 同一按钮连点两次                            | ✅ 第二次暂停                       | 没问题                                 | 播一会儿再点，确认不受进度影响 |
| E-7 | 本笔记 C-1 / C-2 查询表里的时间戳              | ✅ **不**变按钮（纯文本）               | 纯文本                                 | 故意的：防跨集串音频      |
| E-8 | 本笔记 A-6 `1350:00`                   | ✅ 不识别                         | 没问题                                 |                 |
| E-9 | 点完切到别的笔记                            | ✅ 右下角播放条还在、还在播                | 没问题                                 |                 |

### 第四轮（2026-08-03）：v0.2.0，修 E-4 + 收窄扫描范围

**E-4 是真 bug。** 松散列表能点、断言行不能点，唯一差别是断言行里有 inline field ——
Dataview 在我们装好按钮之后重画那一行，把按钮抹了。
修法：post processor 排到 `sortOrder=200` 最后跑，**再挂一个 MutationObserver 补画**（80ms 防抖，
`root` 脱离 DOM 就自动断开）。重画多少次都补得回来。

**E-5 不是绑错，是我扫描范围开太宽。** 你点的 `60:00` 在正文那句「本集音频是 EP01 的 60:00–70:00 切片」里 ——
那篇笔记声明 `音频: EP02.m4a`，插件播 EP02 是按设计执行的（而 EP02 只有 10 分钟，seek 到 3600 秒直接顶到末尾）。
但那个 `60:00` 根本不是播放位置，是句子里提到的数字，不该长成按钮。

新增 frontmatter 开关 **`时间戳范围:`**：

| 值 | 行为 | 用在哪 |
| --- | --- | --- |
| `字段`（默认，可省略） | 只有 `[录音时间戳:: ...]` `[播放位置:: ...]` 的值变按钮 | **生产 EP 笔记** |
| `全文` | 正文里任何 `MM:SS` / `HH:MM:SS` 都变按钮 | 本实验笔记 |

本笔记已设 `全文`，`EP-sample` / `EP-sample2` 保持默认 `字段`。

顺带修了 `currentTime` 不再越过 `duration`（EP02 只有 10 分钟，点 60:00 会顶到末尾而不是静默失败）。

**改完要再重启一次 Obsidian。**

| 编号  | 场景 | 预期 | 实测 | 备注 |
| --- | --- | --- | --- | --- |
| F-1 | [[EP-sample]] 断言行 `[录音时间戳:: 27:04]` | ✅ 可点，播 EP01 @ 27:04 | ❓ | **E-4 重测，这条是关键** |
| F-2 | [[EP-sample]] 同一行的 `[播放位置:: 27:04]` | ✅ 也可点（两个 key 都在白名单） | ❓ | 一行两个 ▶ 是预期的 |
| F-3 | [[EP-sample2]] 正文「EP01 的 60:00–70:00 切片」 | ✅ **不**变按钮 | ❓ | 字段模式的直接效果 |
| F-4 | [[EP-sample2]] 断言行 `[录音时间戳:: 05:00]` | ✅ 可点，播 EP02 @ 05:00 | ❓ | |
| F-5 | 先点 F-1 再点 F-4 | ✅ 播放条标签 EP01.m4a → EP02.m4a，内容明显不同 | ❓ | **跨集切换的真正验证**（E-5 没验成的那条） |
| F-6 | [[EP-sample]] B-6 松散列表的正文时间戳 | ✅ **不**再可点 | ❓ | 字段模式的预期代价，确认一下你能接受 |
| F-7 | 本笔记 A 组 / B 组 | ✅ 仍可点（本笔记是 `全文`） | ❓ | 开关生效的反向确认 |
| F-8 | 本笔记 C-1 / C-2 查询表 | ✅ 仍是纯文本 | ❓ | 跨集防线没被 observer 破坏 |

### 第五轮（2026-08-03）：v0.3.0，修 F-4 + 默认改回全文 + 限定符

**F-4「有按钮但不播」查到三个可疑点，一起堵掉**（`EP02.m4a` 本身没问题：ffprobe 显示 600.0s / AAC / start_time=0，排除了文件损坏）：

1. **`loadedmetadata` 可能在挂 listener 之前就过去了。** `EP-sample2` 里嵌了 `![[EP02.m4a]]`，文件已在缓存，元数据可能同步就绪 → 我们 `addEventListener` 时事件早就发过了，于是**永远等下去**。改成先查 `readyState >= 1`，够了就直接 seek。
2. **按钮被 Dataview 换掉导致 `click` 不触发。** mousedown 落在旧节点、mouseup 落在新节点时，浏览器根本不发 `click`。改成**事件委托 + `pointerdown`**：一个 listener 挂在 `document` 上，按钮信息存 `data-sm-*`，换多少次都点得动。
3. **静默失败。** `play()` 的 rejection 原来被 `.catch(()=>{})` 吞了。现在加了 `error` 监听，加载失败会在播放条上显示 `✗ 加载失败（code N）`。

**F-3 / F-6：默认改回 `全文`。** 你要正文裸时间戳可点，那就该是默认。你指出的真问题——"分不出两个时间戳背后是不同音频"——用两个机制解决，而不是靠禁用：

| 写法 | 效果 |
| --- | --- |
| `05:00` | 绑**本笔记** frontmatter 的 `音频:`（默认） |
| `EP01@60:00` | **限定符**：指名道姓绑 EP01，不跟本笔记走。名字可以是音频文件，也可以是一篇声明了 `音频:` 的集笔记 |
| `` `05:00` `` | 反引号 = **逃生舱**，不变按钮 |
| `时间戳范围: 字段` | 整篇只认 `[录音时间戳:: ...]` 字段值（v0.2 的旧默认，现在是可选项） |

`EP-sample2` 正文已改用限定符，顺便当例子。

**改完要再重启一次 Obsidian。**

| 编号  | 场景 | 预期 | 实测 | 备注 |
| --- | --- | --- | --- | --- |
| G-1 | [[EP-sample2]] 断言行 `[录音时间戳:: 05:00]` | ✅ **能播** EP02 @ 05:00 | ❓ | **F-4 重测，这条是关键** |
| G-2 | 先点 [[EP-sample]] 的 27:04 再点 G-1 | ✅ 播放条 EP01.m4a → EP02.m4a，内容明显不同 | ❓ | **F-5 重测：跨集切换** |
| G-3 | [[EP-sample]] B-6 松散列表正文时间戳 | ✅ 恢复可点 | ❓ | 默认改回全文 |
| G-4 | [[EP-sample2]] 正文 `EP01@60:00` | ✅ 播 **EP01** @ 60:00（不是 EP02） | ❓ | 限定符 |
| G-5 | [[EP-sample2]] 正文反引号里的 `05:00` | ✅ 不变按钮 | ❓ | 逃生舱 |
| G-6 | 本笔记 A 组 / B 组 | ✅ 仍可点 | ❓ | |
| G-7 | 本笔记 C-1 / C-2 查询表 | ✅ 仍是纯文本 | ❓ | 跨集防线 |

> **如果 G-1 还是不播**：在 [[EP-sample2]] 的 frontmatter 加一行 `时间戳调试: true`，
> 重启后按 `Ctrl+Shift+I` 打开开发者工具的 Console，再点一次，把 `[sm-ts]` 开头的输出发我。
> 那会直接告诉我卡在 `readyState`、`play rejected` 还是 `audio error`。
