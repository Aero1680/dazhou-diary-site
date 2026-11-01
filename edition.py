# -*- coding: utf-8 -*-
"""
一期日报的数据整理：网页、PDF、分享卡片、邮件都读这一份，保证各渠道内容一致。

collect()     从数据库取出这一期的头条、各大洲动态、风险提示
apply_copy()  套上面向读者的文字（digest.py 生成的导读；没有时用确定性的回退文字，页面永远有内容）
"""
from __future__ import annotations

import datetime as dt
import difflib
import json
import re
from collections import Counter

import analyze
import ranking
import risk
from geo_data import CONTINENT_ZH

CONT_ORDER = ["asia", "europe", "africa", "north_america", "south_america", "oceania", "global"]
WEEKDAY = "一二三四五六日"
SCENARIO_LABEL = {"基准": "最可能的走向", "乐观": "向好的可能", "风险": "向坏的可能"}
BASIS_LABEL = {"材料": "报道所述", "背景": "背景知识", "推断": "AI 判断"}


def slug(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", key)[:12] or "x"


def head_title(h: dict) -> str:
    return h["an"].get("headline") or h["ev"].get("title_zh") or h["ev"]["title"]


def _norm(s: str) -> str:
    return re.sub(r"\W", "", s or "")


def similar(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() > 0.75


def first_clause(s: str, n: int = 60) -> str:
    return re.split(r"[；。;]", (s or "").strip())[0][:n]


def collect(conn, config: str, hours: float = 36, min_rel: int = 2, top: int = 5, asof=None, per_cont: int = 8) -> dict:
    meta = analyze.load_source_meta(config)
    names = {k: v["name"] for k, v in meta.items()}
    ref_utc = asof or dt.datetime.now(dt.timezone.utc)
    local = ref_utc.astimezone()
    ranked = ranking.load_ranked_events(conn, hours, 1, asof)
    shown = [e for e in ranked if e["rel_int"] >= min_rel]

    ana = {}
    for key, status, analysis, model in conn.execute("SELECT event_key,status,analysis,model FROM analyses"):
        if model != "mock" and status == "ok":
            ana[key] = json.loads(analysis)

    heads, seen = [], set()
    for e in shown:
        if e["event_key"] in ana and e["storyline"] not in seen and len(heads) < top:
            an = ana[e["event_key"]]
            evidence = an.get("_evidence") or analyze.build_evidence(conn, e["event_key"], names, 8, meta)
            group = ranking.storyline_group(ranked, e["storyline"]) or [e]
            heads.append(dict(slug=slug(e["event_key"]), key=e["event_key"], ev=e, an=an, evidence=evidence,
                              n_articles=sum(g["n_articles"] for g in group), n_events=len(group), risk=None))
            seen.add(e["storyline"])

    risks = {}
    for e in shown:
        r = risk.risk_for_event(e, ana.get(e["event_key"]))
        if r:
            risks[e["event_key"]] = r
    for h in heads:
        h["risk"] = risks.get(h["key"])

    covered = {h["ev"]["storyline"] for h in heads}
    rest = [e for e in shown if e["storyline"] not in covered]
    by_cont = {c: {"heads": [], "others": []} for c in CONT_ORDER}
    for h in heads:
        by_cont.setdefault(h["ev"]["continent"], {"heads": [], "others": []})["heads"].append(h)
    for e in rest:
        bucket = by_cont.setdefault(e["continent"], {"heads": [], "others": []})["others"]
        if len(bucket) >= per_cont:
            continue
        arts = conn.execute(
            "SELECT a.source_id, a.title, a.url FROM event_articles ea JOIN articles a ON a.id=ea.article_id "
            "WHERE ea.event_key=? ORDER BY a.tier, a.published_utc LIMIT 2", (e["event_key"],)).fetchall()
        bucket.append(dict(ev=e, risk=risks.get(e["event_key"]),
                           links=[(names.get(s, s), t, u) for s, t, u in arts]))

    # 风险雷达：每条故事线取一个，最多 3 条，至少"关注"级
    radar, seen_st = [], set()
    cand = sorted(shown, key=lambda x: (-risk.LEVEL_ORDER.get((risks.get(x["event_key"]) or {"level": "蓝"})["level"], 0),
                                       -(risks.get(x["event_key"]) or {"score": 0})["score"]))
    head_by_story = {h["ev"]["storyline"]: h for h in heads}
    for e in cand:
        r = risks.get(e["event_key"])
        if r and (r["level"] in ("红", "橙") or (r["china"] and r["level"] == "黄")) and e["storyline"] not in seen_st and len(radar) < 3:
            seen_st.add(e["storyline"])
            h = head_by_story.get(e["storyline"])
            radar.append(dict(risk=r, title=head_title(h) if h else (e.get("title_zh") or e["title"]),
                              slug=h["slug"] if h else None, china=r["china"]))

    latest = conn.execute("SELECT MAX(published_utc) FROM articles WHERE published_utc <= ?", (ref_utc.isoformat(timespec="seconds"),)).fetchone()[0]
    age_h = None
    if latest:
        age_h = (ref_utc - dt.datetime.fromisoformat(latest)).total_seconds() / 3600
    counts = {c: len(by_cont.get(c, {"heads": [], "others": []})["heads"]) + len(by_cont.get(c, {"others": []})["others"]) for c in CONT_ORDER}
    return dict(date=local.strftime("%Y-%m-%d"), local=local, weekday="周" + WEEKDAY[local.weekday()],
                latest_pub=latest, age_h=age_h, heads=heads, by_cont=by_cont, radar=radar, counts=counts,
                n_events=len(shown), n_articles=sum(e["n_articles"] for e in shown))


# ------------------------------------------------------------------ 面向读者的文字
def default_copy(ed: dict) -> dict:
    """没有大模型导读时的确定性回退文字（直接取自已通过核查的分析），页面永远有内容"""
    heads = ed["heads"]
    lead = ("今天最受关注的是：" + "；".join(head_title(h) for h in heads[:2]) + "。") if heads else "今天暂无达到发布标准的重点事件。"
    items = {}
    for h in heads:
        an, title = h["an"], head_title(h)
        one = (an.get("plain") or {}).get("one_line") or ""
        facts = [f.get("text", "") for f in an.get("facts", [])]
        summary = one if one and not similar(one, title) else (facts[0] if facts else "")
        drivers = an.get("drivers") or []
        why = first_clause(drivers[0].get("claim", "")) if drivers else ""
        base = next((s for s in (an.get("outlook") or {}).get("scenarios", []) if s.get("name") == "基准"), None)
        nxt = analyze.join_cn(((base or {}).get("indicators") or [])[:2])
        items[h["key"]] = {"summary": summary[:90], "why": why, "next": nxt}
    conts = {}
    for c in CONT_ORDER:
        grp = ed["by_cont"].get(c) or {"heads": [], "others": []}
        titles = [head_title(h) for h in grp["heads"]] + [(o["ev"].get("title_zh") or o["ev"]["title"]) for o in grp["others"]]
        if titles:
            conts[c] = f"今天有 {len(titles)} 件值得关注：" + "；".join(titles[:2]) + ("等。" if len(titles) > 2 else "。")
    return {"lead": lead, "items": items, "continents": conts}


def apply_copy(ed: dict, digest: dict | None) -> dict:
    """digest（模型写的导读）覆盖回退文字；字段缺失或为空就用回退文字"""
    copy = default_copy(ed)
    if digest:
        if digest.get("lead"):
            copy["lead"] = digest["lead"]
        for k, v in (digest.get("items") or {}).items():
            if k in copy["items"]:
                for f in ("summary", "why", "next"):
                    if v.get(f):
                        copy["items"][k][f] = v[f]
        for c, t in (digest.get("continents") or {}).items():
            if t and c in copy["continents"]:
                copy["continents"][c] = t
    ed["copy"] = copy
    return ed


def load_digest(conn, date: str) -> dict | None:
    try:
        row = conn.execute("SELECT content FROM digests WHERE edition=?", (date,)).fetchone()
    except Exception:
        return None
    return json.loads(row[0]) if row else None
