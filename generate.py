#!/usr/bin/env python3
"""每日科技早报生成器。

每天运行一次：抓取三类真实数据（国内要闻 / 科技动态 / GitHub 今日热门），
生成 editions/YYYY-MM-DD.md，更新 README.md（最新一期 + 历史索引），
并绘制 poster.png 早报图。

原则：每一类数据独立容错；抓不到就如实在当期标注缺失，绝不编造。
仅使用 Python 标准库，方便在任何机器上定时运行。

用法：python3 generate.py [YYYY-MM-DD]   # 不带参数则取北京时间今天
"""
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.abspath(__file__))
EDITIONS_DIR = os.path.join(ROOT, "editions")
CST = timezone(timedelta(hours=8))
UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}

WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def fetch(url, timeout=25):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def clean(text, limit=None):
    text = re.sub(r"<[^>]+>", "", text or "")
    text = re.sub(r"&[a-z#0-9]+;", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rstrip() + "…"
    return text


# ---------------- 国内要闻：60 秒读懂世界 ----------------

def fetch_domestic():
    """返回 (条目列表, 来源说明, 每日一句 or None)。失败抛异常。"""
    # 首选 vvhan
    try:
        data = json.loads(fetch("https://api.vvhan.com/api/60s").decode("utf-8"))
        news = (data.get("data") or {}).get("news") or []
        if news:
            return [clean(n) for n in news], "60 秒读懂世界（vvhan）", None
    except Exception:
        pass
    # 备选 viki 60s
    data = json.loads(fetch("https://60s-api.viki.moe/v2/60s").decode("utf-8"))
    payload = data.get("data") or {}
    news = payload.get("news") or []
    if not news:
        raise RuntimeError("60s 接口返回空")
    tip = payload.get("tip") or payload.get("weiyu")
    return [clean(n) for n in news], "60 秒读懂世界", clean(tip) if tip else None


# ---------------- 科技动态：IT之家 RSS ----------------

def fetch_tech(today):
    """取 IT之家 RSS 中北京时间当天的条目，最多 8 条。返回 (条目, 来源说明)。"""
    raw = fetch("https://www.ithome.com/rss/")
    root = ET.fromstring(raw)
    items = []
    fallback = []
    for item in root.iter("item"):
        title = clean(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        pub = item.findtext("pubDate") or ""
        if not title:
            continue
        entry = {"title": title, "link": link}
        fallback.append(entry)
        try:
            dt = datetime.strptime(pub.strip(), "%a, %d %b %Y %H:%M:%S %Z")
            dt = dt.replace(tzinfo=timezone.utc).astimezone(CST)
            if dt.date() == today:
                items.append(entry)
        except Exception:
            pass
    picked = items[:8] if len(items) >= 3 else fallback[:8]
    if not picked:
        raise RuntimeError("IT之家 RSS 无条目")
    return picked, "IT之家"


# ---------------- GitHub 今日热门 ----------------

def fetch_trending():
    html = fetch("https://github.com/trending?since=daily").decode("utf-8", "replace")
    rows = re.findall(r'<article class="Box-row".*?</article>', html, re.S)
    out = []
    for row in rows:
        m = re.search(r'<h2[^>]*>\s*<a [^>]*href="/([^"]+)"', row)
        if not m:
            continue
        name = m.group(1).strip()
        d = re.search(r'<p class="[^"]*color-fg-muted[^"]*">(.*?)</p>', row, re.S)
        desc = clean(d.group(1), 120) if d else ""
        s = re.search(r'href="/[^"]+/stargazers"[^>]*>.*?</svg>\s*([\d,]+)', row, re.S)
        stars = s.group(1) if s else "?"
        t = re.search(r"([\d,]+) stars today", row)
        today_stars = t.group(1) if t else "?"
        lang = re.search(r'itemprop="programmingLanguage">([^<]+)<', row)
        out.append({"name": name, "desc": desc, "stars": stars,
                    "today": today_stars,
                    "lang": lang.group(1) if lang else ""})
        if len(out) >= 8:
            break
    if not out:
        raise RuntimeError("Trending 解析为空")
    return out, "GitHub Trending"


# ---------------- 渲染 ----------------

def render_edition(date_str, weekday, domestic, domestic_src, tech, tech_src,
                   trending, trending_src, tip):
    lines = [f"# 每日科技早报 · {date_str} {weekday}", ""]
    lines.append("## 📰 国内要闻")
    lines.append("")
    if domestic:
        for i, n in enumerate(domestic, 1):
            lines.append(f"{i}. {n}")
    else:
        lines.append("（今日该栏目数据源暂时不可用，未能抓取，不是没有新闻。）")
    lines.append("")
    lines.append(f"<sub>来源：{domestic_src}</sub>")
    lines.append("")
    lines.append("## 💻 科技动态")
    lines.append("")
    if tech:
        for i, t in enumerate(tech, 1):
            lines.append(f"{i}. [{t['title']}]({t['link']})" if t["link"]
                         else f"{i}. {t['title']}")
    else:
        lines.append("（今日该栏目数据源暂时不可用，未能抓取。）")
    lines.append("")
    lines.append(f"<sub>来源：{tech_src}</sub>")
    lines.append("")
    lines.append("## 🔥 GitHub 今日热门")
    lines.append("")
    if trending:
        for i, r in enumerate(trending, 1):
            meta = f"⭐ {r['stars']}（今日 +{r['today']}）"
            if r["lang"]:
                meta += f" · {r['lang']}"
            lines.append(f"{i}. **[{r['name']}](https://github.com/{r['name']})** — {meta}")
            if r["desc"]:
                lines.append(f"   {r['desc']}")
    else:
        lines.append("（今日该栏目数据源暂时不可用，未能抓取。）")
    lines.append("")
    lines.append(f"<sub>来源：{trending_src}</sub>")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"☀️ {tip if tip else '新的一天，先看要闻，再写代码。'}")
    lines.append("")
    return "\n".join(lines)


def update_readme(edition_md, date_str):
    history = sorted((f for f in os.listdir(EDITIONS_DIR) if f.endswith(".md")),
                     reverse=True)
    parts = [
        "# 每日科技早报 ☀️",
        "",
        "每天早上一份：国内要闻 + 科技动态 + GitHub 今日热门，自动抓取、自动生成，适合转发。",
        "",
        "![今日早报图](poster.png)",
        "",
        "---",
        "",
        edition_md.strip(),
        "",
        "---",
        "",
        "## 📚 历史存档",
        "",
    ]
    for f in history:
        d = f[:-3]
        parts.append(f"- [{d}](editions/{f})")
    parts.append("")
    parts.append("<sub>数据来源：60 秒读懂世界、IT之家、GitHub Trending；每日自动更新。</sub>")
    parts.append("")
    with open(os.path.join(ROOT, "README.md"), "w", encoding="utf-8") as fh:
        fh.write("\n".join(parts))


# ---------------- 早报图 ----------------

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
]
FONT_BOLD_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
]


