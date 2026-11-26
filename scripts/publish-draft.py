#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
publish-draft.py — 把 doing/ 里的离线草稿发布成博客文章（不依赖 PicGo / 图床）

做四件事：
  1. 扫描 markdown 里的图片引用，把本地图片复制进 static/img/<slug>/
  2. 按 md5 复用仓库里已有的同内容图片，不重复上传
  3. 可选把 PNG 压成 WebP（实测省 90%+），让国内外加载都快
  4. 补规范 frontmatter，写到 content/posts/<分类>/<date>-<slug>.md

写作侧保持纯离线：草稿的图片用相对路径放在文档旁边（Typora 直接预览），
发布产物统一改成站点同源 `/img/...`，由 Cloudflare 提供，内外网都能访问。

用法：
  python3 scripts/publish-draft.py "doing/武大之旅.md" \
      --category 杂项 --date 2026-11-25 --dry-run

  # 确认无误后去掉 --dry-run，再按 AGENTS.md 走 hugo + git push
  python3 scripts/publish-draft.py "doing/武大之旅.md" --category 杂项 --date 2026-11-25

常用选项：
  --category    8 个中文分类之一（必填，除非 frontmatter 里已有）
  --date        YYYY-MM-DD，默认今天，决定 permalink
  --title       默认取文件名
  --description 20-60 字摘要，缺省时从正文首段自动截
  --slug        默认取文件名（自动去掉开头的日期前缀）
  --no-compress 不压 WebP，保留原图
  --dry-run     只打印将要做什么，不写任何文件
  --force       目标文章已存在时允许覆盖

