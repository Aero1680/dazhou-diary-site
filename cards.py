#!/usr/bin/env python3
"""
微信分享卡片：竖版 PNG（1080×1440），适合发到微信群、朋友圈。

  card-daily.png   今日要闻合集卡片
  card-1.png …     每条要闻各一张（标题、为什么重要、接下来看什么）

卡片底部有二维码，扫码打开网站（需要在 site_config.yaml 里设置 base_url；没设置时用文字提示）。
依赖：Pillow（已随 requirements 安装）、qrcode（pip install qrcode）。
字体：自动查找 微软雅黑/宋体（Windows）、苹方/宋体（macOS）、Noto CJK（Linux）；
      也可以用环境变量 DAZHOU_FONT / DAZHOU_FONT_SERIF 指定字体文件。

用法：
  python cards.py
  python cards.py --asof "2026-10-18 08:00"
"""
from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import edition
import ranking
from build_web import load_site_config
from edition import head_title
from geo_data import CONTINENT_ZH
import risk

W, H = 1080, 1440
M = 84
PAPER, INK, MUTED, ACCENT, TINT = "#F3F5F4", "#0F2A3D", "#566872", "#1C6B73", "#E1EAEA"
LV_COLOR = {"蓝": "#3F6B8F", "黄": "#85600A", "橙": "#AE4A0B", "红": "#B3261E"}

SANS = [os.environ.get("DAZHOU_FONT"), "C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf",
        "/System/Library/Fonts/PingFang.ttc", "/System/Library/Fonts/STHeiti Medium.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc"]
SANS_B = [os.environ.get("DAZHOU_FONT_BOLD"), "C:/Windows/Fonts/msyhbd.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"]
SERIF = [os.environ.get("DAZHOU_FONT_SERIF"), "C:/Windows/Fonts/simsun.ttc", "/System/Library/Fonts/Songti.ttc",
         "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc", "/usr/share/fonts/noto-cjk/NotoSerifCJK-Regular.ttc"]
SERIF_B = [os.environ.get("DAZHOU_FONT_SERIF_BOLD"), "/usr/share/fonts/opentype/noto/NotoSerifCJK-Bold.ttc"]


def _first(paths):
    return next((p for p in paths if p and Path(p).exists()), None)


_cache: dict = {}


def font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (kind, size)
    if key not in _cache:
        order = {"sans": SANS, "sansb": SANS_B + SANS, "serif": SERIF, "serifb": SERIF_B + SERIF}[kind]
        path = _first(order)
        faux = kind.endswith("b") and path is not None and path not in [p for p in (SANS_B if kind == "sansb" else SERIF_B) if p]
        if not path:
            raise SystemExit("找不到中文字体。请用环境变量 DAZHOU_FONT 指定一个中文字体文件（如 C:/Windows/Fonts/msyh.ttc）。")
        idx = 2 if ("NotoSansCJK" in path or "NotoSerifCJK" in path) and path.endswith(".ttc") else 0  # Noto 合集里 2 是简体
        f = ImageFont.truetype(path, size, index=idx)
        f.faux = faux
        _cache[key] = f
    return _cache[key]


NO_START = set("，。、；：？！）》”’,.;:?!)]}")
NO_END = set("（《“‘([{")


def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines, cur = [], ""
    for ch in text.replace("\n", " "):
        trial = cur + ch
        if f.getlength(trial) <= max_w or not cur:
            cur = trial
            continue
        if ch in NO_START and cur:  # 标点不出现在行首：把前一个字符一起挪下来
            lines.append(cur[:-1])
            cur = cur[-1] + ch
        elif cur[-1] in NO_END:
            lines.append(cur[:-1])
            cur = cur[-1] + ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def text_block(d: ImageDraw.ImageDraw, text: str, x: int, y: int, f, fill, max_w: int, line_h: int, max_lines: int, bold: bool = False) -> int:
    lines = wrap(text, f, max_w)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip("，。、；： ")[:-1] + "…"
    for ln in lines:
        d.text((x, y), ln, font=f, fill=fill, stroke_width=1 if (bold and getattr(f, "faux", False)) else 0, stroke_fill=fill)
        y += line_h
    return y


def height_of(text: str, f, max_w: int, line_h: int, max_lines: int) -> int:
    return min(len(wrap(text, f, max_w)), max_lines) * line_h