def _font(paths, size):
    from PIL import ImageFont
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return None


def make_poster(date_str, weekday, domestic, tech, trending, tip):
    from PIL import Image, ImageDraw
    f_title = _font(FONT_BOLD_CANDIDATES, 64)
    f_h = _font(FONT_BOLD_CANDIDATES, 34)
    f_body = _font(FONT_CANDIDATES, 27)
    f_small = _font(FONT_CANDIDATES, 23)
    if not (f_title and f_h and f_body):
        raise RuntimeError("未找到可用的中文字体")

    W, MARGIN = 1080, 56
    max_w = W - MARGIN * 2
    tmp = ImageDraw.Draw(Image.new("RGB", (W, 10)))

    def wrap(text, font, limit_w):
        out, cur = [], ""
        for ch in text:
            if tmp.textlength(cur + ch, font=font) <= limit_w:
                cur += ch
            else:
                out.append(cur)
                cur = ch
        if cur:
            out.append(cur)
        return out or [""]

    blocks = []  # (kind, text, font, color, space_after)
    blocks.append(("title", "每日科技早报", f_title, (255, 255, 255), 6))
    blocks.append(("sub", f"{date_str} {weekday}", f_h, (179, 207, 255), 26))
    blocks.append(("h", "● 国内要闻", f_h, (255, 196, 66), 10))
    if domestic:
        for i, n in enumerate(domestic[:10], 1):
            for j, seg in enumerate(wrap(f"{i}. {n}", f_body, max_w)):
                blocks.append(("b", seg, f_body, (235, 238, 245), 4 if j else 2))
    else:
        blocks.append(("b", "（数据源暂时不可用）", f_body, (235, 238, 245), 4))
    blocks.append(("gap", "", f_body, None, 14))
    blocks.append(("h", "● 科技动态", f_h, (102, 217, 178), 10))
    if tech:
        for i, t in enumerate(tech[:6], 1):
            for j, seg in enumerate(wrap(f"{i}. {t['title']}", f_body, max_w)):
                blocks.append(("b", seg, f_body, (235, 238, 245), 4 if j else 2))
    else:
        blocks.append(("b", "（数据源暂时不可用）", f_body, (235, 238, 245), 4))
    blocks.append(("gap", "", f_body, None, 14))
    blocks.append(("h", "● GitHub 今日热门", f_h, (255, 138, 128), 10))
    if trending:
        for i, r in enumerate(trending[:8], 1):
            line = f"{i}. {r['name']}  ★{r['stars']}（+{r['today']}）"
            for j, seg in enumerate(wrap(line, f_body, max_w)):
                blocks.append(("b", seg, f_body, (235, 238, 245), 4 if j else 2))
    else:
        blocks.append(("b", "（数据源暂时不可用）", f_body, (235, 238, 245), 4))
    blocks.append(("gap", "", f_body, None, 18))
    blocks.append(("tip", f"☀ {tip if tip else '新的一天，先看要闻，再写代码。'}",
                   f_small, (179, 207, 255), 0))

    def line_h(font):
        a, d = font.getmetrics()
        return a + d + 6

    H = 64 + sum(line_h(f) + s for (_k, _t, f, _c, s) in blocks) + 48
    img = Image.new("RGB", (W, H), (18, 24, 43))
    dr = ImageDraw.Draw(img)
    dr.rectangle([0, 0, W, 10], fill=(255, 196, 66))
    y = 54
    for _kind, text, font, color, space in blocks:
        if text:
            dr.text((MARGIN, y), text, font=font, fill=color)
        y += line_h(font) + space
    img.save(os.path.join(ROOT, "poster.png"))
    return os.path.join(ROOT, "poster.png")


