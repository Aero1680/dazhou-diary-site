#!/usr/bin/env python3
"""
生成"大洲日记"日报网页（静态 HTML，双击就能用浏览器打开，不需要服务器）。

内容：
  - 今日头条：已完成研判的故事线，可展开查看 事实 / 动因 / 走向 / 通俗解读 / 来源
  - 按大洲分栏：各大洲的其他重要事件（中文标题 + 摘要 + 来源链接）
  - 证据强度（信源数、国别多样性、是否含官方源）由程序计算，替代模型自报的置信度
  - 未通过自动核查的事件不会发布；被自动移除的内容记在卡片底部的"质检记录"里（全程无需人工）

用法：
  python build_site.py                  # 生成开发者工作台 devsite/index.html（不对外发布），并归档一份 devsite/archive/日期.html
  python build_site.py --top 5 --hours 36
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import shutil
import sqlite3
from pathlib import Path

import analyze
import coverage
import outreach
import ranking
import risk
from geo_data import CONTINENT_ZH

CONT_ORDER = ["asia", "europe", "africa", "north_america", "south_america", "oceania", "global"]
TIER_LABEL = analyze.TIER_LABEL
esc = html.escape

CSS = """
:root{--bg:#f6f5f1;--card:#ffffff;--ink:#1c1c1a;--muted:#6b6a63;--line:#e3e1d8;--accent:#1f4e79;--accent-soft:#e8eff6;
--ok:#2e7d4f;--ok-bg:#e6f3ec;--warn:#a85d00;--warn-bg:#fdf0dc;--basis-fact:#1f4e79;--basis-bg:#e8eff6;--basis-infer:#7a3b8f;--basis-infer-bg:#f2e8f6;
--basis-ctx:#55605a;--basis-ctx-bg:#ecefed}
@media (prefers-color-scheme:dark){:root{--bg:#161614;--card:#201f1d;--ink:#ecebe5;--muted:#a09e94;--line:#34332f;--accent:#8db7e0;--accent-soft:#1f2c38;
--ok:#7fcf9c;--ok-bg:#1d3125;--warn:#f0b35a;--warn-bg:#3a2c14;--basis-fact:#8db7e0;--basis-bg:#1f2c38;--basis-infer:#cfa3e0;--basis-infer-bg:#2f2236;
--basis-ctx:#b4bdb7;--basis-ctx-bg:#2a2d2b}}
*{box-sizing:border-box}
html{scroll-behavior:smooth;scroll-padding-top:64px}
body{margin:0;background:var(--bg);color:var(--ink);line-height:1.75;
font-family:"Noto Sans SC","PingFang SC","Microsoft YaHei","Helvetica Neue",Arial,sans-serif;-webkit-print-color-adjust:exact;print-color-adjust:exact}
.wrap{max-width:900px;margin:0 auto;padding:0 20px 60px}
header.top{padding:48px 0 20px;border-bottom:2px solid var(--ink)}
header.top h1{margin:0;font-family:"Noto Serif SC","Songti SC","SimSun",serif;font-size:2.4rem;letter-spacing:.12em}
header.top p{margin:6px 0 0;color:var(--muted);font-size:.95rem}
.stats{display:flex;gap:22px;flex-wrap:wrap;margin-top:14px;font-size:.9rem;color:var(--muted)}
.stats b{color:var(--ink);font-size:1.15rem}
nav{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line);padding:10px 0;margin-bottom:8px;display:flex;gap:6px;flex-wrap:wrap}
nav a{text-decoration:none;color:var(--accent);padding:3px 12px;border-radius:14px;font-size:.88rem;background:var(--accent-soft)}
h2.sec{font-family:"Noto Serif SC","Songti SC","SimSun",serif;font-size:1.45rem;margin:38px 0 12px;padding-left:10px;border-left:4px solid var(--accent)}
details.card{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:14px 0;overflow:hidden}
details.card>summary{cursor:pointer;list-style:none;padding:16px 18px}
details.card>summary::-webkit-details-marker{display:none}
details.card>summary:before{content:"▸";color:var(--muted);margin-right:8px;display:inline-block;transition:transform .15s}
details.card[open]>summary:before{transform:rotate(90deg)}
.hl{font-weight:700;font-size:1.12rem}
.meta{display:block;margin:6px 0 0 20px;color:var(--muted);font-size:.84rem}
.badge{display:inline-block;font-size:.74rem;padding:1px 8px;border-radius:10px;margin-right:6px;vertical-align:middle;font-weight:600;white-space:nowrap}
.badge.ok{color:var(--ok);background:var(--ok-bg)}
.badge.warn{color:var(--warn);background:var(--warn-bg)}
.badge.fact{color:var(--basis-fact);background:var(--basis-bg)}
.badge.infer{color:var(--basis-infer);background:var(--basis-infer-bg)}
.badge.ctx{color:var(--basis-ctx);background:var(--basis-ctx-bg)}
.body{padding:2px 22px 20px;border-top:1px solid var(--line)}
.body h3{font-size:1rem;margin:22px 0 8px;color:var(--accent)}
.oneline{background:var(--accent-soft);border-radius:8px;padding:10px 14px;margin:16px 0 0;font-weight:600}
.alert{background:var(--warn-bg);color:var(--warn);border-radius:8px;padding:10px 14px;margin:16px 0 0;font-size:.9rem}
.alert ul{margin:6px 0 0;padding-left:20px}
ul.facts{padding-left:20px;margin:6px 0}
a.ref{color:var(--accent);text-decoration:none;font-size:.78rem;vertical-align:super;margin-left:1px}
.tw{overflow-x:auto}
table.drv{width:100%;min-width:560px;table-layout:fixed;border-collapse:collapse;font-size:.9rem;margin:6px 0}
table.drv th,table.drv td{border-bottom:1px solid var(--line);padding:8px 8px;text-align:left;vertical-align:top;overflow-wrap:anywhere;word-break:break-word}
table.drv th{color:var(--muted);font-weight:600;font-size:.8rem;white-space:nowrap}
table.drv td.nw{white-space:nowrap}
.scn{margin:12px 0;padding:10px 14px;border:1px solid var(--line);border-radius:8px}
.scn b{font-size:.95rem}
.bar{height:6px;background:var(--line);border-radius:3px;margin:6px 0 8px;overflow:hidden}
.bar span{display:block;height:100%;background:var(--accent)}
.scn small{display:block;color:var(--muted)}
.fals{border-left:3px solid var(--warn);padding:4px 12px;margin:10px 0}
ol.src{padding-left:22px;font-size:.88rem;color:var(--muted)}
ol.src a{color:var(--accent)}
ol.src li{margin:4px 0}
ul.evt{list-style:none;padding:0;margin:0}
ul.evt>li{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px 16px;margin:10px 0}
ul.evt .t{font-weight:600}
ul.evt .orig{display:block;color:var(--muted);font-size:.8rem}
ul.evt p{margin:4px 0 0;font-size:.92rem}
ul.evt .links{margin-top:6px;font-size:.84rem}
ul.evt .links a{color:var(--accent);text-decoration:none;display:block;overflow-wrap:anywhere}
.topic{font-size:.74rem;color:var(--accent);background:var(--accent-soft);padding:1px 8px;border-radius:10px;margin-right:6px;white-space:nowrap}
.muted{color:var(--muted);font-size:.85rem}
.lv:before{content:"●";margin-right:4px;font-size:.7em}
.lv{display:inline-block;font-size:.76rem;font-weight:700;padding:1px 9px;border-radius:10px;margin-right:6px;white-space:nowrap}
.lv.red{background:#fde8e8;color:#a31616}.lv.orange{background:#fdebd9;color:#a14a00}.lv.yellow{background:#fbf3cf;color:#7a6300}.lv.blue{background:#e3eefb;color:#1b4f8f}
@media (prefers-color-scheme:dark){.lv.red{background:#4a1f1f;color:#ff9a9a}.lv.orange{background:#4a2c14;color:#ffbb85}.lv.yellow{background:#443b14;color:#f0d667}.lv.blue{background:#1c2f47;color:#9cc4f0}}
ol.brief{padding-left:22px;margin:6px 0}ol.brief li{margin:10px 0}ol.brief a{color:var(--ink);text-decoration:none;border-bottom:1px solid var(--line)}
table.cmp{width:100%;min-width:560px;table-layout:fixed;border-collapse:collapse;font-size:.9rem;margin:6px 0}
table.cmp th,table.cmp td{border-bottom:1px solid var(--line);padding:8px;text-align:left;vertical-align:top;overflow-wrap:anywhere}
table.cmp th{color:var(--muted);font-weight:600;font-size:.8rem}
.draft{border:1px solid var(--line);border-radius:8px;margin:8px 0;padding:6px 14px}
.draft>summary{cursor:pointer;font-weight:600;padding:4px 0}
.draft p{margin:8px 0}
.draft-note{background:var(--warn-bg);color:var(--warn);border-radius:8px;padding:8px 12px;font-size:.88rem;margin:8px 0}
footer{margin-top:50px;padding-top:16px;border-top:1px solid var(--line);color:var(--muted);font-size:.82rem}
@media (max-width:600px){header.top h1{font-size:1.8rem}.body{padding:2px 14px 16px}}
@media print{
  nav{display:none}
  body{background:#fff;color:#000;font-size:11pt}
  :root{--card:#fff;--bg:#fff;--ink:#000;--line:#ccc}
  .wrap{max-width:none;padding:0}
  header.top{padding-top:0}
  details.card{break-inside:auto;border-color:#bbb}
  details.card>summary:before{content:""}
  a{color:inherit;text-decoration:none}
  .scn,.fals,table.drv tr,.oneline,ul.evt>li{break-inside:avoid}
  h2.sec,.body h3{break-after:avoid}
  .tw{overflow:visible}
  table.drv{min-width:0}
}
"""

SCRIPT = """<script>
(function(){var st=[];
window.addEventListener('beforeprint',function(){st=[];document.querySelectorAll('details').forEach(function(d){st.push(d.open);d.open=true;});});
window.addEventListener('afterprint',function(){document.querySelectorAll('details').forEach(function(d,i){d.open=st[i];});});})();
</script>"""


def badge(text: str, cls: str) -> str:
    return f'<span class="badge {cls}">{esc(text)}</span>'


def ref_links(refs, idx: int, evidence: list[dict]) -> str:
    out = []
    for r in refs or []:
        if isinstance(r, int) and 1 <= r <= len(evidence):
            e = evidence[r - 1]
            tip = f"{e.get('source_name', '')}：{e.get('title', '')}"
            out.append(f'<a class="ref" href="#s{idx}-{r}" title="{esc(tip)}">[{r}]</a>')
    return "".join(out)


def strength_text(st: dict) -> str:
    return f"{st['n_sources']}个信源 · {st['n_countries']}个国家/地区" + (" · 含官方源" if st["has_official"] else "")


def render_card(idx: int, ev: dict, an: dict, status: str, issues: list[str], evidence: list[dict], is_open: bool,
                n_events: int, n_articles: int, ri: dict | None = None, orow: tuple | None = None) -> str:
    cs = "、".join(ev["countries"])
    st = an.get("_strength") or analyze.evidence_strength(evidence)
    st_cls = {"强": "ok", "中": "fact", "弱": "warn"}.get(st["label"], "ctx")
    head = an.get("headline") or ev["title_zh"] or ev["title"]
    risk_badge = f'<span class="lv {risk.LEVEL_CLS[ri["level"]]}">{risk.LEVEL_LABEL[ri["level"]]}</span>' if ri and ri["level"] in ("红", "橙", "黄") else ""
    pl = an.get("plain") or {}
    out = an.get("outlook") or {}
    h = [f'<details class="card" id="ev{idx}"{" open" if is_open else ""}><summary>',
         f'<span class="hl">{esc(head)}</span>',
         f'<span class="meta">{risk_badge}{badge("证据强度：" + st["label"], st_cls)}{badge(ev["category"], "ctx")}'
         f'{esc(CONTINENT_ZH.get(ev["continent"], ""))}{" · " + esc(cs) if cs else ""} · {n_articles}篇报道'
         f'{" · 合并" + str(n_events) + "个相关事件" if n_events > 1 else ""}</span>',
         '</summary><div class="body">']
    if pl.get("one_line"):
        h.append(f'<div class="oneline">{esc(pl["one_line"])}</div>')

    h.append("<h3>发生了什么（事实层）</h3><ul class='facts'>")
    for f in an.get("facts", []):
        h.append(f"<li>{esc(f.get('text', ''))}{ref_links(f.get('refs'), idx, evidence)}</li>")
    h.append("</ul>")
    if an.get("disagreements"):
        h.append("<h3>各方表述差异</h3><ul class='facts'>")
        for d in an["disagreements"]:
            h.append(f"<li>{esc(d.get('text', ''))}{ref_links(d.get('refs'), idx, evidence)}</li>")
        h.append("</ul>")

    sc = an.get("source_comparison") or {}
    if sc.get("rows") and len(evidence) >= 2:
        h.append("<h3>多源对照（各来源怎么说）</h3>")
        if sc.get("summary"):
            h.append(f"<p>{esc(sc['summary'])}</p>")
        h.append('<div class="tw"><table class="cmp"><colgroup><col style="width:26%"><col><col style="width:30%"></colgroup>'
                 '<tr><th>来源（所属国别）</th><th>叙述角度</th><th>关键措辞（原文）</th></tr>')
        for r in sc["rows"]:
            k = r.get("ref")
            if not (isinstance(k, int) and 1 <= k <= len(evidence)):
                continue
            e2 = evidence[k - 1]
            h.append(f"<tr><td>{esc(e2.get('source_name') or '')}<br><span class='muted'>{esc(e2.get('country') or '')}</span> "
                     f"<a class='ref' href='#s{idx}-{k}'>[{k}]</a></td><td>{esc(r.get('angle', ''))}</td>"
                     f"<td>{esc('；'.join(r.get('key_terms') or []))}</td></tr>")
        h.append("</table></div>")
    h.append('<h3>为什么会这样（动因层）</h3><div class="tw"><table class="drv"><colgroup><col style="width:16%"><col>'
             '<col style="width:11%"><col style="width:11%"></colgroup><tr><th>维度</th><th>判断</th><th>依据</th><th>置信度</th></tr>')
    cls = {"材料": "fact", "背景": "ctx", "推断": "infer"}
    for d in an.get("drivers", []):
        b = d.get("basis", "")
        h.append(f"<tr><td>{esc(d.get('dimension', ''))}</td><td>{esc(d.get('claim', ''))}{ref_links(d.get('refs'), idx, evidence)}</td>"
                 f"<td class='nw'>{badge(b, cls.get(b, 'ctx'))}</td><td class='nw'>{esc(d.get('confidence', ''))}</td></tr>")
    h.append("</table></div>")

    h.append(f"<h3>走向预判（未来约 {esc(str(out.get('horizon_days', 14)))} 天）</h3>")
    for s in out.get("scenarios", []):
        p = s.get("probability") or [0, 0]
        try:
            lo, hi = p
            mid = max(0, min(100, (lo + hi) / 2))
            prob = f"{lo}%–{hi}%"
        except Exception:
            mid, prob = 0, "?"
        h.append(f'<div class="scn"><b>{esc(s.get("name", ""))}情景 · {prob}</b><div class="bar"><span style="width:{mid:.0f}%"></span></div>'
                 f'{esc(s.get("description", ""))}'
                 f'<small>触发条件：{esc(analyze.join_cn(s.get("triggers")))}</small>'
                 f'<small>观察指标：{esc(analyze.join_cn(s.get("indicators")))}</small></div>')
    if out.get("falsifiers"):
        h.append(f'<div class="fals"><b>证伪条件</b>（出现下列情况，说明上述判断错了）：{esc(analyze.join_cn(out["falsifiers"]))}</div>')
    h.append('<p class="muted">预判是概率性判断，不是预言；所有预判已记入“预测账本”，到期后将与实际结果对照。</p>')

    if pl.get("three_minutes"):
        h.append(f"<h3>通俗解读</h3><p>{esc(pl['three_minutes'])}</p>")
        for t in pl.get("terms", []) or []:
            h.append(f"<p class='muted'><b>{esc(t.get('term', ''))}</b>：{esc(t.get('explain', ''))}</p>")
    if an.get("diplomatic_language"):
        h.append("<h3>外交辞令解读</h3><ul class='facts'>")
        for d in an["diplomatic_language"]:
            h.append(f"<li>“{esc(d.get('phrase', ''))}”（强度 {esc(str(d.get('level', '-')))}/5）：{esc(d.get('note', ''))}</li>")
        h.append("</ul>")
    if an.get("gaps"):
        h.append("<h3>证据缺口</h3><ul class='facts'>" + "".join(f"<li>{esc(g)}</li>" for g in an["gaps"]) + "</ul>")

    if ri and ri["level"] in ("红", "橙", "黄", "蓝"):
        h.append(f'<h3>风险预警</h3><p><span class="lv {risk.LEVEL_CLS[ri["level"]]}">{risk.LEVEL_LABEL[ri["level"]]}</span>'
                 f'{"<span class=\"badge ctx\">涉华</span>" if ri["china"] else ""}'
                 f'<span class="muted">{esc("；".join(ri["reasons"]))}</span></p>')
        if ri.get("watch"):
            h.append(f'<p class="muted">建议关注：{esc(analyze.join_cn(ri["watch"]))}</p>')
    if orow:
        o_status, o_data, o_issues = orow
        h.append("<h3>对外传播（传播策略与外宣稿草案）</h3>")
        h.append('<div class="draft-note">AI 自动生成并经自动核查的草案，仅供参考。</div>')
        h.append("<p><b>目标受众：</b>" + esc("；".join(o_data.get("audience") or [])) + "</p>")
        h.append("<p><b>核心信息：</b></p><ul class='facts'>" + "".join(f"<li>{esc(m.get('text', ''))}</li>" for m in o_data.get("core_messages") or []) + "</ul>")
        if o_data.get("avoid"):
            h.append("<p><b>应避免的表述：</b></p><ul class='facts'>" + "".join(f"<li>{esc(x)}</li>" for x in o_data["avoid"]) + "</ul>")
        if o_data.get("channels"):
            h.append("<p><b>建议渠道：</b>" + esc("；".join(o_data["channels"])) + "</p>")
        for d in o_data.get("drafts") or []:
            lg = d.get("lang", "")
            h.append(f'<details class="draft"><summary>{esc(outreach.LANGS.get(lg, lg))}：{esc(d.get("title", ""))}</summary>'
                     f'<p lang="{esc(lg)}"{' dir="rtl"' if lg == "ar" else ""}>{esc(d.get("body", ""))}</p>'
                     f'<p class="muted">中文大意：{esc(d.get("gloss_zh", ""))}</p></details>')
    # 质检记录（取代头部那个容易和"置信度"混淆的"已通过自动核查"）
    qa = [f"证据强度：{st['label']}（{strength_text(st)}；由程序按信源数、国别多样性、是否含官方源、摘要信息量计算）",
          "自动核查：通过" + (f"（已自动修正或移除 {len(an.get('_notes') or [])} 处无法核实的内容，见下）" if an.get("_notes") else "")]
    qa += list(an.get("_notes") or [])
    if an.get("overall_confidence"):
        qa.append(f"模型自评置信度：{an['overall_confidence']}（仅供参考，未参与评级）")
    h.append("<h3>质检记录</h3><ul class='facts muted'>" + "".join(f"<li>{esc(x)}</li>" for x in qa) + "</ul>")

    h.append("<h3>来源</h3><ol class='src'>")
    for k, e in enumerate(evidence, 1):
        link = f'<a href="{esc(e.get("url") or "#")}" target="_blank" rel="noopener">{esc(e.get("title") or "")}</a>'
        who = esc(e.get("source_name") or "") + (f"，{esc(e['country'])}" if e.get("country") else "")
        h.append(f'<li id="s{idx}-{k}">{who}（{esc(TIER_LABEL.get(e.get("tier"), ""))}）：{link}</li>')
    h.append("</ol></div></details>")
    return "".join(h)


def main():
    ap = argparse.ArgumentParser(description="生成日报网页")
    ap.add_argument("--db", default="data/diary.db")
    ap.add_argument("--config", default="sources_v1.yaml")
    ap.add_argument("--hours", type=float, default=36)
    ap.add_argument("--min-rel", type=int, default=2, help="编辑台相关度（0-3）至少多少才展示")
    ap.add_argument("--top", type=int, default=5, help="今日头条展示几条已研判的故事线")
    ap.add_argument("--per-continent", type=int, default=4)
    ap.add_argument("--out", default="devsite/index.html", help="开发者工作台，不对外发布；对外网站由 build_web.py 生成到 site/")
    ap.add_argument("--asof", default=None, help="日报截止时间，如 \"2026-10-18 08:00\"（本地时间）；固定它，同一期日报重复生成结果一致")
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='events'").fetchone():
        raise SystemExit("请先运行 python cluster.py")
    conn.executescript(analyze.SCHEMA)
    conn.executescript(outreach.SCHEMA)
    meta = analyze.load_source_meta(args.config)
    names = {k: v["name"] for k, v in meta.items()}

    asof = ranking.parse_asof(args.asof)
    ranked = ranking.load_ranked_events(conn, args.hours, 1, asof)
    shown = [e for e in ranked if e["rel_int"] >= args.min_rel]
    ana = {}
    for key, status, analysis, issues, model in conn.execute("SELECT event_key,status,analysis,issues,model FROM analyses"):
        if model != "mock" and status == "ok":
            ana[key] = (status, json.loads(analysis), json.loads(issues or "[]"))

    outs = {}
    for key, status, content, issues, model in conn.execute("SELECT event_key,status,content,issues,model FROM outreach"):
        if model != "mock" and status == "ok":
            outs[key] = (status, json.loads(content), json.loads(issues or "[]"))

    # 风险预警（规则版，见 risk.py）
    risks = {}
    for e in shown:
        r = risk.risk_for_event(e, ana[e["event_key"]][1] if e["event_key"] in ana else None)
        if r:
            risks[e["event_key"]] = r

    # 头条：按重要度遍历，每条故事线取第一个已有分析的事件
    heads, seen_story = [], set()
    for e in shown:
        if e["event_key"] in ana and e["storyline"] not in seen_story and len(heads) < args.top:
            heads.append(e)
            seen_story.add(e["storyline"])
    n_articles_total = sum(e["n_articles"] for e in shown)
    cov = coverage.source_coverage(conn, args.config, args.hours, asof)

    ref_utc = asof or dt.datetime.now(dt.timezone.utc)
    now = ref_utc.astimezone()
    latest = conn.execute("SELECT MAX(published_utc) FROM articles WHERE published_utc <= ?", (ref_utc.isoformat(timespec="seconds"),)).fetchone()[0]
    stale_html, latest_txt = "", "无数据"
    if latest:
        lt = dt.datetime.fromisoformat(latest).astimezone()
        age_h = (ref_utc - dt.datetime.fromisoformat(latest)).total_seconds() / 3600
        latest_txt = f"{lt:%m-%d %H:%M}"
        if age_h > 12:
            stale_html = (f'<div class="alert"><b>⚠ 数据已过期</b>：库里最新一条报道发布于 {lt:%Y-%m-%d %H:%M}（距今约 {age_h:.0f} 小时），'
                          f'下面的内容并不是“今天”的新闻。采集器可能已停止运行，请先运行 <code>python collector.py</code>，再重新生成。</div>')
    body = [f"""<header class="top"><h1>大洲日记</h1><p>外交外事每日研判 · AI 辅助生成 · 每个结论可溯源</p>
<div class="stats"><span>日期 <b>{now:%Y-%m-%d}</b></span><span>数据截至 <b>{latest_txt}</b></span><span>监测信源 <b>{cov["total"]}</b>（本期有稿 {cov["active"]}）</span><span>入选事件 <b>{len(shown)}</b></span>
<span>入选报道 <b>{n_articles_total}</b></span><span>已研判故事线 <b>{len(heads)}</b></span></div></header>"""]

    covered = {e["storyline"] for e in heads}
    rest = [e for e in shown if e["storyline"] not in covered]
    body.append(stale_html)
    nav = ['<a href="#brief">今日要点</a>', '<a href="#risk">风险预警</a>', '<a href="#top">今日头条</a>'] + [f'<a href="#c-{c}">{CONTINENT_ZH[c]}</a>' for c in CONT_ORDER if any(e["continent"] == c for e in rest)] + ['<a href="#data">数据概况</a>']
    body.append("<nav>" + "".join(nav) + "</nav>")

    # ---- 今日要点
    body.append('<h2 class="sec" id="brief">今日要点</h2>')
    if heads:
        lis = []
        for i, e in enumerate(heads, 1):
            an_h = ana[e["event_key"]][1]
            ri = risks.get(e["event_key"])
            chip = f'<span class="lv {risk.LEVEL_CLS[ri["level"]]}">{risk.LEVEL_LABEL[ri["level"]]}</span>' if ri and ri["level"] in ("红", "橙", "黄") else ""
            lis.append(f'<li><a href="#ev{i}"><b>{esc(an_h.get("headline") or e["title_zh"] or e["title"])}</b></a> {chip}'
                       f'<span class="topic">{esc(CONTINENT_ZH.get(e["continent"], ""))}</span><br>'
                       f'<span class="muted">{esc((an_h.get("plain") or {}).get("one_line") or "")}</span></li>')
        body.append('<ol class="brief">' + "".join(lis) + "</ol>")
    else:
        body.append('<p class="muted">暂无已研判事件。</p>')
    # ---- 风险预警
    seen_st, alerts = set(), []
    for e in sorted(shown, key=lambda x: (-risk.LEVEL_ORDER.get((risks.get(x["event_key"]) or {"level": "蓝"})["level"], 0), -(risks.get(x["event_key"]) or {"score": 0})["score"])):
        r = risks.get(e["event_key"])
        if r and r["level"] in ("红", "橙", "黄") and e["storyline"] not in seen_st and len(alerts) < 8:
            seen_st.add(e["storyline"])
            alerts.append((r, e))
    body.append('<h2 class="sec" id="risk">风险预警</h2>')
    if alerts:
        rows = "".join(
            f'<tr><td class="nw"><span class="lv {risk.LEVEL_CLS[r["level"]]}">{risk.LEVEL_LABEL[r["level"]]}</span>'
            f'{"<span class=\"badge ctx\">涉华</span>" if r["china"] else ""}</td>'
            f'<td>{esc(e["title_zh"] or e["title"])}</td><td>{esc("；".join(r["reasons"]))}</td>'
            f'<td>{esc(analyze.join_cn(r["watch"])) or "—"}</td></tr>' for r, e in alerts)
        body.append('<div class="tw"><table class="drv"><colgroup><col style="width:14%"><col style="width:26%"><col><col style="width:24%"></colgroup>'
                    '<tr><th>关注程度</th><th>事件</th><th>评定依据</th><th>建议关注</th></tr>' + rows + "</table></div>")
        body.append('<p class="muted">关注程度由规则按“涉华程度、议题类别、风险情景概率、报道广度”综合评分得出（高度警惕≥8分、警惕≥6分、关注≥4分），'
                    '只表示值得关注的程度，不是对事态发展的预言。</p>')
        body.append('<p class="muted">' + ' '.join(f'<span class="lv {risk.LEVEL_CLS[k]}">{risk.LEVEL_LABEL[k]}</span>{risk.LEVEL_MEANING[k]}　' for k in ('蓝', '黄', '橙', '红')) + '</p>')
    else:
        body.append('<p class="muted">当前没有达到黄色及以上的预警事件。</p>')
    body.append('<h2 class="sec" id="top">今日头条 · 重点研判</h2>')
    if not heads:
        body.append('<p class="muted">还没有已完成研判的事件。请先运行 <code>python analyze.py</code>。</p>')
    for i, e in enumerate(heads, 1):
        status, an, issues = ana[e["event_key"]]
        evidence = an.get("_evidence")
        if not evidence:  # 旧数据没有证据快照：重新构建（编号可能与分析时不一致，建议 --force 重新分析）
            evidence = analyze.build_evidence(conn, e["event_key"], names, 8, meta)
        group = ranking.storyline_group(ranked, e["storyline"]) or [e]
        body.append(render_card(i, e, an, status, issues, evidence, is_open=(i == 1),
                                n_events=len(group), n_articles=sum(g["n_articles"] for g in group),
                                ri=risks.get(e["event_key"]), orow=outs.get(e["event_key"])))

    for c in CONT_ORDER:
        sub = [e for e in rest if e["continent"] == c][: args.per_continent]
        if not sub:
            continue
        body.append(f'<h2 class="sec" id="c-{c}">{CONTINENT_ZH[c]}</h2><ul class="evt">')
        for e in sub:
            cs = "、".join(e["countries"])
            arts = conn.execute(
                "SELECT a.source_id, a.title, a.url FROM event_articles ea JOIN articles a ON a.id=ea.article_id "
                "WHERE ea.event_key=? ORDER BY a.tier, a.published_utc LIMIT 3", (e["event_key"],)).fetchall()
            links = "".join(f'<a href="{esc(u)}" target="_blank" rel="noopener">{esc(names.get(s, s))}：{esc(t)}</a>' for s, t, u in arts)
            main_t = e["title_zh"] or e["title"]
            orig = f'<span class="orig">{esc(e["title"])}</span>' if e["title_zh"] else ""
            summ = f'<p>{esc(e["summary_zh"])}</p>' if e.get("summary_zh") else ""
            body.append(f'<li><span class="topic">{esc(e["category"])}</span><span class="t">{esc(main_t)}</span>{orig}{summ}'
                        f'<div class="muted">{e["n_articles"]}篇报道 / {e["n_sources"]}个信源{" · " + esc(cs) if cs else ""}</div>'
                        f'<div class="links">{links}</div></li>')
        body.append("</ul>")

    def rate_txt(r):
        return f"{r['rate24']:.0%}（{r['tries24']}次）" if r["rate24"] is not None else "-"

    cov_rows = "".join(
        f"<tr><td>{esc(r['name'])}</td><td>{esc(r['tier'])}</td><td class='nw'>{r['n']}</td>"
        f"<td class='nw'>{esc(r['last_status'])}{' ⚠' if r['failed'] else ''}</td><td class='nw'>{rate_txt(r)}</td></tr>" for r in cov["rows"])
    body.append(
        '<h2 class="sec" id="data">数据概况</h2><details class="card"><summary>'
        f'<span class="hl">监测 {cov["total"]} 个信源 · 本期有稿 {cov["active"]} 个 · 最近一次抓取失败 {cov["failed"]} 个</span>'
        '<span class="meta">日报数字的变化主要来自：时间窗口滑动、信源临时抓取失败（超时/403/406）、某时段信源没有发稿</span></summary>'
        '<div class="body"><div class="tw"><table class="drv"><colgroup><col><col style="width:12%"><col style="width:16%"><col style="width:20%"><col style="width:22%"></colgroup>'
        '<tr><th>信源</th><th>层级</th><th>本期稿件</th><th>最近抓取</th><th>24小时成功率</th></tr>' + cov_rows + "</table></div></div></details>")
    body.append(f"""<footer>本页内容由程序自动采集公开新闻的标题与摘要，并由大模型辅助生成研判；国家与大洲标签、事件合并均为规则与算法判断，可能存在误差。
走向预判为概率性判断，不是预言。请以原始来源为准。生成时间：{now:%Y-%m-%d %H:%M}。</footer>""")

    page = (f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>大洲日记 {now:%Y-%m-%d}</title><style>{CSS}</style></head><body><div class="wrap">' + "".join(body)
            + "</div>" + SCRIPT + "</body></html>")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    arch = out.parent / "archive"
    arch.mkdir(exist_ok=True)
    shutil.copyfile(out, arch / f"{now:%Y-%m-%d}.html")
    print(f"已生成：{out}（头条研判 {len(heads)} 个，其他事件 {len(rest)} 个）\n归档：{arch / (now.strftime('%Y-%m-%d') + '.html')}")


if __name__ == "__main__":
    main()
