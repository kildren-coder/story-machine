# story-machine-timestamps

把笔记正文里的 `MM:SS` / `HH:MM:SS` 变成可点跳播按钮。

## 为什么不用现成的 timestamp-player

`timestamp-player` 的按钮绑定音频靠 **DOM 位置**——`findAudioForBtn` 沿文档顺序找「我上面最近的那个 `<audio>`」，和这条断言出自哪一集无关。在跨集查询表里，整张表会全播同一个音频：点 EP07 的 `04:00`，播的是 EP01 的 4 分 00 秒，**有声音、位置也对，就是集数错了，还不报错**。另有两个坑：正则只认 `MM:SS`，`00:29:00` 被解析成 29 **秒**（SPEC §5.9 用的正是 `HH:MM:SS`，静默错 60 倍）；`activeBtn` 跟播放进度走，导致「点同一个按钮暂停」失效。

实测记录见 vault 里的 `story-machine/_lab/T-时间戳跳播验证.md`。

## 设计

- **两条渲染路径，因为 Obsidian 有两套渲染器**（v0.4.0）：阅读视图走 `registerMarkdownPostProcessor` + DOM TreeWalker；实时预览走 CodeMirror 6 `ViewPlugin` 装饰——**post processor 在实时预览里完全不跑**，只做它的话时间戳就只在阅读视图可点，而阅读视图改不了字。审草稿时要一边改一边点，两个都得有。光标落进某个时间戳时该处不装饰、露出原文，否则没法编辑。`@codemirror/*` 的 require 包在 try 里，拿不到就只丢实时预览这条路。
- **音频按数据绑，不按位置**：读本笔记 frontmatter 的 `音频:`（回落 `audio:`），经 `metadataCache.getFirstLinkpathDest` 解析成 `TFile`，取 `vault.getResourcePath`。
- **没声明 `音频:` 的笔记完全不介入**——这既是开关，也是跨集串音频的防线。
- **跳过 Dataview 查询块**（`.block-language-dataview` / `.block-language-dataviewjs`）：查询结果的行可能来自别的集，本插件按「本笔记的 frontmatter」绑音频，接管了就会绑错。跨集阅读面走 dataviewjs 自绘。
- **TreeWalker 扫全部文本节点**，紧凑列表 / 表格单元格都覆盖。
- **`activeBtn` 只由点击改变**，不跟播放进度走。
- **播放器由插件自己造**（右下角浮动条），不去 DOM 里捞 `![[x.m4a]]` 嵌入——嵌入是懒加载的，不在视口里根本没有 `<audio>` 元素。笔记因此不必再写嵌入行。

- **Dataview 重画后补画**：Dataview 会在 post processor 跑完之后重画 inline field，把按钮抹掉（v0.1.0 的 E-4 就栽在这里）。所以除了排到 `sortOrder=200` 最后跑，还挂一个 MutationObserver 补画（80ms 防抖，`root` 脱离 DOM 自动断开）。

## 用法

EP 笔记 frontmatter 加一行：

```yaml
音频: EP01.m4a
```

正文里的时间戳即可点：`27:04`（27 分 04 秒）和 `00:29:00`（29 分）都认，分钟位最多三位（`135:00` 可以，`1350:00` 不识别）。

### 每个时间戳绑哪个音频

| 写法 | 效果 |
| --- | --- |
| `05:00` | 绑本笔记 frontmatter 的 `音频:` |
| `EP01@60:00` | 限定符：绑指定的一集。名字可以是音频文件（`EP01` / `EP01.m4a`），也可以是一篇声明了 `音频:` 的集笔记 |
| `` `05:00` `` | 反引号 = 逃生舱，不变按钮（走的是 `code` 跳过规则） |

正文里提到别集的时间轴时用限定符，否则会静默绑到本集 —— 有声音、位置也对，就是集数错了。

### 扫描范围

| frontmatter | 行为 |
| --- | --- |
| 缺省 / `时间戳范围: 全文` | 正文里任何 `MM:SS` / `HH:MM:SS` 都变按钮 |
| `时间戳范围: 字段` | 只有 `FIELD_KEYS`（`录音时间戳` / `播放位置` / `timestamp`）的字段值变按钮 |

字段识别走两条路，Dataview 渲不渲染 inline field 都能认：祖先 `.inline-field` 上读 `.inline-field-key`；读不到就在同一个文本节点里向前 40 字符找 `[key::`。

### 排障

frontmatter 加 `时间戳调试: true`，重启后开 `Ctrl+Shift+I` 的 Console，点击时会打 `[sm-ts]` 前缀的日志（`readyState` / `play rejected` / `audio error`）。加载失败也会直接显示在播放条上，不再静默。

## 安装

无构建步骤，纯 CommonJS。复制三个文件到 vault：

```powershell
$dst = "D:\obsidian-task\任务栏\.obsidian\plugins\story-machine-timestamps"
New-Item -ItemType Directory -Force $dst | Out-Null
Copy-Item manifest.json, main.js, styles.css $dst
```

然后在 `.obsidian/community-plugins.json` 里加上 `"story-machine-timestamps"`，重启 Obsidian。
