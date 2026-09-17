# -*- coding: utf-8 -*-
"""vault 里各目录的位置（SPEC §4.1 文件位置、§6）。

scope 是「EP{n}」或「{date}」：`_pairs/` `_digest/` `_failed/` 三处都按它分目录，
所以这三个方法只差一个根。
"""
from __future__ import annotations

from pathlib import Path

from .note import read_frontmatter, read_note


class VaultPaths:
    def __init__(self, vault: str | Path):
        self.vault = Path(vault)

    @property
    def assets(self) -> Path:
        return self.vault / "_assets"

    @property
    def episodes(self) -> Path:
        return self.vault / "10-Episodes"

    @property
    def daily(self) -> Path:
        return self.vault / "20-Daily"

    @property
    def events(self) -> Path:
        return self.vault / "30-Events"

    def pairs(self, scope: str) -> Path:
        return self.vault / "_pairs" / scope

    def digest(self, scope: str) -> Path:
        return self.vault / "_digest" / scope

    def failed(self, scope: str) -> Path:
        return self.vault / "_failed" / scope

    def transcript(self, ep: str) -> Path:
        return self.assets / f"{ep}.transcript.json"

    def find_episode_note(self, ep: str) -> Path | None:
        return find_episode_note(self.episodes, ep)

    def rel(self, p: Path) -> str:
        """日志里用的短路径：vault 外的照原样打。"""
        try:
            return str(Path(p).relative_to(self.vault))
        except ValueError:
            return str(p)


def find_episode_note(episodes_dir: str | Path, ep: str) -> Path | None:
    """先按文件名（`EP91 标题.md` / `EP91.md`），再按 frontmatter 的 `episode`。

    人会改标题，所以文件名不是唯一线索；但文件名命中时不必读全目录的 YAML。
    """
    d = Path(episodes_dir)
    if not d.is_dir():
        return None
    named = sorted(d.glob(f"{ep} *.md")) + sorted(d.glob(f"{ep}.md"))
    if named:
        return named[0]
    for f in sorted(d.glob("*.md")):
        fm = read_frontmatter(read_note(f))
        if str(fm.get("episode") or "").strip() == ep:
            return f
    return None
