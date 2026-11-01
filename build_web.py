#!/usr/bin/env python3
"""
生成面向订阅者的多页面网站（静态文件，可直接部署到任何静态托管，也可以双击本地打开）。

输出到 site/ ：
  index.html                 最新一期首页
  asia.html … global.html    各大洲页
  story-xxxx.html            单条要闻的深度页
  d/2026-10-18/              这一期的永久存档（页面同上，加 edition.json）
  archive.html  subscribe.html  about.html  feed.xml  assets/style.css

所有站内链接都是相对路径，放在任意子目录（如 GitHub Pages 的 /仓库名/）下都能正常工作。
给开发者看的"工作台"仍由 build_site.py 生成（输出到 devsite/，不对外发布）。

用法：
  python build_web.py
  python build_web.py --asof "2026-10-18 08:00"
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import html
import json
import re
import sqlite3
from pathlib import Path
from xml.sax.saxutils import escape as xesc

import yaml

import edition
import ranking
import risk
from edition import BASIS_LABEL, CONT_ORDER, SCENARIO_LABEL, head_title
from geo_data import CONTINENT_ZH

esc = html.escape

CSS = r"""
:root{--paper:#F3F5F4;--ink:#0F2A3D;--muted:#566872;--accent:#1C6B73;--tint:#E1EAEA;--line:#C9D5D6;
--lv-note:#3F6B8F;--lv-watch:#85600A;--lv-alert:#AE4A0B;--lv-high:#B3261E;
--serif:"Noto Serif SC","Source Han Serif SC","Songti SC","STSong","SimSun",serif;
--sans:"Noto Sans SC","Source Han Sans SC","PingFang SC","Microsoft YaHei",sans-serif}
@media (prefers-color-scheme:dark){:root{--paper:#0D1B26;--ink:#E7EEF0;--muted:#9DB0B8;--accent:#6FC3CB;--tint:#16303E;--line:#26414F;
--lv-note:#8DB6D8;--lv-watch:#E0B14A;--lv-alert:#F08A4B;--lv-high:#FF8A80}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.85 var(--sans)}
a{color:var(--accent);text-underline-offset:.18em}
:focus-visible{outline:3px solid var(--accent);outline-offset:3px;border-radius:2px}
.skip{position:absolute;left:-999px;top:0}.skip:focus{left:1rem;top:1rem;z-index:20;background:var(--ink);color:var(--paper);padding:.5rem 1rem}
.wrap{max-width:44rem;margin:0 auto;padding:0 1.25rem}
.bar{display:flex;justify-content:space-between;align-items:center;gap:1rem;padding:1rem 0;flex-wrap:wrap}
.brand{font:700 1.15rem var(--serif);letter-spacing:.12em;color:var(--ink);text-decoration:none}
.bar nav{display:flex;gap:1.4rem;font-size:.95rem}
.bar nav a{color:var(--ink);text-decoration:none;padding:.2rem 0;border-bottom:2px solid transparent}
.bar nav a:hover,.bar nav a[aria-current]{border-bottom-color:var(--accent)}
.archived{background:var(--tint);padding:.4rem 1rem;border-radius:6px;font-size:.88rem;margin-bottom:.5rem}
.notice{background:var(--tint);border-left:4px solid var(--lv-watch);padding:.6rem 1rem;font-size:.92rem;margin:1rem 0}
.mast{display:grid;grid-template-columns:auto 1fr;gap:1rem 1.6rem;align-items:center;padding:1.4rem 0 .6rem}
.mast h1{font:700 3.1rem/1.1 var(--serif);letter-spacing:.16em;margin:0}
.mast .sub{margin:.4rem 0 0;color:var(--muted)}
.mast .when{display:flex;flex-wrap:wrap;gap:.2rem 1.2rem;margin:.5rem 0 0;font-size:.9rem;color:var(--muted)}
.seal{width:6.4rem;height:6.4rem;color:var(--accent);transform:rotate(-8deg);flex:none}
.lead{font:500 1.28rem/1.8 var(--serif);margin:1.4rem 0 .6rem}
h2.sec{font:700 1.5rem/1.3 var(--serif);margin:3rem 0 1.1rem}
h2.sec small{font:400 .85rem var(--sans);color:var(--muted);margin-left:.8rem}
.brief{list-style:none;padding:0;margin:0;counter-reset:n}
.brief>li{position:relative;padding:0 0 2rem 3.2rem;counter-increment:n}
.brief>li:before{content:counter(n);position:absolute;left:0;top:-.15rem;font:700 2.3rem/1 var(--serif);color:var(--accent)}
.brief h3{font:700 1.3rem/1.5 var(--serif);margin:0 0 .3rem}
.brief h3 a,.plain h3 a{color:var(--ink);text-decoration:none}
.brief h3 a:hover,.plain h3 a:hover{text-decoration:underline}
.brief p{margin:.25rem 0}
.why{font-size:.97rem}.why b{font-weight:600;color:var(--accent);margin-right:.6rem}
.meta{display:flex;flex-wrap:wrap;gap:.35rem .6rem;align-items:center;margin-top:.7rem;font-size:.85rem;color:var(--muted)}
.chip{background:var(--tint);color:var(--ink);padding:.05rem .65rem;border-radius:99px;font-size:.8rem}
.lv{display:inline-flex;align-items:center;gap:.35rem;font-size:.8rem;font-weight:600;padding:.05rem .65rem;border:1.5px solid currentColor;border-radius:99px;white-space:nowrap}
.lv:before{content:"";width:.5rem;height:.5rem;border-radius:50%;background:currentColor}
.lv.blue{color:var(--lv-note)}.lv.yellow{color:var(--lv-watch)}.lv.orange{color:var(--lv-alert)}.lv.red{color:var(--lv-high)}
.radar{list-style:none;padding:0;margin:0}
.radar li{display:grid;grid-template-columns:7.2rem 1fr;gap:.2rem 1.2rem;padding:.9rem 0;border-top:1px solid var(--line)}
.radar li:first-child{border-top:0}
.radar li>div:first-child{grid-row:1/span 2;display:flex;flex-direction:column;gap:.4rem;align-items:flex-start}
.radar .t{font-weight:600}.radar .t a{color:var(--ink);text-decoration:none}.radar .t a:hover{text-decoration:underline}.radar .w{grid-column:2;font-size:.92rem;color:var(--muted)}
.cont{display:grid;grid-template-columns:8rem 1fr;gap:.3rem 1.6rem;padding:1.3rem 0;border-top:1px solid var(--line)}
.cont h3{font:700 1.7rem/1.2 var(--serif);margin:0}
.cont h3 a{color:var(--ink);text-decoration:none}.cont h3 a:hover{color:var(--accent)}
.cont .count{font-size:.82rem;color:var(--muted);margin-top:.3rem}
.cont p{margin:0}
.sub-box{background:var(--tint);border-radius:10px;padding:1.5rem 1.6rem;margin:3rem 0 1rem}
.sub-box h2{font:700 1.3rem var(--serif);margin:0 0 .4rem}
.sub-box p{margin:.2rem 0 1rem;color:var(--muted);font-size:.95rem}
.btns{display:flex;flex-wrap:wrap;gap:.7rem}
.btn{display:inline-block;padding:.55rem 1.1rem;border:1.5px solid var(--accent);border-radius:6px;color:var(--accent);text-decoration:none;font-weight:600;font-size:.95rem;background:transparent;cursor:pointer;font-family:inherit}
.btn:hover{background:var(--accent);color:var(--paper)}
.btn.fill{background:var(--accent);color:var(--paper)}.btn.fill:hover{filter:brightness(1.1)}
.foot{margin:3.5rem 0 2.5rem;padding-top:1.2rem;border-top:1px solid var(--line);color:var(--muted);font-size:.85rem}
.foot p{margin:.3rem 0}.foot .links{display:flex;flex-wrap:wrap;gap:.3rem 1.2rem}
.crumb{font-size:.88rem;color:var(--muted);margin-top:1rem}.crumb a{color:var(--muted)}
h1.story{font:700 2.05rem/1.45 var(--serif);margin:.8rem 0 .4rem}
.callouts{display:grid;grid-template-columns:1fr 1fr;gap:.9rem;margin:1.6rem 0}
.callout{background:var(--tint);border-radius:8px;padding:.9rem 1.2rem}
.callout h2{font:600 .85rem var(--sans);color:var(--accent);margin:0 0 .2rem;letter-spacing:.08em}
.callout p{margin:0}
.story h2.s{font:700 1.35rem/1.4 var(--serif);margin:2.6rem 0 .8rem}.story h2.s small{font:400 .85rem var(--sans);color:var(--muted);margin-left:.8rem}
.story ul.facts{padding-left:1.25rem}.story ul.facts li{margin:.7rem 0}
a.ref{font-size:.75rem;vertical-align:super;text-decoration:none;margin-left:2px}
.views{display:grid;gap:1rem}
.views>div{display:grid;grid-template-columns:8.6rem 1fr;gap:.1rem 1.2rem}
.views .who{font-weight:600}.views .who small{display:block;font-weight:400;color:var(--muted)}
.views .terms{color:var(--muted);font-size:.9rem}
.drv{list-style:none;padding:0;margin:0}.drv li{margin:.9rem 0}
.drv .dim{font-weight:600;margin-right:.6rem}
.tag{font-size:.74rem;border:1px solid var(--line);border-radius:4px;padding:0 .45rem;color:var(--muted);margin-left:.4rem;white-space:nowrap}
.tag.ai{border-color:var(--accent);color:var(--accent)}
.scn{margin:1.2rem 0}.scn .h{display:flex;justify-content:space-between;gap:1rem;font-weight:600}
.scn .h span:last-child{color:var(--muted);font-weight:400;font-size:.9rem}
.bar2{height:6px;background:var(--line);border-radius:3px;margin:.4rem 0 .5rem;overflow:hidden}.bar2 i{display:block;height:100%;background:var(--accent)}
.scn p{margin:.2rem 0}.scn .sig{font-size:.9rem;color:var(--muted)}
.fals{border-left:3px solid var(--lv-alert);padding:.2rem 1rem;margin:1.4rem 0}
.terms-list dt{font-weight:600;margin-top:.7rem}.terms-list dd{margin:0}
ol.src{padding-left:1.5rem;font-size:.93rem}ol.src li{margin:.45rem 0;overflow-wrap:anywhere}
details.method{margin:2.6rem 0 0;border-top:1px solid var(--line);padding-top:1rem;font-size:.92rem;color:var(--muted)}
details.method summary{cursor:pointer;color:var(--ink);font-weight:600}
.plain{list-style:none;padding:0;margin:0}.plain>li{padding:.2rem 0 1.5rem}
.plain h3{font:700 1.2rem/1.5 var(--serif);margin:0 0 .2rem}.plain p{margin:.2rem 0}
.srcs a{display:block;font-size:.88rem;overflow-wrap:anywhere}
.chips{display:flex;flex-wrap:wrap;gap:.5rem;margin:1.4rem 0}
.chips a{padding:.2rem .9rem;border-radius:99px;background:var(--tint);color:var(--ink);text-decoration:none;font-size:.92rem}
.chips a[aria-current]{background:var(--accent);color:var(--paper)}
.opt{padding:1.3rem 0;border-top:1px solid var(--line)}.opt h2{font:700 1.3rem var(--serif);margin:0 0 .4rem}
.opt img{display:block;max-width:20rem;width:100%;border-radius:8px;border:1px solid var(--line);margin:.8rem 0 1rem}
code.url{display:block;background:var(--tint);padding:.5rem .8rem;border-radius:6px;overflow-wrap:anywhere;font-size:.9rem}
table.lv-table{border-collapse:collapse;width:100%;font-size:.93rem}table.lv-table td{padding:.5rem .6rem .5rem 0;vertical-align:top;border-top:1px solid var(--line)}
@media (max-width:560px){.callouts{grid-template-columns:1fr}body{font-size:16px}.mast{grid-template-columns:4.8rem 1fr}.seal{width:4.8rem;height:4.8rem}.mast h1{font-size:2.3rem}
.cont{grid-template-columns:1fr}.radar li{grid-template-columns:1fr}.radar li>div:first-child{grid-row:auto}.radar .w{grid-column:1}.views>div{grid-template-columns:1fr}h1.story{font-size:1.65rem}}
@media print{.bar,.sub-box,.skip,.chips{display:none}body{background:#fff;color:#000;font-size:11pt}a{color:inherit;text-decoration:none}.wrap{max-width:none}}
"""


def cn_date(d: dt.datetime) -> str:
    return f"{d.year}年{d.month}月{d.day}日"


def seal(d: dt.datetime, wd: str) -> str:
    return (f'<svg class="seal" viewBox="0 0 100 100" role="img" aria-label="{esc(cn_date(d))} {esc(wd)}">'
            '<circle cx="50" cy="50" r="46" fill="none" stroke="currentColor" stroke-width="3"/>'
            '<circle cx="50" cy="50" r="40" fill="none" stroke="currentColor" stroke-width="1"/>'
            f'<text x="50" y="33" text-anchor="middle" font-size="12" fill="currentColor" font-family="var(--serif)">{d.month}月</text>'
            f'<text x="50" y="65" text-anchor="middle" font-size="34" font-weight="700" fill="currentColor" font-family="var(--serif)">{d.day}</text>'
            f'<text x="50" y="81" text-anchor="middle" font-size="10" fill="currentColor" font-family="var(--serif)">{esc(wd)}</text></svg>')


def lv(r: dict | None) -> str:
    if not r or r["level"] not in ("红", "橙", "黄"):
        return ""
    return f'<span class="lv {risk.LEVEL_CLS[r["level"]]}">{risk.LEVEL_LABEL[r["level"]]}</span>'


def chip(t: str) -> str:
    return f'<span class="chip">{esc(t)}</span>' if t else ""


def files_in(d: Path) -> dict:
    return {"pdf": (d / "daily.pdf").exists(), "card_daily": (d / "card-daily.png").exists(),
            "cards": {i: (d / f"card-{i}.png").exists() for i in range(1, 8)}}


# ------------------------------------------------------------------ 页面骨架
def layout(cfg: dict, root: str, title: str, body: str, *, desc: str = "", image: str = "", path: str = "",
           active: str = "", archived: str = "") -> str:
    base = cfg.get("base_url") or ""
    full_title = f"{title} | {cfg['title']}" if title != cfg["title"] else cfg["title"]
    og = [f'<meta property="og:title" content="{esc(full_title)}">', '<meta property="og:type" content="article">',
          f'<meta property="og:site_name" content="{esc(cfg["title"])}">']
    if desc:
        og += [f'<meta name="description" content="{esc(desc)}">', f'<meta property="og:description" content="{esc(desc)}">']
    if base and path:
        og.append(f'<meta property="og:url" content="{esc(base + path)}">')
    if base and image:
        og.append(f'<meta property="og:image" content="{esc(base + image)}">')
    nav = "".join(f'<a href="{root}{href}"{" aria-current=\"page\"" if key == active else ""}>{label}</a>'
                  for key, href, label in (("home", "index.html", "首页"), ("archive", "archive.html", "往期"),
                                           ("subscribe", "subscribe.html", "订阅"), ("about", "about.html", "关于")))
    arch = f'<div class="archived">你正在看 {esc(archived)} 的往期日报，<a href="{root}index.html">回到最新一期</a></div>' if archived else ""
    return (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(full_title)}</title>{"".join(og)}<meta name="color-scheme" content="light dark">'
            f'<link rel="alternate" type="application/rss+xml" title="{esc(cfg["title"])}" href="{root}feed.xml">'
            f'<link rel="stylesheet" href="{root}assets/style.css"></head><body><a class="skip" href="#main">跳到正文</a>'
            f'<div class="wrap"><header class="bar"><a class="brand" href="{root}index.html">{esc(cfg["title"])}</a><nav aria-label="主导航">{nav}</nav></header>{arch}'
            f'<main id="main">{body}</main>'
            f'<footer class="foot"><p>本站内容由程序自动采集公开新闻的标题与摘要，并由 AI 辅助生成解读，可能存在错误，请以原始来源为准。预判是概率性判断，不是预言。</p>'
            f'<p class="links">{("<span>" + esc(cfg["publisher"]) + "</span>") if cfg.get("publisher") else ""}<a href="{root}about.html">关于本站</a><a href="{root}feed.xml">RSS</a>'
            f'{"<a href=\"mailto:" + esc(cfg["contact_email"]) + "\">反馈与纠错</a>" if cfg.get("contact_email") else ""}</p></footer></div></body></html>')


# ------------------------------------------------------------------ 首页
def item_meta(h: dict) -> str:
    ev = h["ev"]
    parts = [chip(CONTINENT_ZH.get(ev["continent"], "")), lv(h["risk"]), chip("涉华") if (h["risk"] or {}).get("china") else "",
             f'<span>{h["n_articles"]}篇报道</span>']
    return '<div class="meta">' + "".join(p for p in parts if p) + "</div>"


def render_index(ed: dict, cfg: dict, root: str, files: dict, archived: str = "") -> str:
    copy = ed["copy"]
    b = []
    when = [f"<span>{esc(cn_date(ed['local']))} {esc(ed['weekday'])}</span>"]
    if ed["latest_pub"]:
        lt = dt.datetime.fromisoformat(ed["latest_pub"]).astimezone()
        when.append(f"<span>数据截至 {lt:%m月%d日 %H:%M}</span>")
    b.append(f'<div class="mast">{seal(ed["local"], ed["weekday"])}<div><h1>{esc(cfg["title"])}</h1>'
             f'<p class="sub">{esc(cfg["tagline"])}</p><p class="when">{"".join(when)}</p></div></div>')
    if ed["age_h"] is not None and ed["age_h"] > 12 and not archived:
        b.append(f'<p class="notice">本期数据已有 {ed["age_h"]:.0f} 小时没有更新，最新消息可能尚未收录。</p>')
    b.append(f'<p class="lead">{esc(copy["lead"])}</p>')
    b.append('<h2 class="sec" id="brief">今日要闻</h2>')
    if ed["heads"]:
        b.append('<ol class="brief">')
        for h in ed["heads"]:
            c = copy["items"][h["key"]]
            b.append(f'<li><h3><a href="story-{h["slug"]}.html">{esc(head_title(h))}</a></h3>'
                     + (f'<p>{esc(c["summary"])}</p>' if c.get("summary") and not edition.similar(c["summary"], head_title(h)) else "")
                     + (f'<p class="why"><b>为什么重要</b>{esc(c["why"])}</p>' if c.get("why") else "")
                     + item_meta(h) + "</li>")
        b.append("</ol>")
    else:
        b.append('<p class="notice">今天暂无达到发布标准的重点事件。</p>')

    if ed["radar"]:
        b.append('<h2 class="sec" id="radar">需要多留意的<small>警惕级别以上，或涉及中国的事件</small></h2><ul class="radar">')
        for r in ed["radar"]:
            title = f'<a href="story-{r["slug"]}.html">{esc(r["title"])}</a>' if r["slug"] else esc(r["title"])
            watch = analyze_join(r["risk"].get("watch"))
            b.append(f'<li><div>{lv(r["risk"])}{"<br>" + chip("涉华") if r["china"] else ""}</div><div class="t">{title}</div>'
                     + (f'<div class="w">建议关注：{esc(watch)}</div>' if watch else "") + "</li>")
        b.append(f'</ul><p class="why"><a href="{root}about.html#levels">各级别是什么意思</a></p>')

    b.append('<h2 class="sec" id="continents">六大洲日记</h2>')
    shown = 0
    for c in CONT_ORDER:
        n = ed["counts"].get(c, 0)
        if not n:
            continue
        shown += 1
        b.append(f'<div class="cont"><div><h3><a href="{c}.html">{CONTINENT_ZH[c]}</a></h3><div class="count">今日 {n} 条</div></div>'
                 f'<p>{esc(copy["continents"].get(c, ""))}</p></div>')
    if not shown:
        b.append('<p class="why">今天各大洲暂无需要单独列出的动态。</p>')

    b.append('<section class="sub-box" aria-labelledby="subh"><h2 id="subh">每天收到这份日记</h2>'
             '<p>邮件、PDF、微信分享卡片、RSS，选你习惯的方式。</p><div class="btns">'
             f'<a class="btn fill" href="{root}subscribe.html">订阅</a>'
             + (f'<a class="btn" href="daily.pdf">下载今日 PDF</a>' if files.get("pdf") else "")
             + (f'<a class="btn" href="card-daily.png">微信分享卡片</a>' if files.get("card_daily") else "")
             + "</div></section>")
    first = ed["heads"][0] if ed["heads"] else None
    desc = copy["lead"][:100]
    return layout(cfg, root, cfg["title"], "".join(b), desc=desc, image=("card-daily.png" if files.get("card_daily") else ""),
                  path=("" if root == "" else f"d/{ed['date']}/") + "index.html", active="home", archived=archived)


def analyze_join(lst) -> str:
    import analyze
    return analyze.join_cn(lst or [])


# ------------------------------------------------------------------ 大洲页
def render_continent(ed: dict, cfg: dict, root: str, cont: str, files: dict, archived: str = "") -> str:
    grp = ed["by_cont"].get(cont) or {"heads": [], "others": []}
    b = [f'<p class="crumb"><a href="index.html">首页</a>　{esc(CONTINENT_ZH[cont])}</p><h1 class="story">{esc(CONTINENT_ZH[cont])}</h1>']
    note = ed["copy"]["continents"].get(cont)
    b.append(f'<p class="lead">{esc(note)}</p>' if note else '<p class="lead">今天这个大洲暂无需要单独列出的动态。</p>')
    if grp["heads"]:
        b.append('<h2 class="sec">今日要闻</h2><ul class="plain">')
        for h in grp["heads"]:
            c = ed["copy"]["items"][h["key"]]
            b.append(f'<li><h3><a href="story-{h["slug"]}.html">{esc(head_title(h))}</a></h3>'
                     + (f'<p>{esc(c["summary"])}</p>' if c.get("summary") else "") + item_meta(h) + "</li>")
        b.append("</ul>")
    if grp["others"]:
        b.append('<h2 class="sec">其他动态</h2><ul class="plain">')
        for o in grp["others"]:
            e = o["ev"]
            links = "".join(f'<a href="{esc(u)}" target="_blank" rel="noopener noreferrer">{esc(n)}：{esc(t)}</a>' for n, t, u in o["links"])
            b.append(f'<li><h3>{esc(e.get("title_zh") or e["title"])}</h3>'
                     + (f'<p>{esc(e["summary_zh"])}</p>' if e.get("summary_zh") else "")
                     + f'<div class="meta">{chip(e["category"])}{lv(o["risk"])}<span>{e["n_articles"]}篇报道</span></div>'
                     + (f'<div class="srcs">{links}</div>' if links else "") + "</li>")
        b.append("</ul>")
    chips = "".join(f'<a href="{c}.html"{" aria-current=\"page\"" if c == cont else ""}>{CONTINENT_ZH[c]}</a>'
                    for c in CONT_ORDER if ed["counts"].get(c) or c == cont)
    b.append(f'<h2 class="sec">看看其他大洲</h2><div class="chips">{chips}</div>')
    return layout(cfg, root, CONTINENT_ZH[cont], "".join(b), desc=(note or "")[:100],
                  path=("" if root == "" else f"d/{ed['date']}/") + f"{cont}.html", active="home", archived=archived)


# ------------------------------------------------------------------ 深度页
def refs(rs, evidence) -> str:
    out = []
    for r in rs or []:
        if isinstance(r, int) and 1 <= r <= len(evidence):
            e = evidence[r - 1]
            out.append(f'<a class="ref" href="#s{r}" title="{esc((e.get("source_name") or "") + "：" + (e.get("title") or ""))}">[{r}]</a>')
    return "".join(out)


def render_story(ed: dict, cfg: dict, root: str, h: dict, idx: int, files: dict, archived: str = "") -> str:
    an, ev, evidence = h["an"], h["ev"], h["evidence"]
    c = ed["copy"]["items"][h["key"]]
    title = head_title(h)
    cont = ev["continent"]
    b = [f'<p class="crumb"><a href="index.html">首页</a>　<a href="{cont}.html">{esc(CONTINENT_ZH.get(cont, ""))}</a></p>',
         '<article class="story">', f'<h1 class="story">{esc(title)}</h1>', item_meta(h)]
    if c.get("summary"):
        b.append(f'<p class="lead">{esc(c["summary"])}</p>')
    call = []
    if c.get("why"):
        call.append(f'<div class="callout"><h2>为什么重要</h2><p>{esc(c["why"])}</p></div>')
    if c.get("next"):
        call.append(f'<div class="callout"><h2>接下来看什么</h2><p>{esc(c["next"])}</p></div>')
    if call:
        b.append('<div class="callouts">' + "".join(call) + "</div>")

    b.append('<h2 class="s">发生了什么</h2><ul class="facts">' + "".join(
        f'<li>{esc(f.get("text", ""))}{refs(f.get("refs"), evidence)}</li>' for f in an.get("facts", [])) + "</ul>")
    for d in an.get("disagreements") or []:
        b.append(f'<p>各方说法有出入：{esc(d.get("text", ""))}{refs(d.get("refs"), evidence)}</p>')

    sc = an.get("source_comparison") or {}
    rows = [r for r in sc.get("rows") or [] if isinstance(r.get("ref"), int) and 1 <= r["ref"] <= len(evidence)]
    if len(evidence) >= 2 and rows:
        b.append('<h2 class="s">各方怎么说</h2>')
        if sc.get("summary"):
            b.append(f'<p>{esc(sc["summary"])}</p>')
        b.append('<div class="views">')
        for r in rows:
            e = evidence[r["ref"] - 1]
            kt = "；".join(r.get("key_terms") or [])
            b.append(f'<div><div class="who">{esc(e.get("source_name") or "")}<small>{esc(e.get("country") or "")}</small></div>'
                     f'<div>{esc(r.get("angle", ""))}{refs([r["ref"]], evidence)}' + (f'<div class="terms">原文措辞：{esc(kt)}</div>' if kt else "") + "</div></div>")
        b.append("</div>")

    if an.get("drivers"):
        b.append('<h2 class="s">为什么会这样</h2><ul class="drv">')
        for d in an["drivers"]:
            tag = BASIS_LABEL.get(d.get("basis"), "")
            b.append(f'<li><span class="dim">{esc(d.get("dimension", ""))}</span>'
                     f'<span class="tag{" ai" if d.get("basis") == "推断" else ""}" style="margin:0 .6rem 0 0">{esc(tag)}</span>'
                     f'{esc(d.get("claim", ""))}{refs(d.get("refs"), evidence)}</li>')
        b.append("</ul>")

    out = an.get("outlook") or {}
    if out.get("scenarios"):
        b.append(f'<h2 class="s">接下来可能怎么走<small>未来约 {esc(str(out.get("horizon_days", 14)))} 天</small></h2>')
        for s in out["scenarios"]:
            p = s.get("probability") or [0, 0]
            try:
                lo, hi = p
                mid, ptxt = max(0, min(100, (lo + hi) / 2)), f"可能性约 {lo}%–{hi}%"
            except Exception:
                mid, ptxt = 0, ""
            sig = analyze_join(s.get("indicators"))
            b.append(f'<div class="scn"><div class="h"><span>{esc(SCENARIO_LABEL.get(s.get("name"), s.get("name", "")))}</span><span>{ptxt}</span></div>'
                     f'<div class="bar2"><i style="width:{mid:.0f}%"></i></div><p>{esc(s.get("description", ""))}</p>'
                     + (f'<p class="sig">可以留意的信号：{esc(sig)}</p>' if sig else "") + "</div>")
        if out.get("falsifiers"):
            b.append(f'<p class="fals"><b>什么情况说明这个判断错了：</b>{esc(analyze_join(out["falsifiers"]))}</p>')
        b.append('<p class="why">预判是概率性判断，不是预言。</p>')

    terms = (an.get("plain") or {}).get("terms") or []
    if terms:
        b.append('<h2 class="s">几个词</h2><dl class="terms-list">' + "".join(
            f'<dt>{esc(t.get("term", ""))}</dt><dd>{esc(t.get("explain", ""))}</dd>' for t in terms) + "</dl>")
    if an.get("diplomatic_language"):
        b.append('<h2 class="s">措辞里的信号</h2><ul class="facts">' + "".join(
            f'<li>“{esc(d.get("phrase", ""))}”：{esc(d.get("note", ""))}（强度 {esc(str(d.get("level", "-")))}/5）</li>' for d in an["diplomatic_language"]) + "</ul>")

    b.append('<h2 class="s">来源</h2><ol class="src">' + "".join(
        f'<li id="s{i}">{esc(e.get("source_name") or "")}（{esc(e.get("country") or "")}）：'
        f'<a href="{esc(e.get("url") or "#")}" target="_blank" rel="noopener noreferrer">{esc(e.get("title") or "")}</a></li>'
        for i, e in enumerate(evidence, 1)) + "</ol>")

    st = an.get("_strength") or {}
    notes = an.get("_notes") or []
    reasons = (h["risk"] or {}).get("reasons") or []
    b.append('<details class="method"><summary>这篇是怎么生成的</summary>'
             f'<p>系统自动采集了 {len(evidence)} 条相关报道的标题和摘要（共 {h["n_articles"]} 篇报道），由 AI 梳理事实、对比各方说法并做出解读；'
             '随后经过程序校验（引用编号、数字、原话）和第二轮 AI 核查，无法核实的内容会被自动移除。</p>'
             + (f'<p>来源覆盖：{st.get("n_sources", "-")} 个信源、{st.get("n_countries", "-")} 个国家/地区'
                + ("，含官方或国际组织来源" if st.get("has_official") else "") + "。</p>" if st else "")
             + (f'<p>关注程度的依据：{esc("；".join(reasons))}</p>' if reasons else "")
             + (f'<p>自动处置记录：</p><ul>' + "".join(f"<li>{esc(n)}</li>" for n in notes) + "</ul>" if notes else "")
             + "</details>")
    share = ""
    if files["cards"].get(idx):
        share = f'<a class="btn" href="card-{idx}.png">保存分享卡片</a>'
    b.append(f'<div class="btns" style="margin-top:2rem"><a class="btn" href="index.html">回到首页</a>{share}</div></article>')
    return layout(cfg, root, title, "".join(b), desc=(c.get("summary") or c.get("why") or "")[:110],
                  image=(f"card-{idx}.png" if files["cards"].get(idx) else ""),
                  path=("" if root == "" else f"d/{ed['date']}/") + f"story-{h['slug']}.html", active="home", archived=archived)


# ------------------------------------------------------------------ 站点级页面
def render_archive(editions: list[dict], cfg: dict) -> str:
    b = ['<h1 class="story">往期日报</h1>']
    if not editions:
        b.append("<p>还没有往期。</p>")
    b.append('<ul class="plain">')
    for e in editions:
        b.append(f'<li><h3><a href="d/{esc(e["date"])}/index.html">{esc(e["date"])} {esc(e.get("weekday", ""))}</a></h3>'
                 f'<p>{esc(e.get("lead", ""))}</p><div class="meta"><span>{len(e.get("items", []))} 条要闻</span></div></li>')
    b.append("</ul>")
    return layout(cfg, "", "往期日报", "".join(b), desc="大洲日记往期合集", path="archive.html", active="archive")


def render_subscribe(cfg: dict, files: dict) -> str:
    b = ['<h1 class="story">订阅</h1><p class="lead">选一种你习惯的方式，每天读到这份日记。</p>']
    if cfg.get("subscribe_form_url"):
        mail = f'<a class="btn fill" href="{esc(cfg["subscribe_form_url"])}" target="_blank" rel="noopener noreferrer">填写订阅表单</a>'
    elif cfg.get("contact_email"):
        mail = (f'<a class="btn fill" href="mailto:{esc(cfg["contact_email"])}?subject={esc("订阅大洲日记")}'
                f'&body={esc("请把我的邮箱加入大洲日记的每日邮件订阅。")}">发邮件订阅</a>')
    else:
        mail = '<p class="why">站点管理员还没有配置订阅入口（site_config.yaml 里的 contact_email 或 subscribe_form_url）。</p>'
    b.append('<section class="opt" id="email"><h2>邮件</h2><p>每个工作日早上一封，只含当天要闻、风险提示和各大洲小结，打开就能读完。'
             '随时可以退订：回复“退订”即可。你的邮箱只用来发送日报，不会用于其他用途。</p>' + mail + "</section>")
    card = ('<img src="card-daily.png" alt="今日分享卡片" loading="lazy">' if files.get("card_daily") else "")
    b.append('<section class="opt" id="wechat"><h2>微信分享卡片</h2><p>每天一张竖版图片，长按保存后发到微信群或朋友圈；图上的二维码可以直接打开网站。</p>'
             + (f'{card}<a class="btn" href="card-daily.png">打开今日卡片</a>' if card else '<p class="why">今天的卡片还没有生成。</p>') + "</section>")
    b.append('<section class="opt" id="pdf"><h2>PDF 日报</h2><p>一页纸版本，适合打印和转发。</p>'
             + ('<a class="btn" href="daily.pdf">下载今日 PDF</a>' if files.get("pdf") else '<p class="why">今天的 PDF 还没有生成。</p>') + "</section>")
    feed = (cfg.get("base_url") or "") + "feed.xml"
    b.append('<section class="opt" id="rss"><h2>RSS</h2><p>用 Feedly、Inoreader、Reeder 等阅读器订阅这个地址：</p>'
             f'<code class="url" id="feedurl">{esc(feed if cfg.get("base_url") else "（网站正式发布、设置 base_url 之后，这里会显示完整地址）")}</code>'
             '<p><button class="btn" type="button" onclick="navigator.clipboard&&navigator.clipboard.writeText(document.getElementById(\'feedurl\').textContent)">复制地址</button></p></section>')
    return layout(cfg, "", "订阅", "".join(b), desc="通过邮件、PDF、微信分享卡片或 RSS 订阅大洲日记", path="subscribe.html", active="subscribe")


def render_about(cfg: dict) -> str:
    levels = "".join(f'<tr><td><span class="lv {risk.LEVEL_CLS[k]}">{risk.LEVEL_LABEL[k]}</span></td><td>{esc(risk.LEVEL_MEANING[k])}</td></tr>'
                     for k in ("蓝", "黄", "橙", "红"))
    b = [f'<h1 class="story">关于{esc(cfg["title"])}</h1>',
         f'<p class="lead">{esc(cfg["tagline"])}。这是一份由 AI 辅助生成的外交外事日报，按亚洲、欧洲、非洲、北美洲、南美洲、大洋洲分栏，帮助你在几分钟内了解当天值得关注的国际动态。</p>',
         '<h2 class="s" style="font:700 1.35rem var(--serif);margin:2.4rem 0 .6rem">内容从哪里来</h2>'
         '<p>系统每天自动采集国际组织、各国政府和主要媒体公开发布的新闻，只使用其标题、摘要和链接，不转载全文；每个结论都标注了来源，可以点击溯源。</p>',
         '<h2 class="s" style="font:700 1.35rem var(--serif);margin:2.4rem 0 .6rem">怎么保证可靠</h2>'
         '<p>AI 先梳理事实、对比各方说法、给出成因和走向的判断；程序再核对引用编号、数字和原话，第二轮 AI 核查事实与倾向性；无法核实的内容会被自动移除，仍不达标的事件不会发布。'
         '即便如此，自动生成的内容仍可能出错，请以原始来源为准。</p>',
         '<h2 class="s" id="levels" style="font:700 1.35rem var(--serif);margin:2.4rem 0 .6rem">“关注程度”是什么</h2>'
         '<p>按涉华程度、议题类别、风险情景概率和报道广度综合评分，只表示值得关注的程度，不是对事态发展的预言。</p>'
         f'<table class="lv-table">{levels}</table>',
         '<h2 class="s" style="font:700 1.35rem var(--serif);margin:2.4rem 0 .6rem">发现错误？</h2>'
         + (f'<p>欢迎来信纠错：<a href="mailto:{esc(cfg["contact_email"])}">{esc(cfg["contact_email"])}</a></p>' if cfg.get("contact_email") else "<p>欢迎联系站点管理员纠错。</p>")]
    return layout(cfg, "", "关于", "".join(b), desc="大洲日记是什么、内容从哪里来、如何保证可靠", path="about.html", active="about")


def render_feed(editions: list[dict], cfg: dict) -> str:
    base = cfg.get("base_url") or "http://localhost/"
    items = []
    for e in editions[:12]:
        pub = dt.datetime.strptime(e["date"], "%Y-%m-%d").replace(hour=8, tzinfo=dt.timezone(dt.timedelta(hours=8)))
        for it in e.get("items", []):
            link = f'{base}d/{e["date"]}/story-{it["slug"]}.html'
            desc = "　".join(x for x in (it.get("summary"), ("为什么重要：" + it["why"]) if it.get("why") else "",
                                        ("接下来看：" + it["next"]) if it.get("next") else "") if x)
            items.append(f'<item><title>{xesc(it["title"])}</title><link>{xesc(link)}</link><guid isPermaLink="true">{xesc(link)}</guid>'
                         f'<pubDate>{email.utils.format_datetime(pub)}</pubDate><category>{xesc(it.get("continent_name", ""))}</category>'
                         f'<description>{xesc(desc)}</description></item>')
    return ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
            f'<title>{xesc(cfg["title"])}</title><link>{xesc(base)}</link><description>{xesc(cfg["tagline"])}</description><language>zh-CN</language>'
            + "".join(items) + "</channel></rss>")


# ------------------------------------------------------------------ 写出
def write_edition(out: Path, root: str, ed: dict, cfg: dict, archived: str = "") -> int:
    out.mkdir(parents=True, exist_ok=True)
    files = files_in(out)
    n = 0
    (out / "index.html").write_text(render_index(ed, cfg, root, files, archived), encoding="utf-8"); n += 1
    for c in CONT_ORDER:
        if ed["counts"].get(c):
            (out / f"{c}.html").write_text(render_continent(ed, cfg, root, c, files, archived), encoding="utf-8"); n += 1
    for i, h in enumerate(ed["heads"], 1):
        (out / f"story-{h['slug']}.html").write_text(render_story(ed, cfg, root, h, i, files, archived), encoding="utf-8"); n += 1
    return n


def edition_json(ed: dict) -> dict:
    return dict(date=ed["date"], weekday=ed["weekday"], lead=ed["copy"]["lead"], generated_at=dt.datetime.now().isoformat(timespec="seconds"),
                items=[dict(slug=h["slug"], title=head_title(h), continent=h["ev"]["continent"],
                            continent_name=CONTINENT_ZH.get(h["ev"]["continent"], ""), risk=(h["risk"] or {}).get("level"),
                            china=bool((h["risk"] or {}).get("china")), n_articles=h["n_articles"], **ed["copy"]["items"][h["key"]]) for h in ed["heads"]],
                continents=[dict(id=c, name=CONTINENT_ZH[c], count=ed["counts"].get(c, 0), note=ed["copy"]["continents"].get(c, "")) for c in CONT_ORDER if ed["counts"].get(c)])


def load_site_config(path: str) -> dict:
    cfg = {"title": "大洲日记", "tagline": "每天一次，读懂各大洲的外交外事", "base_url": "", "contact_email": "",
           "subscribe_form_url": "", "publisher": "", "deploy": {}}
    p = Path(path)
    if p.exists():
        cfg.update({k: v for k, v in (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).items() if v is not None})
    if cfg["base_url"] and not cfg["base_url"].endswith("/"):
        cfg["base_url"] += "/"
    return cfg


def main():
    ap = argparse.ArgumentParser(description="生成面向订阅者的多页面网站")
    ap.add_argument("--db", default="data/diary.db")
    ap.add_argument("--config", default="sources_v1.yaml")
    ap.add_argument("--site-config", default="site_config.yaml")
    ap.add_argument("--out", default="site")
    ap.add_argument("--hours", type=float, default=36)
    ap.add_argument("--min-rel", type=int, default=2)
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--asof", default=None, help="日报截止时间，如 \"2026-10-18 08:00\"（本地时间）")
    args = ap.parse_args()

    cfg = load_site_config(args.site_config)
    conn = sqlite3.connect(args.db)
    ed = edition.collect(conn, args.config, args.hours, args.min_rel, args.top, ranking.parse_asof(args.asof))
    edition.apply_copy(ed, edition.load_digest(conn, ed["date"]))

    out = Path(args.out)
    (out / "assets").mkdir(parents=True, exist_ok=True)
    (out / "assets" / "style.css").write_text(CSS, encoding="utf-8")
    ed_dir = out / "d" / ed["date"]
    n = write_edition(ed_dir, "../../", ed, cfg, archived=ed["date"])
    (ed_dir / "edition.json").write_text(json.dumps(edition_json(ed), ensure_ascii=False, indent=1), encoding="utf-8")
    # 根目录放最新一期：先清掉上一期遗留的页面
    for f in list(out.glob("story-*.html")) + [out / "index.html"] + [out / f"{c}.html" for c in CONT_ORDER]:
        f.unlink(missing_ok=True)
    write_edition(out, "", ed, cfg)

    editions = []
    for f in sorted((out / "d").glob("*/edition.json"), reverse=True):
        editions.append(json.loads(f.read_text(encoding="utf-8")))
    files = files_in(out)
    (out / "archive.html").write_text(render_archive(editions, cfg), encoding="utf-8")
    (out / "subscribe.html").write_text(render_subscribe(cfg, files), encoding="utf-8")
    (out / "about.html").write_text(render_about(cfg), encoding="utf-8")
    (out / "feed.xml").write_text(render_feed(editions, cfg), encoding="utf-8")
    (out / "robots.txt").write_text("User-agent: *\nAllow: /\n" + (f"Sitemap: {cfg['base_url']}feed.xml\n" if cfg["base_url"] else ""), encoding="utf-8")
    (out / "404.html").write_text(layout(cfg, "/" if False else "", "页面不存在", '<h1 class="story">页面不存在</h1><p><a href="index.html">回到首页</a></p>'), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    print(f"已生成 {ed['date']} 这一期：{n} 个页面（要闻 {len(ed['heads'])} 条）→ {out}/ ，存档 {ed_dir}/")
    if not cfg["base_url"]:
        print("提示：site_config.yaml 里还没有设置 base_url，RSS、分享卡片二维码和邮件链接需要它，网站发布后请补上。")


if __name__ == "__main__":
    main()