注意：脚本只生成/覆盖文章文件与复制图片，不执行 hugo、git commit 或 push。
"""
import argparse
import datetime
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


def yaml_str(s: str) -> str:
    """双引号 YAML 标量转义，防止正文里的引号/反斜杠破坏 frontmatter。"""
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'

REPO = Path(__file__).resolve().parent.parent
IMAGES = REPO / "static" / "img"
POSTS = REPO / "content" / "posts"
CATEGORIES = [
    "PostgreSQL案例", "PostgreSQL内功修炼", "PostgreSQL源码解析",
    "PostgreSQL面试题", "论文解读", "读书笔记", "AIOps", "杂项",
]
IMG_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)


def md5(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_md5_index() -> dict:
    """仓库里已有图片 -> 相对 static/ 的 URL 路径，用于去重复用。"""
    idx = {}
    for p in IMAGES.rglob("*"):
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
            idx.setdefault(md5(p), "/img/" + p.relative_to(IMAGES).as_posix())
    return idx


def is_external(raw: str) -> bool:
    """已经可在线访问 / 站点同源的引用，原样保留。"""
    return raw.startswith(("http://", "https://", "/img/", "data:"))


def resolve_image(raw: str, draft: Path) -> Path | None:
    """把 markdown 里的图片路径解析成本地文件；找不到返回 None。"""
    if is_external(raw):
        return None
    p = Path(raw)
    if not p.is_absolute():
        p = (draft.parent / p).resolve()
    return p if p.is_file() else None


def compress_to_webp(src: Path, dst: Path) -> bool:
    exe = shutil.which("cwebp")
    if not exe:
        return False
    r = subprocess.run([exe, "-quiet", "-q", "82", str(src), "-o", str(dst)],
                       capture_output=True)
    return r.returncode == 0 and dst.is_file() and dst.stat().st_size > 0


def first_paragraph(body: str, limit: int = 56) -> str:
    """从正文首段截一句做 description，去掉链接/图片/标题符号。"""
    for line in body.splitlines():
        s = line.strip()
        if not s or s.startswith(("#", "![", "|", "-", ">")):
            continue
        s = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", s)   # 链接留文字
        s = re.sub(r"[*`>]", "", s).strip()
        if len(s) >= 12:
            return s[:limit].rstrip("，。、； ") + "…" if len(s) > limit else s
    return "（请在 frontmatter 补 description）"


def main() -> int:
    ap = argparse.ArgumentParser(description="离线草稿 -> lastdba.com 文章")
    ap.add_argument("draft", type=Path, help="草稿 md 路径（可在仓库外，如 doing/）")
    ap.add_argument("--category", choices=CATEGORIES)
    ap.add_argument("--date", default=datetime.date.today().isoformat())
    ap.add_argument("--title")
    ap.add_argument("--description")
    ap.add_argument("--slug")
    ap.add_argument("--no-compress", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    draft = a.draft.expanduser().resolve()
    if not draft.is_file():
        sys.exit(f"草稿不存在: {draft}")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", a.date):
        sys.exit(f"--date 需为 YYYY-MM-DD: {a.date}")

    text = draft.read_text(encoding="utf-8")
    m = FM_RE.match(text)
    old_fm = m.group(1) if m else ""
    body = text[m.end():] if m else text

    # 从旧 frontmatter 里取可用字段（typora-copy-images-to 之类的一律丢弃）
    def fm_get(key, default=None):
        mm = re.search(rf"^{key}:\s*(.+)$", old_fm, re.M)
        return mm.group(1).strip().strip('"').strip("'") if mm else default

    cat = a.category or fm_get("categories", "").strip("[]").strip('"')
    cat = cat or "杂项"
    if cat not in CATEGORIES:
        sys.exit(f"分类不合法: {cat}，必须是 {CATEGORIES}")
    title = a.title or fm_get("title") or re.sub(r"^\d{4}-\d{2}-\d{2}-", "", draft.stem)
    slug = a.slug or re.sub(r"^\d{4}-\d{2}-\d{2}-", "", draft.stem)
    desc = a.description or fm_get("description") or first_paragraph(body)

    out = POSTS / cat / f"{a.date}-{slug}.md"
    if out.exists() and not (a.dry_run or a.force):
        sys.exit(f"目标已存在: {out}\n如要覆盖请加 --force")

    index = build_md5_index()
    dest_dir = IMAGES                      # 与现有 764 张图一致：平铺在 static/img/，纯 ASCII 路径
    replacements, copied, reused, missing, plan = {}, 0, 0, [], []

    for raw in dict.fromkeys(IMG_RE.findall(body)):
        if is_external(raw):
            continue  # /img/、http、data: 原样保留
        src = resolve_image(raw, draft)
        if src is None:
            missing.append(raw)
            plan.append(f"  !! 图片文件缺失（不会发布成功）: {raw}")
            continue
        digest = md5(src)
        if digest in index:                       # 仓库已有同内容图，复用
            new_url = index[digest]
            reused += 1
            plan.append(f"  复用  {src.name} -> {new_url}")
        else:
            suffix = ".webp" if not a.no_compress else src.suffix.lower()
            target = dest_dir / (src.stem + suffix)
            # 同名但内容不同 → 加 md5 短前缀，绝不覆盖已有图片
            if target.exists() and md5(target) != digest:
                target = dest_dir / (src.stem + "-" + digest[:8] + suffix)
            new_url = "/img/" + target.relative_to(IMAGES).as_posix()
            if not target.exists():
                if not a.dry_run:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    if suffix == ".webp" and compress_to_webp(src, target):
                        pass
                    else:
                        shutil.copy2(src, target.with_suffix(src.suffix.lower()))
                        suffix = src.suffix.lower()
                        target = dest_dir / (src.stem + suffix)
                        new_url = "/img/" + target.relative_to(IMAGES).as_posix()
                copied += 1
                saved = ""
                if suffix == ".webp" and not a.dry_run:
                    saved = f"  ({src.stat().st_size/1048576:.1f}MB -> {target.stat().st_size/1048576:.1f}MB)"
                plan.append(f"  新增  {src.name} -> {new_url}{saved}")
            else:
                new_url = "/img/" + target.relative_to(IMAGES).as_posix()
                plan.append(f"  已存在 {new_url}")
            index[digest] = new_url
        replacements[raw] = new_url

    # 正文只改图片 URL，其余一字不动
    for raw, new_url in replacements.items():
        body = body.replace(f"({raw})", f"({new_url})")

    # 显式 slug 锁定 URL：不加的话 Hugo 会用 title 当 :slug，中文标题会变一长串 %XX
    fm = "\n".join([
        "---", f"title: {yaml_str(title)}", f"slug: {yaml_str(slug)}",
        f"date: {a.date}", "draft: false", f"categories: [{cat}]",
        f"description: {yaml_str(desc)}", "showHero: false", "---", "",
    ])
    content = fm + body.lstrip("\n")

    print(f"草稿   : {draft}")
    print(f"目标   : {out.relative_to(REPO)}")
    print(f"URL    : https://lastdba.com/{a.date.replace('-', '/')}/{quote(slug)}/")
    print(f"图片   : 复用 {reused} / 新增 {copied} / 压缩 {'关' if a.no_compress else '开(WebP q82)'}")
    for line in plan:
        print(line)
    if missing:
        print(f"  !! 仍指向本地且文件缺失: {missing}")
    print(f"正文   : {len(body)} 字符，仅替换图片 URL")
    if a.dry_run:
        print("\n[dry-run] 未写任何文件。去掉 --dry-run 才会生成文章和图片。")
        return 0
    if missing:
        sys.exit(f"\n有 {len(missing)} 张图片找不到本地文件，已中止（避免发布出 404）。")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    print(f"\n已生成: {out}")
    print("下一步: hugo --quiet && git add -A && git commit -m \"post: {}\" && git push".format(title))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
