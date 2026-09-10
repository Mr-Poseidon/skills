# -*- coding: utf-8 -*-
"""EPUB → Agent 书库 公共解析库（仅 Python 标准库）。

提供：容器/OPF 路径解析、目录解析（EPUB2 toc.ncx 与 EPUB3 nav.xhtml 双支持）、
XHTML 正文块抽取、命名清理、YAML frontmatter 工具。
"""
import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

NCX_NS = {"ncx": "http://www.daisy.org/z3986/2005/ncx/"}
OPF_NS = {"opf": "http://www.idpf.org/2007/opf", "dc": "http://purl.org/dc/elements/1.1/"}
XH_NS = {"xh": "http://www.w3.org/1999/xhtml"}
CONTAINER_ROOTFILE = ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
ILLEGAL = re.compile(r'[\\/:*?"<>|]')


def sanitize(name: str) -> str:
    name = ILLEGAL.sub("_", str(name).strip())
    name = re.sub(r"\s+", "_", name)
    return name.rstrip(". ") or "未命名"


def sec_folder_name(label: str) -> str:
    """去掉原书小节编号前缀（如 '4.' / '48.'）后作为文件夹名。"""
    return sanitize(re.sub(r"^\d+\.", "", label))


def excerpt(text: str, n: int) -> str:
    return text[:n] + ("…" if len(text) > n else "")


def q(s) -> str:
    """用 JSON 字符串字面量保证 YAML 安全。"""
    import json
    return json.dumps(str(s), ensure_ascii=False)


def fm(fields: dict) -> str:
    lines = ["---"]
    for k, v in fields.items():
        if isinstance(v, (int, float)):
            lines.append(f"{k}: {v}")
        elif isinstance(v, list):
            lines.append(f"{k}: [{', '.join(q(x) for x in v)}]")
        else:
            lines.append(f"{k}: {q(v)}")
    lines.append("---")
    return "\n".join(lines)


FM_RE = re.compile(r"\A---\n.*?\n---\n+", re.S)


def strip_fm(text: str) -> str:
    return FM_RE.sub("", text, count=1) if text.startswith("---") else text


class BookInfo:
    """EPUB 内部路径与元数据。"""

    def __init__(self, epub: Path, zf: zipfile.ZipFile):
        self.epub = epub
        container = ET.fromstring(zf.read("META-INF/container.xml"))
        rf = container.find(CONTAINER_ROOTFILE)
        if rf is None:
            raise ValueError("container.xml 中未找到 rootfile")
        self.opf_path = _norm(rf.get("full-path"))
        self.opf_dir = posixpath.dirname(self.opf_path)
        root = ET.fromstring(zf.read(self.opf_path))

        def dc_text(tag):
            el = root.find(f".//dc:{tag}", OPF_NS)
            return " ".join("".join(el.itertext()).split()) if el is not None else ""

        self.title = dc_text("title") or epub.stem
        self.author = dc_text("creator")

        items = root.findall(".//opf:manifest/opf:item", OPF_NS)
        self.ncx = None
        self.nav = None
        self.docs = []
        for it in items:
            mtype = it.get("media-type", "")
            href = _join(self.opf_dir, it.get("href", ""))
            props = it.get("properties", "") or ""
            if mtype == "application/x-dtbncx+xml" and self.ncx is None:
                self.ncx = href
            elif "nav" in props.split() and mtype.endswith("xml") and self.nav is None:
                self.nav = href
            if mtype in ("application/xhtml+xml", "text/html"):
                self.docs.append(href)
        self.toc_dir = posixpath.dirname(self.ncx or self.nav or self.opf_path)

    def toc_display(self):
        return self.ncx or self.nav or ""


def _norm(p: str) -> str:
    return posixpath.normpath(unquote(p))


def _join(base_dir: str, href: str) -> str:
    href = unquote(href.split("#")[0])
    if base_dir:
        return posixpath.normpath(posixpath.join(base_dir, href))
    return posixpath.normpath(href)


# ---------------- 目录解析（ncx 优先，nav 兜底） ----------------

def parse_toc(zf: zipfile.ZipFile, info: BookInfo):
    """返回 (tops, deep)。deep 为超过 2 级被并入所属章的条目数。"""
    if info.ncx:
        return _parse_ncx(zf, info)
    if info.nav:
        return _parse_nav(zf, info)
    raise ValueError("EPUB 中未找到 toc.ncx 或 nav.xhtml，无法确定目录层级")


def _parse_ncx(zf: zipfile.ZipFile, info: BookInfo):
    root = ET.fromstring(zf.read(info.ncx))
    nav = root.find("ncx:navMap", NCX_NS)
    tops, cur, deep = [], None, 0

    def walk(el, depth):
        nonlocal cur, deep
        for np in el.findall("ncx:navPoint", NCX_NS):
            label = " ".join("".join(np.find("ncx:navLabel/ncx:text", NCX_NS).itertext()).split())
            src = np.find("ncx:content", NCX_NS).get("src")
            node = {"label": label, "src": src, "base": _join(info.toc_dir, src)}
            if depth == 0:
                node["children"] = []
                tops.append(node)
                cur = node
            else:
                if depth > 1:
                    deep += 1
                cur["children"].append(node)
            walk(np, depth + 1)

    walk(nav, 0)
    return tops, deep


