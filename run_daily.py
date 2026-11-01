#!/usr/bin/env python3
"""
每日流水线：采集 -> 打标签 -> 聚类 -> 编辑台 -> 事件分析 -> 外宣稿 -> 编辑部导读 -> 分享卡片 -> PDF -> 订阅网站 -> 开发者工作台（-> 发布），一条命令跑完。

用法：
  python run_daily.py                  # 完整流程
  python run_daily.py --top 8          # 分析前 8 个事件
  python run_daily.py --skip-analyze   # 只做到聚类，不调用大模型（省钱、调试用）
  python run_daily.py --no-collect     # 采集器已经在另一个终端循环运行时，可以跳过采集

每一步的输出都会同时写入 logs/daily_日期.log，方便出问题时回看。
"""
import argparse
import datetime as dt
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def freshness(log) -> None:
    """打印库里最新一条报道距今多久；超过 12 小时说明采集器没在工作"""
    try:
        latest = sqlite3.connect("data/diary.db").execute("SELECT MAX(published_utc) FROM articles").fetchone()[0]
        t = dt.datetime.fromisoformat(latest)
        age = (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600
        msg = f"\n[数据新鲜度] 最新一条报道发布于 {t.astimezone():%Y-%m-%d %H:%M}，距今 {age:.1f} 小时"
        if age > 12:
            msg += "\n  ⚠ 数据已经过期！采集器可能没有运行。请去掉 --no-collect 重新运行，或另开终端运行 python collector.py --loop 30"
    except Exception as e:
        msg = f"\n[数据新鲜度] 无法检查：{e}"
    print(msg)
    log.write(msg + "\n")


def run(step: str, cmd: list[str], log) -> bool:
    banner = f"\n{'=' * 8} {step} {'=' * 8}\n$ {' '.join(cmd)}\n"
    print(banner, end="")
    log.write(banner)
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}  # Windows 下子进程默认用 GBK 输出，会和这里的 UTF-8 解码冲突造成乱码
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)
    out = proc.stdout + (("\n[stderr]\n" + proc.stderr) if proc.stderr.strip() else "")
    print(out)
    log.write(out + "\n")
    log.flush()
    ok = proc.returncode == 0
    if not ok:
        msg = f"!! 步骤“{step}”失败（退出码 {proc.returncode}）\n"
        print(msg)
        log.write(msg)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="sources_v1.yaml")
    ap.add_argument("--top", type=int, default=5)
    ap.add_argument("--skip-analyze", action="store_true")
    ap.add_argument("--no-collect", action="store_true")
    ap.add_argument("--no-outreach", action="store_true", help="不生成外宣稿")
    ap.add_argument("--publish", action="store_true", help="最后执行 publish.py，把网站推送到发布仓库（先做密钥泄露检查）")
    ap.add_argument("--asof", default=None, help="日报截止时间，如 \"2026-10-18 08:00\"（本地时间）；固定它，同一期日报重复生成结果一致")
    args = ap.parse_args()
    asof = ["--asof", args.asof] if args.asof else []

    Path("logs").mkdir(exist_ok=True)
    py = sys.executable
    with open(f"logs/daily_{dt.datetime.now():%Y%m%d}.log", "a", encoding="utf-8") as log:
        log.write(f"\n\n######## 开始 {dt.datetime.now():%Y-%m-%d %H:%M:%S} ########\n")
        results = {}
        if not args.no_collect:
            results["采集"] = run("采集", [py, "collector.py", "--config", args.config], log)  # 部分信源失败不影响后续
        freshness(log)
        run("信源覆盖", [py, "coverage.py", "--config", args.config, *asof], log)  # 数字为什么变，看这里
        results["打标签"] = run("打标签", [py, "geotag.py", "--config", args.config, "--examples", "0"], log)
        if results["打标签"]:
            results["聚类"] = run("聚类", [py, "cluster.py", "--md", "reports/events.md", *asof], log)
        if results.get("聚类") and not args.skip_analyze:
            results["编辑台"] = run("编辑台", [py, "editor.py", "--config", args.config, *asof], log)  # 失败时自动退回规则版，不影响后续
            results["分析"] = run("事件分析", [py, "analyze.py", "--config", args.config, "--top", str(args.top), *asof], log)
        if "分析" in results and not args.no_outreach:
            results["外宣稿"] = run("外宣稿草案", [py, "outreach.py", "--config", args.config, *asof], log)  # 失败不影响网页生成
        if results.get("聚类"):
            if not args.skip_analyze:
                run("编辑部导读", [py, "digest.py", "--config", args.config, *asof], log)  # 没配置大模型时自动用回退文字
            results["分享卡片"] = run("微信分享卡片", [py, "cards.py", "--config", args.config, *asof], log)
            results["PDF"] = run("PDF 日报", [py, "make_pdf.py", "--config", args.config, *asof], log)
            results["订阅网站"] = run("生成订阅网站", [py, "build_web.py", "--config", args.config, *asof], log)
            results["工作台"] = run("开发者工作台", [py, "build_site.py", "--config", args.config, *asof], log)  # 输出到 devsite/，不对外发布
            if args.publish and results["订阅网站"]:
                results["发布"] = run("发布网站", [py, "publish.py"], log)
        summary = "\n".join(f"  {k}: {'成功' if v else '失败'}" for k, v in results.items())
        print("\n===== 汇总 =====\n" + summary)
        log.write("\n===== 汇总 =====\n" + summary + "\n")


if __name__ == "__main__":
    main()