def draw_seal(img: Image.Image, cx: int, cy: int, r: int, local, weekday: str) -> None:
    k = 3  # 放大 3 倍绘制，再缩小，边缘更平滑
    R = r * k
    layer = Image.new("RGBA", (R * 2 + 60, R * 2 + 60), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    c = R + 30
    d.ellipse((c - R, c - R, c + R, c + R), outline=ACCENT, width=max(10, R // 14))
    d.ellipse((c - R * .86, c - R * .86, c + R * .86, c + R * .86), outline=ACCENT, width=5)
    for text, f, dy in ((f"{local.month}月", font("serif", int(R * .26)), -.52), (str(local.day), font("serifb", int(R * .78)), -.02), (weekday, font("serif", int(R * .22)), .55)):
        w = f.getlength(text)
        d.text((c - w / 2, c + R * dy - f.size / 2), text, font=f, fill=ACCENT)
    layer = layer.rotate(8, resample=Image.BICUBIC, center=(c, c))
    layer = layer.resize((layer.width // k, layer.height // k), Image.LANCZOS)
    c //= k
    img.paste(layer, (cx - c, cy - c), layer)


def qr_image(url: str, size: int):
    try:
        import qrcode
    except ImportError:
        return None
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(url)
    qr.make(fit=True)
    im = qr.make_image(fill_color=INK, back_color="white")
    im = im.get_image() if hasattr(im, "get_image") else im
    return im.convert("RGB").resize((size, size), Image.NEAREST)


def footer(img: Image.Image, d: ImageDraw.ImageDraw, cfg: dict, date_txt: str) -> None:
    y0 = img.height - 270
    d.line((M, y0, W - M, y0), fill="#C9D5D6", width=2)
    base = cfg.get("base_url") or ""
    qr = qr_image(base, 190) if base else None
    if qr:
        img.paste(qr, (W - M - 190, y0 + 38))
    else:
        d.rounded_rectangle((W - M - 190, y0 + 38, W - M, y0 + 228), radius=10, outline="#C9D5D6", width=2)
        text_block(d, "设置 base_url 并安装 qrcode 后显示二维码" if base else "发布网站后显示二维码", W - M - 175, y0 + 90, font("sans", 24), MUTED, 160, 34, 4)
    left_w = W - 2 * M - 230
    d.text((M, y0 + 40), "扫码阅读全文", font=font("serifb", 40), fill=INK, stroke_width=1 if getattr(font("serifb", 40), "faux", False) else 0, stroke_fill=INK)
    y = text_block(d, base.replace("https://", "").replace("http://", "").rstrip("/") if base else "", M, y0 + 100, font("sans", 28), ACCENT, left_w, 38, 2)
    d.text((M, y0 + 172), f"{cfg['title']}　{date_txt}", font=font("sans", 26), fill=MUTED)
    d.text((M, y0 + 210), "AI 辅助生成，请以原始来源为准", font=font("sans", 24), fill=MUTED)


def pill(d, x, y, text, color) -> int:
    f = font("sansb", 26)
    w = int(f.getlength(text)) + 44
    d.rounded_rectangle((x, y, x + w, y + 44), radius=22, outline=color, width=3)
    d.ellipse((x + 16, y + 17, x + 26, y + 27), fill=color)
    d.text((x + 34, y + 3), text, font=f, fill=color)
    return x + w + 14


def header(img, d, ed, cfg) -> int:
    draw_seal(img, M + 100, 190, 100, ed["local"], ed["weekday"])
    d.text((M + 250, 118), cfg["title"], font=font("serifb", 108), fill=INK, stroke_width=2 if getattr(font("serifb", 108), "faux", False) else 0, stroke_fill=INK)
    d.text((M + 252, 262), f"{ed['local'].year}年{ed['local'].month}月{ed['local'].day}日 {ed['weekday']}", font=font("sans", 34), fill=MUTED)
    return 340


def fit_font(text: str, kind: str, base: int, width: int):
    """标题尽量不留下孤字：最后一行只剩 1~2 个字时，把字号微调小一点"""
    for sz in range(base, int(base * .8), -2):
        f = font(kind, sz)
        lines = wrap(text, f, width)
        if len(lines) == 1 or len(lines[-1]) >= 3:
            return f
    return font(kind, base)


def _daily(ed: dict, cfg: dict, hc: int, sc: float, heads: list[dict]):
    copy = ed["copy"]
    img = Image.new("RGB", (W, hc), PAPER)
    d = ImageDraw.Draw(img)
    y = header(img, d, ed, cfg)
    y = text_block(d, copy["lead"], M, y, font("serif", 42), INK, W - 2 * M, 66, 3) + 26
    d.text((M, y), "今日要闻", font=font("serifb", 40), fill=ACCENT, stroke_width=1 if getattr(font("serifb", 40), "faux", False) else 0, stroke_fill=ACCENT)
    y += 76
    tw = W - 2 * M - 90
    sf = font("sans", int(29 * sc))
    for i, h in enumerate(heads, 1):
        c = copy["items"][h["key"]]
        tf = fit_font(head_title(h), "serifb", int(44 * sc), tw)
        d.text((M, y - 6), str(i), font=font("serifb", int(70 * sc)), fill=ACCENT)
        x0 = M + 90
        y = text_block(d, head_title(h), x0, y, tf, INK, tw, int(60 * sc), 2, bold=True)
        if c.get("summary") and not edition.similar(c["summary"], head_title(h)):
            y = text_block(d, c["summary"], x0, y + 4, sf, MUTED, tw, int(42 * sc), 2)
        r = h["risk"]
        if r and r["level"] in ("红", "橙", "黄"):
            pill(d, x0, y + 6, risk.LEVEL_LABEL[r["level"]], LV_COLOR[r["level"]])
            y += 52
        y += int(34 * sc)
    return img, d, y


def daily_card(ed: dict, cfg: dict) -> Image.Image:
    """高度自适应：内容多就拉长（最高 1920），放不下再缩小字号，仍放不下就少放几条"""
    heads, chosen, sc = ed["heads"][:5], None, 1.0
    for n in range(len(heads), 0, -1):
        for s_ in (1.0, .92, .84):
            _, _, y_end = _daily(ed, cfg, 2800, s_, heads[:n])
            if y_end + 300 <= 1920:
                chosen, sc = heads[:n], s_
                break
        if chosen:
            break
    chosen = chosen or heads[:1]
    _, _, y_end = _daily(ed, cfg, 2800, sc, chosen)
    hc = max(H, min(1920, y_end + 300))
    img, d, y = _daily(ed, cfg, hc, sc, chosen)
    if len(chosen) < len(heads):
        d.text((M + 90, y - 12), f"另有 {len(heads) - len(chosen)} 条要闻，见网站", font=font("sans", 28), fill=MUTED)
    footer(img, d, cfg, ed["date"])
    return img


def story_card(ed: dict, cfg: dict, h: dict) -> Image.Image:
    c = ed["copy"]["items"][h["key"]]
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    y = header(img, d, ed, cfg) + 20
    ev = h["ev"]
    x = M
    d.rounded_rectangle((x, y, x + 120, y + 44), radius=22, fill=TINT)
    d.text((x + 24, y + 3), CONTINENT_ZH.get(ev["continent"], ""), font=font("sans", 26), fill=INK)
    r = h["risk"]
    if r and r["level"] in ("红", "橙", "黄"):
        pill(d, x + 134, y, risk.LEVEL_LABEL[r["level"]], LV_COLOR[r["level"]])
    y += 90
    y = text_block(d, head_title(h), M, y, font("serifb", 62), INK, W - 2 * M, 88, 4, bold=True) + 24
    if c.get("summary"):
        y = text_block(d, c["summary"], M, y, font("serif", 36), MUTED, W - 2 * M, 58, 3) + 30
    for label, key in (("为什么重要", "why"), ("接下来看什么", "next")):
        if not c.get(key):
            continue
        bh = 54 + height_of(c[key], font("sans", 33), W - 2 * M - 64, 52, 3) + 36
        if y + bh > img.height - 300:
            break
        d.rounded_rectangle((M, y, W - M, y + bh), radius=14, fill=TINT)
        d.text((M + 32, y + 22), label, font=font("sansb", 28), fill=ACCENT)
        text_block(d, c[key], M + 32, y + 66, font("sans", 33), INK, W - 2 * M - 64, 52, 3)
        y += bh + 22
    footer(img, d, cfg, ed["date"])
    return img


def main():
    ap = argparse.ArgumentParser(description="微信分享卡片")
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
        raise SystemExit("这一期没有要闻，不生成卡片。")
    out = Path(args.out) / "d" / ed["date"]
    out.mkdir(parents=True, exist_ok=True)
    names = []
    daily_card(ed, cfg).save(out / "card-daily.png", optimize=True)
    names.append("card-daily.png")
    for i, h in enumerate(ed["heads"], 1):
        story_card(ed, cfg, h).save(out / f"card-{i}.png", optimize=True)
        names.append(f"card-{i}.png")
    for n in names:  # 同时放一份到网站根目录（最新一期）
        shutil.copyfile(out / n, Path(args.out) / n)
    print(f"已生成 {len(names)} 张卡片 → {out}/")
    if not cfg.get("base_url"):
        print("提示：site_config.yaml 里没有 base_url，卡片上的二维码会显示为提示文字。")
    try:
        import qrcode  # noqa: F401
    except ImportError:
        print("提示：没有安装 qrcode，卡片上没有二维码。请运行：pip install qrcode")


if __name__ == "__main__":
    main()
