#!/usr/bin/env python3
"""
一页纸 PDF 日报（A4，适合打印和转发）。

先生成一页排好版的 HTML，再用浏览器内核转成 PDF——字体、排版和网站保持一致，不需要额外的 PDF 库。
渲染器按顺序尝试：
  1. Playwright（如果装了：pip install playwright && playwright install chromium）
  2. 系统自带的 Microsoft Edge / Google Chrome（Windows 上通常已经有，无需安装任何东西）
都不可用时，会保留 daily-print.html，你可以用浏览器打开后"打印 → 另存为 PDF"。

用法：
  python make_pdf.py
  python make_pdf.py --asof "2026-10-18 08:00"
"""
from __future__ import annotations

import argparse
import base64
import html
import io
import re
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

import edition
import ranking
import risk
from build_web import load_site_config, seal
from edition import CONT_ORDER, head_title
from geo_data import CONTINENT_ZH

esc = html.escape

CSS = """
@page{size:A4;margin:11mm 13mm}
:root{--paper:#fff;--ink:#0F2A3D;--muted:#566872;--accent:#1C6B73;--tint:#E8EFEF;--line:#C9D5D6;
--serif:"Noto Serif SC","Source Han Serif SC","Songti SC","STSong","SimSun",serif;--sans:"Noto Sans SC","Source Han Sans SC","PingFang SC","Microsoft YaHei",sans-serif}
*{box-sizing:border-box}
body{margin:0;color:var(--ink);font:9.3pt/1.56 var(--sans);-webkit-print-color-adjust:exact;print-color-adjust:exact}
.head{display:flex;align-items:center;gap:5mm;border-bottom:2px solid var(--ink);padding-bottom:3mm}
.seal{width:19mm;height:19mm;color:var(--accent);transform:rotate(-8deg);flex:none}
h1{font:700 27pt/1 var(--serif);letter-spacing:.16em;margin:0}
.sub{color:var(--muted);font-size:9pt;margin-top:1.5mm}
.lead{font:500 10.8pt/1.65 var(--serif);margin:3mm 0 2mm}
h2{font:700 11.5pt var(--serif);margin:3.5mm 0 1.6mm;color:var(--accent)}
ol{list-style:none;margin:0;padding:0;counter-reset:n}
li.it{position:relative;padding-left:9mm;margin-bottom:2.6mm;counter-increment:n;break-inside:avoid}
li.it:before{content:counter(n);position:absolute;left:0;top:-1mm;font:700 17pt/1 var(--serif);color:var(--accent)}
li.it h3{font:700 10.6pt/1.42 var(--serif);margin:0 0 .4mm}
li.it p{margin:.4mm 0}
.why b{color:var(--accent);margin-right:2mm;font-weight:600}
.lv{display:inline-block;font-size:7.8pt;font-weight:700;padding:0 2.2mm;border:1px solid currentColor;border-radius:9px;margin-left:2mm;vertical-align:1px}
.lv.yellow{color:#85600A}.lv.orange{color:#AE4A0B}.lv.red{color:#B3261E}.lv.blue{color:#3F6B8F}
.chip{display:inline-block;font-size:7.8pt;background:var(--tint);padding:0 2.2mm;border-radius:9px;margin-left:2mm;vertical-align:1px}
.cols{columns:2;column-gap:7mm}.cols .c{break-inside:avoid;margin-bottom:2mm}
.cols b{font-family:var(--serif);font-size:10pt}
.foot{margin-top:3mm;padding-top:2.5mm;border-top:1px solid var(--line);display:flex;justify-content:space-between;align-items:center;gap:6mm;color:var(--muted);font-size:8.2pt}
.foot img{width:19mm;height:19mm}.foot .u{color:var(--accent);font-size:9pt}
"""


