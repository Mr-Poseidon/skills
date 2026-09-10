# -*- coding: utf-8 -*-
"""打印 EPUB 的真实目录层级（解析 toc.ncx，EPUB3 回退 nav.xhtml）。只读。

用法：python parse_epub.py --epub <epub路径>
用途：生成前的结构预览，人工核对章/小节划分是否符合预期。
"""
import argparse
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from epublib import BookInfo, parse_toc


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="打印 EPUB 目录层级")
    ap.add_argument("--epub", required=True)
    args = ap.parse_args()

    epub = Path(args.epub).resolve()
    with zipfile.ZipFile(epub) as z:
        info = BookInfo(epub, z)
        print(f"书名：{info.title}｜作者：{info.author or '—'}｜目录源：{info.toc_display()}\n")
        tops, deep = parse_toc(z, info)
        n_child = sum(len(t["children"]) for t in tops)
        print(f"一级条目 {len(tops)} 个，二级条目 {n_child} 个\n")
        for t in tops:
            print(f"[章] {t['label']}  ->  {t['base']}")
            for c in t["children"]:
                print(f"    [节] {c['label']}  ->  {c['base']}")


if __name__ == "__main__":
    main()
