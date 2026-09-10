# -*- coding: utf-8 -*-
"""体检 EPUB 全部 XHTML 文档的标签与 class 组合（只读）。

用法：python scan_tags.py --epub <epub路径>
用途：生成前确认正文标记约定。build_tree.py 的抽取器假定：
- 层级标题为 h1/h2；内部小标题为 h3-h6 或 class 含 p5 的 <p>；
- 脚注为 class 含 fnote 的 <p>；图片容器为 class 含 middle-img 的 <p> 或 <div class="pic">。
若体检发现本书使用其他样式类承担这些角色，先调整 Extractor 的样式约定再生成。
"""
import argparse
import sys
import zipfile
from collections import Counter
from pathlib import Path
import re

sys.path.insert(0, str(Path(__file__).parent))
from epublib import BookInfo


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="统计 EPUB XHTML 标签/样式清单")
    ap.add_argument("--epub", required=True)
    args = ap.parse_args()

    epub = Path(args.epub).resolve()
    combos = Counter()
    with zipfile.ZipFile(epub) as z:
        info = BookInfo(epub, z)
        for doc in info.docs:
            try:
                html = z.read(doc).decode("utf-8", errors="replace")
            except KeyError:
                continue
            body = html[html.find("<body"):]
            for m in re.finditer(r"<(h\d|p|img|table|blockquote|ul|ol|li|div)([^>]*)>", body):
                tag, attrs = m.group(1), m.group(2)
                cls = re.search(r'class="([^"]*)"', attrs)
                combos[(tag, cls.group(1) if cls else "")] += 1

    print(f"文档数 {len(info.docs)}；标签/样式清单：")
    for (tag, cls), n in sorted(combos.items()):
        print(f"  {tag:12s} class={cls!r:34s} x{n}")


if __name__ == "__main__":
    main()
