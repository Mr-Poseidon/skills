# -*- coding: utf-8 -*-
"""为书库注入渐进披露元数据（在 AI 摘要阶段之后运行）：

1. 给 00_章节记录.md / 00_小节记录.md / 目录.md 注入 YAML frontmatter
   （类型、所属、来源、统计、keywords——来自书库内 keywords.json，按小节序号对齐）。
2. 生成关键词直达索引 索引.md。
3. 升级 SKILL.md 的 description（追加关键词主题，便于其他 Agent 触发）。

用法：python make_skill.py --out <书库目录> [--keywords <keywords.json路径>]
keywords.json 默认取 <书库>/keywords.json（由 AI 阶段撰写；不存在则跳过关键词注入）。
幂等：重复运行会先剥离旧 frontmatter 再重新注入；索引.md 每次重建。
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from epublib import book_description, fm, strip_fm

BOOK_TITLE_KEY = "title"


def get_source(text: str) -> str:
    m = re.search(r"\|\s*来源文件\s*\|\s*([^|]+?)\s*\|", text)
    return m.group(1) if m else ""


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="注入渐进披露元数据并生成索引")
    ap.add_argument("--out", required=True, help="书库目录")
    ap.add_argument("--keywords", help="keywords.json 路径（默认 <书库>/keywords.json）")
    args = ap.parse_args()

    out = Path(args.out).resolve()
    stats = json.loads((out / "_build_stats.json").read_text(encoding="utf-8"))
    kw_path = Path(args.keywords).resolve() if args.keywords else out / "keywords.json"
    kws = {}
    if kw_path.is_file():
        kws = json.loads(kw_path.read_text(encoding="utf-8"))
        print(f"关键词来源：{kw_path}")
    else:
        print(f"警告：未找到 {kw_path}，将注入不含 keywords 的 frontmatter；"
              f"AI 摘要阶段完成后重跑本脚本可补上。")

    n_ch = n_sec = 0
    missing = []
    index_lines = [
        fm({"type": "index", "book": stats.get("title", out.name),
            "entry": "SKILL.md", "toc": "目录.md",
            "chapters": len(stats["chapters"]),
            "sections": sum(len(c["sections"]) for c in stats["chapters"])}),
        "",
        "# 关键词直达索引",
        "",
        "> 用法：Ctrl+F / grep 查找主题关键词 → 命中行即目标小节 → 打开其 `00_小节记录.md`，再按导航选读 `段落_NNN.md`。各小节记录文件头部 frontmatter 中含同样一组 `keywords`，可直接对全库检索。",
        "",
    ]
    all_ch_kws = []

    for c in stats["chapters"]:
        ch_dir = out / c["dir"]
        kinfo = kws.get(c["dir"], {})
        ch_kws = kinfo.get("chapter_keywords", [])
        all_ch_kws.extend(ch_kws)
        sec_kws = kinfo.get("sections", {})

        rec = ch_dir / "00_章节记录.md"
        text = strip_fm(rec.read_text(encoding="utf-8"))
        rec.write_text(fm({
            "type": "chapter_record", "book": stats.get("title", out.name),
            "chapter": c["label"], "dir": c["dir"], "order": c["order"],
            "source": get_source(text), "sections": len(c["sections"]),
            "paragraph_files": c["par_total"], "chars": c["chars"],
            "keywords": ch_kws,
        }) + "\n\n" + text, encoding="utf-8")
        n_ch += 1

        index_lines.append(f"## {c['order']:02d} {c['label']}")
        for si, s in enumerate(c["sections"]):
            kw = sec_kws.get(str(si), [])
            if not kw:
                missing.append(f"{c['dir']}/{s['dir']}")
            index_lines.append(
                f"- [{s['label']}](./{c['dir']}/{s['dir']}/00_小节记录.md)｜{s['par']} 段｜关键词：{'、'.join(kw) if kw else '—'}")
            index_lines.append("")

            sec_rec = ch_dir / s["dir"] / "00_小节记录.md"
            stext = strip_fm(sec_rec.read_text(encoding="utf-8"))
            sec_rec.write_text(fm({
                "type": "section_record", "book": stats.get("title", out.name),
                "chapter": c["label"], "chapter_record": "../00_章节记录.md",
                "section": s["label"], "dir": s["dir"], "order": si,
                "source": get_source(stext), "paragraph_files": s["par"],
                "chars": s["chars"], "keywords": kw,
            }) + "\n\n" + stext, encoding="utf-8")
            n_sec += 1

    # --- 目录.md frontmatter（幂等重建）---
    toc = out / "目录.md"
    ttext = strip_fm(toc.read_text(encoding="utf-8"))
    toc.write_text(fm({
        "type": "book_toc", "book": stats.get("title", out.name),
        "author": stats.get("author", "—"), "entry": "SKILL.md", "index": "索引.md",
        "chapters": len(stats["chapters"]),
        "sections": sum(len(c["sections"]) for c in stats["chapters"]),
        "paragraph_files": stats["total_par"], "chars": stats["total_chars"],
    }) + "\n\n" + ttext, encoding="utf-8")

    (out / "索引.md").write_text("\n".join(index_lines), encoding="utf-8")

    # --- 升级 SKILL.md（重新生成 description：基础描述 + 关键词主题）---
    skill = out / "SKILL.md"
    stext = strip_fm(skill.read_text(encoding="utf-8"))
    topic_line = ""
    if all_ch_kws:
        uniq = list(dict.fromkeys(all_ch_kws))
        topic_line = f"涉及主题：{'、'.join(uniq[:24])}等。"
    desc = book_description(stats.get("title", out.name), stats.get("author", "")) + topic_line
    skill.write_text(fm({"name": stats.get("skill_name", "book-library"),
                         "description": desc}) + "\n\n" + stext, encoding="utf-8")

    print(f"frontmatter 注入：章 {n_ch}｜小节 {n_sec}")
    if missing:
        print(f"警告：{len(missing)} 个小节缺关键词（keywords.json 中缺对应序号），如：{missing[:5]}")
    print(f"已生成 {out / '索引.md'}，并升级 {out / 'SKILL.md'} 的 description")


if __name__ == "__main__":
    main()