# ---------------- 主流程 ----------------

def main():
    if len(sys.argv) > 1:
        day = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
    else:
        day = datetime.now(CST).date()
    date_str = day.isoformat()
    weekday = WEEKDAYS[day.weekday()]
    report = {}

    try:
        domestic, domestic_src, tip = fetch_domestic()
    except Exception as e:
        domestic, domestic_src, tip = [], "60 秒读懂世界（抓取失败）", None
        report["domestic_error"] = str(e)
    report["domestic"] = len(domestic)

    try:
        tech, tech_src = fetch_tech(day)
    except Exception as e:
        tech, tech_src = [], "IT之家（抓取失败）"
        report["tech_error"] = str(e)
    report["tech"] = len(tech)

    try:
        trending, trending_src = fetch_trending()
    except Exception as e:
        trending, trending_src = [], "GitHub Trending（抓取失败）"
        report["trending_error"] = str(e)
    report["trending"] = len(trending)

    edition_md = render_edition(date_str, weekday, domestic, domestic_src,
                                tech, tech_src, trending, trending_src, tip)
    os.makedirs(EDITIONS_DIR, exist_ok=True)
    path = os.path.join(EDITIONS_DIR, f"{date_str}.md")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(edition_md)
    update_readme(edition_md, date_str)

    try:
        make_poster(date_str, weekday, domestic, tech, trending, tip)
        report["poster"] = "ok"
    except Exception as e:
        report["poster"] = f"failed: {e}"

    report["edition"] = path
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
