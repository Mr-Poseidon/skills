# -*- coding: utf-8 -*-
"""校验生成的书库与 EPUB 源的一致性（逐段落比对 + 记录文件齐全性）。

用法：python validate.py --epub <epub路径> --out <书库目录>
必须全部通过后才能进入 AI 摘要阶段。
"""
import argparse
import re
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from epublib import BookInfo, chapter_plan, extract_file, parse_toc, sanitize, sec_folder_name


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="校验书库与 EPUB 源一致")
    ap.add_argument("--epub", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    errors = []

    def expect(cond, msg):
        if not cond:
            errors.append(msg)

    epub = Path(args.epub).resolve()
    out = Path(args.out).resolve()
    with zipfile.ZipFile(epub) as z:
        info = BookInfo(epub, z)
        tops, _ = parse_toc(z, info)
        expect(out.is_dir(), f"缺少输出目录 {out}")
        expect((out / "目录.md").is_file(), "缺少顶层 目录.md")
        expect((out / "SKILL.md").is_file(), "缺少顶层 SKILL.md")

        n_ch = n_sec = n_par = 0
        for ci, ch in enumerate(tops):
            ch_dir = out / f"{ci:02d}_{sanitize(ch['label'])}"
            expect(ch_dir.is_dir(), f"缺少章文件夹 {ch_dir.name}")
            expect((ch_dir / "00_章节记录.md").is_file(), f"{ch_dir.name} 缺少 00_章节记录.md")
            n_ch += 1

            for si, s in enumerate(chapter_plan(ch)):
                sec_dir = ch_dir / f"{si:02d}_{sec_folder_name(s['label'])}"
                expect(sec_dir.is_dir(), f"缺少小节文件夹 {sec_dir}")
                expect((sec_dir / "00_小节记录.md").is_file(), f"{sec_dir} 缺少 00_小节记录.md")
                n_sec += 1

                _, _, blocks = extract_file(z, s["base"])
                flow = [b for b in blocks if b["kind"] not in ("h1", "h2", "imgbox")]
                files = sorted(sec_dir.glob("段落_*.md"))
                expect(len(files) == len(flow),
                       f"{sec_dir.name}: 段落文件 {len(files)} != 预期 {len(flow)}")
                for f, b in zip(files, flow):
                    n_par += 1
                    actual = f.read_text(encoding="utf-8")
                    from epublib import block_to_text
                    expect(actual.strip() != "", f"{f} 为空文件")
                    expect(actual == block_to_text(b), f"{f} 内容与源不一致")
                    expect(re.fullmatch(r"段落_\d{3}\.md", f.name), f"文件名不合规: {f.name}")

    print(f"章 {n_ch}｜小节 {n_sec}｜段落文件 {n_par}")
    if errors:
        print(f"\n发现 {len(errors)} 个问题：")
        for e in errors[:30]:
            print(" -", e)
        sys.exit(1)
    print("全部校验通过：内容与 EPUB 源逐段一致，记录文件齐全，命名合规。")


if __name__ == "__main__":
    main()
