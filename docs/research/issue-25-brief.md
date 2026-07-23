## 问的是什么

「下载管理前端」开工前查现成参考：MeTube / yt-dlp-web-ui / ytptube / Tube Archivist，在 Windows 部署、批量导入、历史存储、完成 hook 上各是什么形态，该自建还是部署现成？

## 答案是什么

现成首选 **ytptube**：唯一官方 Windows 二进制、批量、`ITEM_COMPLETED` webhook 可直接串转写、MIT、最活跃。自建则抄 MeTube 的三态 JSON 队列 + WebSocket 进度 + cookies 上传，靠目录监听串链。yt-dlp-web-ui（Linux-only、无 hook）与 Tube Archivist（媒体库过重）排除。

## 对项目意味着什么

下游 grilling 票优先评估「部署 ytptube」为基线，其 webhook 接阶段 0 转写触发。spec 建议在阶段 0 前补「取音频产物落 `E:\asr\audio\`、下游按目录监听/webhook 触发」，并把多 P 策略列入未决——MeTube 强制 `noplaylist` 会把多 P 默认只抓第 1 P，与现 `dl-audio.ps1`「多 P 全下」相反。

## 最不可靠的地方

① MeTube「多 P 只抓第 1 P」是源码静态分析、未真机实测——若错，给 grilling 票的「MeTube 漏抓」警告方向就反了。验证：真机跑一个多 P BV，看入队 1 条还是 N 条。② ytptube 绕 412 风控的 `curl-cffi` 仅 Docker 生效——Windows 原生若靠 cookies/直连绕不过，非 Docker 路径缩水。验证：5070 原生二进制实跑一个 B 站风控链接。