def _parse_nav(zf: zipfile.ZipFile, info: BookInfo):
    root = ET.fromstring(zf.read(info.nav))
    navs = root.findall(".//xh:nav", XH_NS)
    toc_nav = next((n for n in navs
                    if "toc" in (n.get("{http://www.idpf.org/2007/ops}type") or "").split()), None)
    toc_nav = toc_nav or navs[0]
    tops, cur, deep = [], None, 0

    def walk_ol(ol, depth):
        nonlocal cur, deep
        for li in ol.findall("xh:li", XH_NS):
            a = li.find("xh:a", XH_NS)
            if a is None:
                sub = li.find("xh:ol", XH_NS)
                if sub is not None:
                    walk_ol(sub, depth)
                continue
            label = " ".join("".join(a.itertext()).split())
            src = a.get("href") or ""
            node = {"label": label, "src": src, "base": _join(info.toc_dir, src)}
            if depth == 0:
                node["children"] = []
                tops.append(node)
                cur = node
            else:
                if depth > 1:
                    deep += 1
                cur["children"].append(node)
            sub = li.find("xh:ol", XH_NS)
            if sub is not None:
                walk_ol(sub, depth + 1)

    walk_ol(toc_nav, 0)
    return tops, deep


# ---------------- XHTML 正文块抽取 ----------------

class Extractor(HTMLParser):
    """按文档顺序产出内容块：h1/h2（层级标题）、sub（内部小标题）、p（正文）、fnote（脚注）、img（插图）。

    样式约定（可在 scan_tags.py 体检后按书调整）：
    - class 含 p5 的 <p> 视为小标题；class 含 fnote 视为脚注；
      class 含 middle-img 视为纯图片容器；<div class="pic"> 由其中的 <img> 产出块。
    - <img> 带 ≥15 字的 title/alt 文本视为脚注（部分书以图片承载脚注、全文在 title 属性里）。
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.in_body = False
        self.blocks = []
        self._cap = None
        self._cls = ""
        self._buf = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "body":
            self.in_body = True
            return
        if not self.in_body:
            return
        if tag in ("style", "script", "title"):
            self._skip += 1
            return
        if self._skip:
            return
        if tag == "br":
            if self._cap:
                self._buf.append(" ")
            return
        if tag == "img":
            note = " ".join((a.get("title") or a.get("alt") or "").split())
            if len(note) >= 15:
                self.blocks.append({"kind": "fnote", "text": note, "img": a.get("src", "").split("/")[-1]})
            else:
                self.blocks.append({"kind": "img", "text": "", "img": a.get("src", "").split("/")[-1]})
            return
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6", "p"):
            self._flush()
            self._cap = tag
            self._cls = a.get("class", "")
            self._buf = []
        # div/a/sup/span/small/em/strong 等不产生新块；div.pic 由其中的 img 产出块

    def handle_endtag(self, tag):
        if tag == "body":
            self.in_body = False
            self._flush()
            return
        if self._cap == tag:
            self._flush()

    def handle_data(self, data):
        if self.in_body and self._cap and not self._skip:
            self._buf.append(data)

    def _flush(self):
        if not self._cap:
            return
        text = " ".join("".join(self._buf).split())
        kind = self._cap
        if self._cap == "p":
            cls = self._cls.split()
            if "p5" in cls:
                kind = "sub"
            elif "fnote" in cls:
                kind = "fnote"
            elif "middle-img" in cls:
                kind = "imgbox"
        elif self._cap in ("h3", "h4", "h5", "h6"):
            kind = "sub"
        if text:
            self.blocks.append({"kind": kind, "text": text, "img": ""})
        self._cap = None
        self._cls = ""
        self._buf = []


def extract_file(zf: zipfile.ZipFile, path: str):
    p = Extractor()
    p.feed(zf.read(path).decode("utf-8", errors="replace"))
    p.close()
    h1 = next((b["text"] for b in p.blocks if b["kind"] == "h1"), "")
    h2 = next((b["text"] for b in p.blocks if b["kind"] == "h2"), "")
    return h1, h2, p.blocks


def block_to_text(b: dict) -> str:
    """内容块 → 段落文件文本。"""
    if b["kind"] == "sub":
        return f"[标题] {b['text']}"
    if b["kind"] == "img":
        return f"[图: {b['img']}]"
    return b["text"]


def chapter_plan(ch: dict):
    """把一个一级目录条目规划为小节列表：[{label, base, note}]。

    规则：有子条目时，若章文件与第一个小节文件相同则题记并入首小节，
    否则补一个"章首"小节；无子条目的章补一个"全文"小节。
    """
    plan = []
    if ch["children"]:
        if ch["base"] != ch["children"][0]["base"]:
            plan.append({"label": "章首", "base": ch["base"],
                         "note": "章级文件（含章标题与题记、脚注）"})
        for c in ch["children"]:
            plan.append({"label": c["label"], "base": c["base"], "note": ""})
    else:
        plan.append({"label": "全文", "base": ch["base"], "note": "整章内容"})
    return plan


def book_slug(title: str) -> str:
    """书名 → ASCII slug（用于 SKILL.md 的 name 字段），纯数字/过短时回退。"""
    slug = re.sub(r"-{2,}", "-", re.sub(r"[^a-z0-9]+", "-", title.lower())).strip("-")
    if len(slug) < 3 or slug.isdigit():
        return "book-library"
    return slug[:64]


def book_description(title: str, author: str) -> str:
    """书库 SKILL.md 的基础 description（build_tree 初版与 make_skill 升级共用）。"""
    author_part = f"（{author}）" if author else ""
    return (f"《{title}》{author_part}的 AI 阅读版全书：一本给 AI 阅读的书，"
            f"按书→章→小节→段落渐进披露，含章节要点摘要与关键词索引。"
            f"当需要查阅本书任何内容时使用本库；先读协议按需下钻，"
            f"按摘录取舍段落，禁止通读全书。")


def wan_chars(chars: int) -> str:
    """字数 → 适读的万字表示。"""
    return f"{chars / 10000:.1f} 万" if chars >= 10000 else f"{chars} "