def qr_data_uri(url: str) -> str:
    try:
        import qrcode
    except ImportError:
        return ""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    im = qr.make_image(fill_color="#0F2A3D", back_color="white")
    im = im.get_image() if hasattr(im, "get_image") else im
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def build_html(ed: dict, cfg: dict, zoom: float = 1.0) -> str:
    copy = ed["copy"]
    d = ed["local"]
    items = []
    for h in ed["heads"]:
        c = copy["items"][h["key"]]
        r = h["risk"]
        lvl = f'<span class="lv {risk.LEVEL_CLS[r["level"]]}">{risk.LEVEL_LABEL[r["level"]]}</span>' if r and r["level"] in ("红", "橙", "黄") else ""
        cn = '<span class="chip">涉华</span>' if r and r.get("china") else ""
        items.append(f'<li class="it"><h3>{esc(head_title(h))}{lvl}{cn}<span class="chip">{esc(CONTINENT_ZH.get(h["ev"]["continent"], ""))}</span></h3>'
                     + (f'<p>{esc(c["summary"])}</p>' if c.get("summary") and not edition.similar(c["summary"], head_title(h)) else "")
                     + (f'<p class="why"><b>为什么重要</b>{esc(c["why"])}</p>' if c.get("why") else "")
                     + (f'<p class="why"><b>接下来看</b>{esc(c["next"])}</p>' if c.get("next") else "") + "</li>")
    conts = "".join(f'<div class="c"><b>{CONTINENT_ZH[c]}</b><br>{esc(copy["continents"].get(c, ""))}</div>' for c in CONT_ORDER if ed["counts"].get(c))
    base = cfg.get("base_url") or ""
    qr = qr_data_uri(base) if base else ""
    foot_left = (f'<div>扫码或访问：<span class="u">{esc(base) or "（网站发布后显示）"}</span><br>'
                 f'本页由 AI 辅助生成，依据公开新闻的标题与摘要，可能存在错误，请以原始来源为准。</div>')
    return (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><title>{esc(cfg["title"])} {ed["date"]}</title><style>{CSS}html{{zoom:{zoom}}}</style></head><body>'
            f'<div class="head">{seal(d, ed["weekday"])}<div><h1>{esc(cfg["title"])}</h1>'
            f'<div class="sub">{d.year}年{d.month}月{d.day}日 {esc(ed["weekday"])}　{esc(cfg["tagline"])}</div></div></div>'
            f'<p class="lead">{esc(copy["lead"])}</p><h2>今日要闻</h2><ol>{"".join(items)}</ol>'
            + (f'<h2>各大洲</h2><div class="cols">{conts}</div>' if conts else "")
            + f'<div class="foot">{foot_left}{f"<img src=\"{qr}\" alt=\"二维码\">" if qr else ""}</div></body></html>')


def find_browser() -> str | None:
    for name in ("msedge", "chrome", "google-chrome", "chromium", "chromium-browser"):
        p = shutil.which(name)
        if p:
            return p
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"):
        if Path(p).exists():
            return p
    return None


def render(html_path: Path, pdf_path: Path) -> str:
    """返回使用的渲染器名称；失败返回空字符串"""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto(html_path.resolve().as_uri())
            pg.pdf(path=str(pdf_path), format="A4", print_background=True, prefer_css_page_size=True)
            b.close()
        return "playwright"
    except Exception:
        pass
    exe = find_browser()
    if exe:
        with tempfile.TemporaryDirectory() as prof:
            cmd = [exe, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--print-to-pdf-no-header",
                   f"--user-data-dir={prof}", f"--print-to-pdf={pdf_path.resolve()}", html_path.resolve().as_uri()]
            try:
                subprocess.run(cmd, capture_output=True, timeout=90)
            except Exception:
                return ""
        if pdf_path.exists() and pdf_path.stat().st_size > 1000:
            return Path(exe).stem
    return ""


def main():
    ap = argparse.ArgumentParser(description="一页纸 PDF 日报")
    ap.add_argument("--db", default="data/diary.db")
    ap.add_argument("--config", default="sources_v1.yaml")
    ap.add_argument("--site-config", default="site_config.yaml")
    ap.add_argument("--out", default="site")
    ap.add_argument("--hours", type=float, default=36)
    ap.add_argument("--min-rel", type=int, default=2)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--asof", default=None)
    args = ap.parse_args()

    cfg = load_site_config(args.site_config)
    conn = sqlite3.connect(args.db)
    ed = edition.collect(conn, args.config, args.hours, args.min_rel, args.top, ranking.parse_asof(args.asof))
    edition.apply_copy(ed, edition.load_digest(conn, ed["date"]))
    if not ed["heads"]:
        raise SystemExit("这一期没有要闻，不生成 PDF。")
    out = Path(args.out) / "d" / ed["date"]
    out.mkdir(parents=True, exist_ok=True)
    html_path, pdf_path = out / "daily-print.html", out / "daily.pdf"
    who, pages = "", 0
    for zoom in (1.0, .94, .88, .82, .76):  # 超出一页就自动缩小，直到刚好一页
        html_path.write_text(build_html(ed, cfg, zoom), encoding="utf-8")
        who = render(html_path, pdf_path)
        if not who:
            print(f"没有找到可用的渲染器。已生成 {html_path}，请用浏览器打开后选择“打印 → 另存为 PDF”。")
            return
        pages = len(re.findall(rb"/Type\s*/Page[^s]", pdf_path.read_bytes()))
        if pages == 1:
            break
    html_path.unlink(missing_ok=True)
    shutil.copyfile(pdf_path, Path(args.out) / "daily.pdf")
    print(f"已生成 PDF（{who}，{pages} 页）→ {pdf_path}" + ("" if pages == 1 else "\n提示：内容超出一页，可以减少 --top。"))
    if not cfg.get("base_url"):
        print("提示：site_config.yaml 里没有 base_url，PDF 里不会有二维码。")


if __name__ == "__main__":
    main()
