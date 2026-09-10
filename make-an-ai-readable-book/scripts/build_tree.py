# -*- coding: utf-8 -*-
"""把一本 EPUB 生成"Agent 渐进披露书库"：书 → 章 → 小节 → 段落文件。

用法：python build_tree.py --epub <epub路径> [--out <输出目录>]
产出：章/小节/段落文件、三级记录文件（目录.md、00_章节记录.md、00_小节记录.md）、
      SKILL.md（协议初版）、_build_stats.json（供 make_skill.py 使用）。
仅标准库。默认输出到 EPUB 同目录、以书名命名的文件夹。
"""
import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from epublib import (BookInfo, block_to_text, book_description, book_slug,
                     chapter_plan, excerpt, extract_file, fm, parse_toc, sanitize,
                     sec_folder_name, wan_chars)


def skill_md(title: str, author: str, name: str, n_ch: int, n_sec: int, n_par: int, chars: int) -> str:
    desc = book_description(title, author)
    body = f"""# 《{title}》—— 给 AI 阅读的书（阅读协议）

本文件夹是《{title}》的 AI 阅读版（{n_ch} 章 / {n_sec} 小节 / {n_par} 个段落文件 / 正文约 {wan_chars(chars)}字），供 AI/Agent **按需检索、逐级下钻**使用，不要求也不建议通读；人类读者请从 `目录.md` 进入。

## 渐进披露层级

| 层级 | 位置 | 内容 | 何时读取 |
| --- | --- | --- | --- |
| L0 元数据 | 本文件头部 frontmatter | 书名、触发场景 | 系统自动；判断是否使用本库 |
| L1 协议 | 本文件正文 | 导航规则与检索方法 | 进入本库必读（仅本文件） |
| L2 全书导航 | `目录.md`、`索引.md` | 章级列表+一句话导读；关键词直达表 | 明确了大方向后，据此定位章/小节 |
| L3 章摘要 | `NN_章名/00_章节记录.md` | 本章要点、逐小节要点、核心概念、小节导航表 | 锁定候选章后读（每份数百字） |
| L4 小节导航 | `.../NN_小节名/00_小节记录.md` | 段落文件导航（类型+40字摘录）、首段摘录 | 候选小节内筛选具体段落 |
| L5 原文 | `.../段落_NNN.md` | 逐段原文（每文件一段） | 只打开 L4 摘录显示相关的段落 |

## 使用规则

1. **自上而下**：永远先读高层记录文件，再决定是否下钻；禁止一开始就批量读取 `段落_*.md`，禁止为回答单一问题通读全书。
2. **带着问题检索**：先在 `索引.md` 查关键词，或对全库 `grep`（各记录文件头部 frontmatter 含 `keywords` 字段，段落原文均可全文检索），命中后跳到对应 `00_小节记录.md`。
3. **按摘录取舍**：L4 的内容导航为每个段落文件标注类型（正文/小标题/插图/脚注）并给出 40 字摘录，只打开摘录与问题相关的段落文件。
4. **引用溯源**：回答时引用所依据的相对路径（如 `NN_章名/NN_小节名/段落_001.md`），方便人工核对。
5. **元数据可编程**：三级记录文件均有 YAML frontmatter（`type/chapter/section/source/paragraph_files/chars/keywords` 等字段），可脚本化遍历而无需解析正文。

## 注意事项

- 正文中 `[图: 文件名.jpg]` 为插图占位符（图片在原 EPUB 的 Images 目录内，未随库导出）；部分附录/参考文献页在原书中可能是扫描图片，仅有占位符、无可提取文字。
- 各段文件为原书原文（仅作个人学习整理），引用时保持原意并注明出处。
- 入口文件：`SKILL.md`（本文件）｜全书目录：`目录.md`｜关键词索引：`索引.md`。
"""
    return fm({"name": name, "description": desc}) + "\n\n" + body + "\n"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="EPUB → Agent 渐进披露书库")
    ap.add_argument("--epub", required=True)
    ap.add_argument("--out", help="输出目录（默认：EPUB 同目录下以书名命名）")
    args = ap.parse_args()

    epub = Path(args.epub).resolve()
    with zipfile.ZipFile(epub) as z:
        info = BookInfo(epub, z)
        out = Path(args.out).resolve() if args.out else epub.parent / sanitize(info.title)
        if out.exists():
            print(f"输出目录已存在，先清空重建：{out}")
            shutil.rmtree(out)
        out.mkdir(parents=True)

        tops, deep = parse_toc(z, info)
        if deep:
            print(f"提示：{deep} 个超过 2 级的目录条目已并入所属章。")

        stats = {"book": out.name, "title": info.title, "author": info.author,
                 "skill_name": book_slug(info.title), "chapters": []}
        total_par = total_chars = 0

        for ci, ch in enumerate(tops):
            ch_dir_name = f"{ci:02d}_{sanitize(ch['label'])}"
            ch_dir = out / ch_dir_name
            ch_dir.mkdir(parents=True)

            ch_rows = []
            ch_par = ch_chars = 0
            for si, s in enumerate(chapter_plan(ch)):
                sec_dir = ch_dir / f"{si:02d}_{sec_folder_name(s['label'])}"
                sec_dir.mkdir()
                h1, h2, blocks = extract_file(z, s["base"])

                flow = [b for b in blocks if b["kind"] not in ("h1", "h2", "imgbox")]
                nav_lines = []
                n_sub = n_img = n_fn = n_p = chars = 0
                first_p = ""
                for bi, b in enumerate(flow, 1):
                    fname = f"段落_{bi:03d}.md"
                    (sec_dir / fname).write_text(block_to_text(b), encoding="utf-8")
                    if b["kind"] == "sub":
                        n_sub += 1
                        nav_lines.append(f"- [{fname}]({fname})｜小标题｜{b['text']}")
                    elif b["kind"] == "img":
                        n_img += 1
                        nav_lines.append(f"- [{fname}]({fname})｜插图｜{b['img']}")
                    elif b["kind"] == "fnote":
                        n_fn += 1
                        nav_lines.append(f"- [{fname}]({fname})｜脚注｜{excerpt(b['text'], 40)}")
                    else:
                        n_p += 1
                        chars += len(b["text"])
                        nav_lines.append(f"- [{fname}]({fname})｜正文｜{excerpt(b['text'], 40)}")
                        if not first_p:
                            first_p = b["text"]

                import re
                num_m = re.match(r"^(\d+)\.", s["label"])
                rec = [f"# {s['label']}", "",
                       "| 项 | 内容 |", "| --- | --- |",
                       f"| 所属章 | {ch['label']} |",
                       f"| 原书编号 | {num_m.group(1) if num_m else '—'} |",
                       f"| 来源文件 | {s['base']} |",
                       f"| 段落文件 | 共 {len(flow)} 个：正文 {n_p} ｜ 小标题 {n_sub} ｜ 插图 {n_img} ｜ 脚注 {n_fn} |",
                       f"| 正文字数 | 约 {chars} 字 |"]
                if h1 and h1 != ch["label"]:
                    rec.append(f"| 文件内主标题（h1） | {h1} |")
                if h2 and h2 != s["label"]:
                    rec.append(f"| 小节标题（h2） | {h2} |")
                if s["note"]:
                    rec.append(f"| 说明 | {s['note']} |")
                rec += ["", "## 内容导航", *nav_lines, ""]
                if first_p:
                    rec += ["## 首段摘录", f"> {excerpt(first_p, 120)}", ""]
                (sec_dir / "00_小节记录.md").write_text("\n".join(rec), encoding="utf-8")

                ch_rows.append((s["label"], sec_dir.name, len(flow), chars))
                ch_par += len(flow)
                ch_chars += chars

            nav_table = ["| 序号 | 小节 | 段落文件数 | 正文字数 |", "| --- | --- | --- | --- |"]
            for ri, r in enumerate(ch_rows):
                nav_table.append(f"| {ri:02d} | [{r[1]}]({r[1]}/00_小节记录.md) | {r[2]} | {r[3]} |")
            chapter_rec = [f"# {ch['label']}", "",
                           "| 项 | 内容 |", "| --- | --- |",
                           f"| 来源文件 | {ch['base']} |",
                           f"| 小节数 | {len(ch_rows)} |",
                           f"| 段落文件总数 | {ch_par} |",
                           f"| 正文字数 | 约 {ch_chars} 字 |",
                           "", "## 小节导航", *nav_table, "",
                           "## 本章要点（AI 摘要）",
                           "> 待撰写：由 AI 阅读本章各小节后补写。", ""]
            (ch_dir / "00_章节记录.md").write_text("\n".join(chapter_rec), encoding="utf-8")

            stats["chapters"].append({
                "order": ci, "dir": ch_dir_name, "label": ch["label"],
                "sections": [{"dir": r[1], "label": r[0], "par": r[2], "chars": r[3]} for r in ch_rows],
                "par_total": ch_par, "chars": ch_chars,
            })
            total_par += ch_par
            total_chars += ch_chars
            print(f"{ch_dir_name}｜小节 {len(ch_rows)}｜段落 {ch_par}｜约 {ch_chars} 字")

    # --- 顶层 目录.md ---
    toc_lines = []
    for c in stats["chapters"]:
        toc_lines.append(f"- [{c['dir']}](./{c['dir']}/00_章节记录.md)｜{c['label']}｜{len(c['sections'])} 小节｜{c['par_total']} 段")
        for s in c["sections"]:
            toc_lines.append(f"  - [{s['dir']}](./{c['dir']}/{s['dir']}/00_小节记录.md)｜{s['label']}｜{s['par']} 段")
    head = [
        fm({"type": "book_toc", "book": out.name, "author": info.author or "—",
            "entry": "SKILL.md", "index": "索引.md", "chapters": len(stats["chapters"]),
            "sections": sum(len(c["sections"]) for c in stats["chapters"]),
            "paragraph_files": total_par, "chars": total_chars}),
        "",
        f"# 《{info.title}》结构化文本库",
        "",
        f"> **Agent 渐进披露入口与阅读协议：[SKILL.md](SKILL.md)** ｜ 关键词直达：[索引.md](索引.md)",
        f"> 作者：{info.author or '—'}",
        f"> 层级：书 → 章 → 小节 → 段落。章文件夹含 00_章节记录.md；小节文件夹含 00_小节记录.md 与逐段文件 段落_NNN.md。",
        f"> 插图未导出，正文中以 `[图: 文件名.jpg]` 占位（图片位于 EPUB 原文件的 Images 目录）。",
        "",
        "## 全书统计",
        f"- 章：{len(stats['chapters'])} ｜ 小节：{sum(len(c['sections']) for c in stats['chapters'])} ｜ 段落文件：{total_par} ｜ 正文约 {total_chars} 字",
        "",
        "## 目录",
        *toc_lines,
        "",
        "## 导读（AI 摘要）",
        "> 待撰写。",
        "",
    ]
    (out / "目录.md").write_text("\n".join(head), encoding="utf-8")

    # --- SKILL.md（协议初版，make_skill.py 阶段会升级描述）---
    (out / "SKILL.md").write_text(
        skill_md(info.title, info.author, stats["skill_name"], len(stats["chapters"]),
                 sum(len(c["sections"]) for c in stats["chapters"]), total_par, total_chars),
        encoding="utf-8")

    # --- 统计文件（供 make_skill.py / 后续工具使用）---
    stats.update({"total_par": total_par, "total_chars": total_chars})
    (out / "_build_stats.json").write_text(json.dumps(stats, ensure_ascii=False, indent=2),
                                           encoding="utf-8")

    print(f"\n完成：{len(stats['chapters'])} 章 / "
          f"{sum(len(c['sections']) for c in stats['chapters'])} 小节 / {total_par} 个段落文件，"
          f"正文约 {total_chars} 字")
    print(f"书库位置：{out}")
    print("下一步：validate.py 校验 → AI 摘要与 keywords.json → make_skill.py")


if __name__ == "__main__":
    main()
