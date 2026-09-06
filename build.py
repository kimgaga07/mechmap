# -*- coding: utf-8 -*-
"""
mechmap 정적 사이트 빌더
  docs/*.md, experiments/*.md  ->  site/*.html

사용법:  python build.py
"""

import re, os, sys, shutil, html, json, threading, webbrowser
from pathlib import Path
import markdown, yaml

ROOT = Path(__file__).parent
OUT = ROOT / "site"
SITE_NAME = "테크토닉"                  # 사이트 · 팀 이름
GITHUB_REPO = "kimgaga07/mechmap"       # 저장소 바뀌면 여기만 바꾸면 됨

# 과목 색 (순서대로 배정)
SUBJECT_COLORS = ["#c2410c", "#1d4ed8", "#15803d", "#7c3aed", "#b91c1c", "#0e7490"]

# 도구 색
TOOL_COLORS = {"MATLAB": "#1d4ed8", "Inventor": "#c2740c"}

CODE_LANG = {"m": "matlab", "py": "python", "js": "javascript", "txt": "text"}

CALLOUT_LABEL = {
    "question": "여기서 막힌다",
    "example": "숫자로 보기",
    "warning": "흔한 오해",
    "note": "메모",
    "tip": "팁",
    "danger": "주의",
}


# ---------------------------------------------------------------- 파일 읽기
def split_front(text):
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            raw = text[3:end]
            body = text[end + 4:]
            try:
                return yaml.safe_load(raw) or {}, body
            except Exception:
                return {}, body
    return {}, text


def collect():
    pages = []
    for folder, kind in (("docs", "doc"), ("experiments", "experiment")):
        d = ROOT / folder
        if not d.exists():
            continue
        for f in sorted(d.glob("*.md")):
            meta, body = split_front(f.read_text(encoding="utf-8"))
            pages.append({
                "stem": f.stem,
                "kind": kind,
                "meta": meta,
                "body": body,
                "url": f"{f.stem}.html",
                "title": meta.get("title") or f.stem,
                "subject": meta.get("subject") or "기타",
                "links": [],
            })
    return pages


# ---------------------------------------------------------------- 전처리
MATH_STORE = []


def protect_math(text):
    """python-markdown 이 \\x02 를 내부 placeholder 로 쓰므로 평범한 토큰을 쓴다"""
    MATH_STORE.clear()

    def keep(m):
        MATH_STORE.append(m.group(0))
        return f"zqmathzq{len(MATH_STORE)-1}zqzq"

    text = re.sub(r"\$\$.+?\$\$", keep, text, flags=re.S)
    text = re.sub(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", keep, text)
    return text


def restore_math(text):
    def put(m):
        return MATH_STORE[int(m.group(1))]
    return re.sub(r"zqmathzq(\d+)zqzq", put, text)


def convert_callouts(text):
    """> [!type] 제목  블록을 div 로 바꾼다"""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        m = re.match(r"^>\s*\[!(\w+)\]\s*(.*)$", lines[i])
        if not m:
            out.append(lines[i]); i += 1; continue
        ctype = m.group(1).lower()
        label = m.group(2).strip() or CALLOUT_LABEL.get(ctype, ctype)
        i += 1
        inner = []
        while i < len(lines) and lines[i].startswith(">"):
            inner.append(re.sub(r"^>\s?", "", lines[i])); i += 1
        out.append(f'<div class="callout callout-{ctype}" markdown="1">')
        out.append(f'<div class="callout-title">{html.escape(label)}</div>')
        out.append("")
        out.extend(inner)
        out.append("")
        out.append("</div>")
    return "\n".join(out)


def convert_embeds(text):
    """![[img.jpg|520]] -> figure. 바로 다음 줄이 *캡션* 이면 같이 묶는다"""
    lines = text.split("\n")
    out, i = [], 0
    while i < len(lines):
        m = re.match(r"^!\[\[([^\]|]+?)(?:\|(\d+))?\]\]\s*$", lines[i])
        if not m:
            out.append(lines[i]); i += 1; continue
        name, width = m.group(1).strip(), m.group(2)
        cap = ""
        if i + 1 < len(lines):
            c = re.match(r"^\*(.+)\*\s*$", lines[i + 1].strip())
            if c:
                cap = c.group(1); i += 1
        # 코드 파일이면 내용을 그대로 박스로 넣는다
        ext = name.rsplit(".", 1)[-1].lower()
        if ext in CODE_LANG:
            f = ROOT / "assets" / name
            if f.exists():
                src_code = f.read_text(encoding="utf-8").rstrip()
                out.append(f'<div class="codebox"><div class="codebox-name">{html.escape(name)}</div>')
                out.append("")
                out.append(f"```{CODE_LANG[ext]}")
                out.extend(src_code.splitlines())
                out.append("```")
                out.append("")
                out.append("</div>")
            else:
                out.append(f'<div class="img-missing">코드 자리 &nbsp;·&nbsp; '
                           f'<code>assets/{html.escape(name)}</code></div>')
            i += 1
            continue

        w = f' style="max-width:{width}px"' if width else ""
        src = f"assets/{name}"
        exists = (ROOT / "assets" / name).exists()
        if exists:
            body = f'<img src="{src}" alt="{html.escape(cap or name)}"{w}>'
        else:
            body = (f'<div class="img-missing"{w}>그림 자리 &nbsp;·&nbsp; '
                    f'<code>assets/{html.escape(name)}</code></div>')
        figcap = f'<figcaption>{html.escape(cap)}</figcaption>' if cap else ""
        out.append(f'<figure>{body}{figcap}</figure>')
        i += 1
    return "\n".join(out)


def convert_links(text, index, page):
    """[[문서]] [[문서|별칭]] [[문서#절]]"""
    def rep(m):
        raw = m.group(1)
        alias = None
        if "|" in raw:
            raw, alias = raw.split("|", 1)
        anchor = ""
        if "#" in raw:
            raw, sec = raw.split("#", 1)
            anchor = "#" + slug(sec)
        target = index.get(raw.strip())
        label = alias if alias is not None else raw.strip()
        if not target:
            return f'<span class="link-missing" title="아직 없는 문서">{html.escape(label)}</span>'
        page["links"].append(target["stem"])
        cls = "wlink"
        if target["kind"] == "experiment":
            cls = "wlink taglink"
            label = "#" + label
        return f'<a class="{cls}" href="{target["url"]}{anchor}">{html.escape(label)}</a>'

    return re.sub(r"\[\[([^\]]+)\]\]", rep, text)


def slug(s):
    s = re.sub(r"[^\w가-힣\- ]", "", s).strip().replace(" ", "-")
    return s.lower()


# ---------------------------------------------------------------- 렌더
MD = markdown.Markdown(extensions=["tables", "fenced_code", "md_in_html",
                                   "attr_list", "sane_lists"])


def fix_tables(htmltext):
    """빈 헤더 행 제거 + 가로 스크롤 래퍼"""
    def strip_empty_head(m):
        head = m.group(0)
        if not re.search(r"<th[^>]*>\s*[^<\s]", head):
            return ""
        return head
    htmltext = re.sub(r"<thead>.*?</thead>", strip_empty_head, htmltext, flags=re.S)
    htmltext = re.sub(r"<table>(.*?)</table>",
                      lambda m: f'<div class="tw"><table>{m.group(1)}</table></div>',
                      htmltext, flags=re.S)
    return htmltext


def add_heading_ids(htmltext):
    def rep(m):
        lvl, inner = m.group(1), m.group(2)
        plain = re.sub(r"<[^>]+>", "", inner)
        return f'<h{lvl} id="{slug(plain)}">{inner}</h{lvl}>'
    return re.sub(r"<h([23])>(.*?)</h\1>", rep, htmltext, flags=re.S)


def render_body(page, index):
    t = page["body"]
    # 문서 제목은 머리말에서 이미 보여주므로 본문 첫 H1 은 지운다
    t = re.sub(r"^\s*#\s+.*?$", "", t, count=1, flags=re.M)
    t = protect_math(t)
    t = convert_callouts(t)
    t = convert_embeds(t)
    t = convert_links(t, index, page)
    MD.reset()
    t = MD.convert(t)
    t = restore_math(t)
    t = fix_tables(t)
    t = add_heading_ids(t)
    return t


# ---------------------------------------------------------------- 사이드바
def build_sidebar(pages, subj_color, current=None):
    docs = [p for p in pages if p["kind"] == "doc"]
    exps = [p for p in pages if p["kind"] == "experiment"]

    parts = []
    by_subject = {}
    for p in docs:
        by_subject.setdefault(p["subject"], []).append(p)

    for subj, items in by_subject.items():
        items.sort(key=lambda x: (x["meta"].get("chapter") or 99, x["title"]))
        c = subj_color[subj]
        parts.append(f'<div class="nav-group">')
        parts.append(f'<div class="nav-head"><span class="dot" style="background:{c}"></span>'
                     f'{html.escape(subj)}<span class="cnt">{len(items)}</span></div>')
        parts.append('<ul>')
        for p in items:
            ch = p["meta"].get("chapter")
            num = f'<span class="ch">{ch}장</span>' if ch else ""
            act = ' class="active"' if current == p["stem"] else ""
            parts.append(f'<li><a href="{p["url"]}"{act}>{num}{html.escape(p["title"])}</a></li>')
        parts.append('</ul></div>')

    if exps:
        groups = {"MATLAB": [], "Inventor": [], "이론-FEM 검증": []}
        for p in exps:
            tools = p["meta"].get("tools") or []
            if "MATLAB" in tools and "Inventor" in tools:
                groups["이론-FEM 검증"].append(p)
            elif "Inventor" in tools:
                groups["Inventor"].append(p)
            else:
                groups["MATLAB"].append(p)
        parts.append('<div class="nav-sep"></div>')
        parts.append(f'<div class="nav-group"><div class="nav-head">실험'
                     f'<span class="cnt">{len(exps)}</span></div>')
        for gname, items in groups.items():
            if not items:
                continue
            parts.append(f'<div class="nav-sub">{gname} <span class="cnt">{len(items)}</span></div>')
            parts.append('<ul>')
            for p in items:
                act = ' class="active"' if current == p["stem"] else ""
                parts.append(f'<li><a href="{p["url"]}"{act}>{html.escape(p["title"])}</a></li>')
            parts.append('</ul>')
        parts.append('</div>')

    parts.append('<div class="nav-sep"></div>')
    parts.append('<div class="nav-group"><ul>'
                 '<li><a class="soon">개념 지도 <span class="soon-tag">준비중</span></a></li>'
                 '<li><a class="soon">주차별 성장 <span class="soon-tag">준비중</span></a></li>'
                 '</ul></div>')
    return "\n".join(parts)


# ---------------------------------------------------------------- 템플릿
def page_html(page, pages, subj_color, backlinks):
    meta = page["meta"]
    subj = page["subject"]
    c = subj_color[subj]

    # 선수 항목은 화면에 표시하지 않는다 (prereq 는 나중에 개념 지도에서 사용)
    pre_html = ""

    # 태그는 화면에 표시하지 않는다 (tools 는 사이드바 분류에 사용)
    tag_html = ""

    byline = []
    if meta.get("author"):
        byline.append(html.escape(str(meta["author"])))
    if meta.get("week"):
        byline.append(f'{meta["week"]}주차')
    byline_html = f'<div class="byline">{" · ".join(byline)}</div>' if byline else ""

    # 코드 실행 버튼 (제목 바로 아래)
    code_file = meta.get("code")
    act_html = ""
    if code_file:
        ml = (f"https://matlab.mathworks.com/open/github/v1?repo={GITHUB_REPO}"
              f"&file=assets/{code_file}")
        act_html = (
            '<div class="actions">'
            f'<a class="act act-run" href="{ml}" target="_blank" rel="noopener">'
            'MATLAB Online 에서 열기</a>'
            f'<a class="act" href="assets/{html.escape(str(code_file))}" download>'
            f'{html.escape(str(code_file))} 받기</a>'
            '</div>')

    kind_label = "실험" if page["kind"] == "experiment" else html.escape(subj)

    # 백링크
    bl_html = ""   # 백링크 표시하지 않음

    body = render_body(page, INDEX)
    sidebar = build_sidebar(pages, subj_color, current=page["stem"])

    return TEMPLATE.format(
        title=html.escape(page["title"]),
        site=html.escape(SITE_NAME),
        sidebar=sidebar,
        kind=kind_label,
        subj_color=c,
        pagetitle=html.escape(page["title"]),
        meta_pre=pre_html,
        meta_tag=tag_html,
        byline=byline_html + act_html,
        body=body,
        backlinks=bl_html,
    )


TEMPLATE = """<!doctype html>
<html lang="ko" data-theme="light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} · {site}</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable.min.css">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css">
<link rel="stylesheet" href="style.css">
</head>
<body>

<header class="topbar">
  <button id="navToggle" class="icon-btn" title="사이드바 (Ctrl+B)" aria-label="사이드바 열기/닫기">
    <span></span><span></span><span></span>
  </button>
  <a class="brand" href="index.html">{site}</a>
  <div class="spacer"></div>
  <button id="linkToggle" class="pill" title="본문 링크 밑줄 표시">링크 표시</button>
  <button id="themeToggle" class="icon-btn" title="밝게 / 어둡게">◐</button>
</header>

<div class="layout">
  <nav id="sidebar" class="sidebar">{sidebar}</nav>
  <main class="main">
    <article class="doc">
      <div class="kicker" style="color:{subj_color}">{kind}</div>
      <h1>{pagetitle}</h1>
      {meta_pre}
      {meta_tag}
      {byline}
      <div class="content">
      {body}
      </div>
      {backlinks}
      <div class="feedback">
        <div class="fb-q">이 문서, 어떠셨나요?</div>
        <div class="fb-btns">
          <button class="fb ok">이해됐어요</button>
          <button class="fb hard">어려웠어요</button>
        </div>
        <div class="fb-more" hidden>
          <div class="fb-sub">어떤 점이 어려웠나요? <span class="opt">안 고르고 보내도 됩니다</span></div>
          <div class="fb-chips">
            <button class="chip-btn">설명이 부족</button>
            <button class="chip-btn">너무 길다</button>
            <button class="chip-btn">배경지식이 없다</button>
            <button class="chip-btn">기타</button>
          </div>
          <textarea placeholder="한마디 (선택)"></textarea>
          <div class="fb-send">
            <button class="ghost">그냥 보내기</button>
            <button class="solid">보내기</button>
          </div>
        </div>
        <div class="fb-done" hidden>고맙습니다.</div>
      </div>
    </article>
  </main>
</div>

<button id="toTop" class="to-top" title="맨 위로">↑</button>

<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.js"></script>
<script src="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/contrib/auto-render.min.js"></script>
<script src="app.js"></script>
</body>
</html>
"""


# ---------------------------------------------------------------- CSS / JS
CSS = """
:root{
  --bg:#ffffff; --fg:#1c1a18; --dim:#6b6560; --line:#e6e2dd;
  --panel:#faf8f6; --accent:#1d4ed8; --code:#f3f0ec;
  --ok:#15803d; --warn:#b45309; --danger:#b91c1c;
  --sidebar-w:262px;
}
:root[data-theme="dark"]{
  --bg:#16181c; --fg:#e8e6e3; --dim:#9a948d; --line:#2c2f36;
  --panel:#1c1f24; --accent:#7aa2ff; --code:#22262c;
  --ok:#4ade80; --warn:#fbbf24; --danger:#f87171;
}
*{box-sizing:border-box}
html,body{margin:0;padding:0}
body{
  background:var(--bg); color:var(--fg);
  font-family:"Pretendard Variable",Pretendard,"Malgun Gothic","맑은 고딕",
              -apple-system,system-ui,sans-serif;
  font-size:16.5px; line-height:1.78;
  -webkit-font-smoothing:antialiased;
}
a{color:var(--accent); text-decoration:none}
code,pre,kbd{font-family:"D2Coding",Consolas,"Courier New",monospace}

/* ---------- 상단바 ---------- */
.topbar{
  position:sticky; top:0; z-index:50;
  display:flex; align-items:center; gap:12px;
  height:52px; padding:0 14px;
  background:var(--bg); border-bottom:1px solid var(--line);
}
.spacer{flex:1}
.brand{
  font-weight:700; font-size:15.5px; color:var(--fg);
  letter-spacing:-.01em; white-space:nowrap;
}
.icon-btn{
  width:34px; height:34px; display:grid; place-items:center; gap:3px;
  background:none; border:1px solid transparent; border-radius:8px;
  color:var(--fg); cursor:pointer; font-size:15px; padding:0;
}
.icon-btn:hover{background:var(--panel); border-color:var(--line)}
#navToggle{gap:1.5px}
#navToggle span{
  display:block; width:15px; height:1.5px; background:var(--fg);
  border-radius:2px; grid-column:1;
}
.pill{
  height:30px; padding:0 12px; font-size:13px;
  background:none; color:var(--dim);
  border:1px solid var(--line); border-radius:99px; cursor:pointer;
  font-family:inherit;
}
.pill.on{background:var(--accent); border-color:var(--accent); color:#fff}

/* ---------- 레이아웃 ---------- */
.layout{display:flex; align-items:flex-start}
.sidebar{
  width:var(--sidebar-w); flex:0 0 var(--sidebar-w);
  position:sticky; top:52px; height:calc(100vh - 52px);
  overflow-y:auto; padding:18px 10px 60px 16px;
  border-right:1px solid var(--line); background:var(--bg);
  font-size:14px;
}
body.nav-closed .sidebar{display:none}
.main{flex:1; min-width:0; display:flex; justify-content:center}
.doc{width:100%; max-width:760px; padding:34px 26px 120px}

/* ---------- 사이드바 ---------- */
.nav-group{margin-bottom:14px}
.nav-head{
  display:flex; align-items:center; gap:7px;
  font-weight:600; color:var(--fg); padding:4px 6px; font-size:14px;
}
.nav-sub{
  font-size:12.5px; color:var(--dim); padding:6px 6px 2px 6px;
}
.dot{width:8px; height:8px; border-radius:99px; display:inline-block}
.cnt{margin-left:auto; color:var(--dim); font-size:12.5px; font-weight:400}
.sidebar ul{list-style:none; margin:2px 0 0; padding:0}
.sidebar li a{
  display:block; padding:5px 8px 5px 20px; border-radius:7px;
  color:var(--dim); font-size:13.8px; line-height:1.45;
}
.sidebar li a:hover{background:var(--panel); color:var(--fg)}
.sidebar li a.active{background:var(--panel); color:var(--fg); font-weight:600}
.ch{color:var(--dim); margin-right:7px; font-size:12.5px}
.nav-sep{height:1px; background:var(--line); margin:14px 6px}
.soon{cursor:default; opacity:.55}
.soon:hover{background:none !important}
.soon-tag{font-size:11px; color:var(--dim); border:1px solid var(--line);
  border-radius:4px; padding:0 4px; margin-left:5px}

/* ---------- 문서 머리 ---------- */
.kicker{font-size:13px; font-weight:600; letter-spacing:.02em; margin-bottom:6px}
.doc h1{
  font-size:33px; line-height:1.3; margin:0 0 16px;
  letter-spacing:-.022em; text-wrap:balance;
}
.meta-row{display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin-bottom:7px}
.meta-key{font-size:12.5px; color:var(--dim); margin-right:4px}
.chip{
  font-size:12.5px; color:var(--dim);
  border:1px solid var(--line); border-radius:99px; padding:1.5px 9px;
}
.chip.tool{color:var(--c); border-color:color-mix(in srgb,var(--c) 40%,transparent)}
.byline{color:var(--dim); font-size:13px; margin:12px 0 0}
.doc h1 + .meta-row{margin-top:2px}

.actions{display:flex; flex-wrap:wrap; gap:8px; margin-top:16px}
.act{
  display:inline-block; padding:7px 14px; font-size:13.5px;
  border:1px solid var(--line); border-radius:8px; color:var(--dim);
}
.act:hover{border-color:var(--accent); color:var(--accent)}
.act-run{
  border-color:color-mix(in srgb,#1d4ed8 45%,transparent); color:#1d4ed8;
}
:root[data-theme="dark"] .act-run{
  border-color:color-mix(in srgb,#7aa2ff 45%,transparent); color:#7aa2ff;
}

.codebox{
  border:1px solid var(--line); border-radius:10px; overflow:hidden;
  margin:0 0 20px;
}
.codebox-name{
  padding:8px 14px; font-size:12.5px; color:var(--dim);
  background:var(--panel); border-bottom:1px solid var(--line);
  font-family:"D2Coding",Consolas,monospace;
}
.codebox pre{border:0; border-radius:0; margin:0; max-height:520px}

/* ---------- 본문 ---------- */
.content{margin-top:30px}
.content h2{
  font-size:21px; margin:44px 0 14px; padding-bottom:8px;
  border-bottom:1px solid var(--line); letter-spacing:-.015em;
}
.content h3{font-size:17px; margin:30px 0 10px}
.content p{margin:0 0 16px}
.content ul,.content ol{margin:0 0 16px; padding-left:22px}
.content li{margin:5px 0}
.content strong{font-weight:700}
.content hr{border:0; border-top:1px solid var(--line); margin:36px 0}

.tw{overflow-x:auto; margin:0 0 18px}
.content table{
  border-collapse:collapse; width:100%; font-size:15px;
}
.content th,.content td{
  border:1px solid var(--line); padding:8px 12px; text-align:left;
  vertical-align:top;
}
.content th{background:var(--panel); font-weight:600}

.content pre{
  background:var(--code); border:1px solid var(--line); border-radius:9px;
  padding:14px 16px; overflow-x:auto; font-size:14px; line-height:1.6;
}
.content :not(pre) > code{
  background:var(--code); border-radius:5px; padding:1.5px 5px; font-size:.9em;
}

figure{margin:22px 0; text-align:center}
figure img{
  max-width:100%; height:auto; border:1px solid var(--line); border-radius:9px;
}
figcaption{
  margin-top:9px; font-size:13.5px; color:var(--dim); line-height:1.6;
}
.img-missing{
  border:1.5px dashed var(--line); border-radius:9px; padding:34px 18px;
  color:var(--dim); font-size:13.5px; background:var(--panel);
  margin:0 auto;
}
.img-missing code{background:none; color:var(--dim)}

/* ---------- 링크 ---------- */
.wlink{
  color:inherit; text-decoration:none;
  border-bottom:1px solid transparent;
}
.wlink:hover{border-bottom-color:var(--accent); color:var(--accent)}
body.show-links .wlink{
  border-bottom:1px dotted var(--accent); color:var(--accent);
}
.taglink{
  color:var(--accent); font-size:.95em;
  background:color-mix(in srgb,var(--accent) 9%,transparent);
  border-radius:6px; padding:1px 7px; white-space:nowrap;
}
body.show-links .taglink{border-bottom:none}
.link-missing{color:var(--dim); border-bottom:1px dotted var(--dim)}

/* ---------- 콜아웃 ---------- */
.callout{
  border:1px solid var(--line); border-left:3px solid var(--dim);
  background:var(--panel); border-radius:9px;
  padding:16px 18px 4px; margin:24px 0;
}
.callout-title{
  font-weight:700; font-size:14.5px; margin-bottom:10px;
  letter-spacing:-.01em;
}
.callout p{margin:0 0 12px}
.callout table{margin-bottom:12px; font-size:14.5px}
.callout-question{border-left-color:var(--accent)}
.callout-question .callout-title{color:var(--accent)}
.callout-example{border-left-color:var(--ok)}
.callout-example .callout-title{color:var(--ok)}
.callout-warning{border-left-color:var(--warn)}
.callout-warning .callout-title{color:var(--warn)}
.callout-danger{border-left-color:var(--danger)}
.callout-danger .callout-title{color:var(--danger)}

/* ---------- 백링크 / 피드백 ---------- */
.backlinks{
  margin-top:54px; padding-top:18px; border-top:1px solid var(--line);
  font-size:14px;
}
.bl-head{color:var(--dim); font-size:12.5px; margin-bottom:6px}
.feedback{
  margin-top:34px; padding:22px; border:1px solid var(--line);
  border-radius:12px; background:var(--panel);
}
.fb-q{font-size:14.5px; margin-bottom:14px}
.fb-btns{display:flex; gap:10px; flex-wrap:wrap}
.fb{
  padding:9px 20px; font-size:14px; font-family:inherit; cursor:pointer;
  border:1px solid var(--line); border-radius:9px;
  background:var(--bg); color:var(--fg);
}
.fb:hover{border-color:var(--accent); color:var(--accent)}
.fb-more{margin-top:18px}
.fb-sub{font-size:13.5px; color:var(--dim); margin-bottom:10px}
.opt{font-size:12.5px; opacity:.75}
.fb-chips{display:flex; gap:7px; flex-wrap:wrap; margin-bottom:12px}
.chip-btn{
  font-size:13px; padding:5px 12px; cursor:pointer; font-family:inherit;
  border:1px solid var(--line); border-radius:99px;
  background:var(--bg); color:var(--dim);
}
.chip-btn.on{border-color:var(--accent); color:var(--accent)}
.fb-more textarea{
  width:100%; min-height:64px; padding:10px 12px; font-family:inherit;
  font-size:14px; border:1px solid var(--line); border-radius:9px;
  background:var(--bg); color:var(--fg); resize:vertical;
}
.fb-send{display:flex; gap:9px; justify-content:flex-end; margin-top:10px}
.ghost,.solid{
  padding:8px 16px; font-size:13.5px; border-radius:8px; cursor:pointer;
  font-family:inherit; border:1px solid var(--line);
}
.ghost{background:none; color:var(--dim)}
.solid{background:var(--accent); border-color:var(--accent); color:#fff}
.fb-done{font-size:14.5px; color:var(--ok)}

/* ---------- 문단 표시 (모르겠어요) ---------- */
.blk{position:relative}
.flag{
  position:absolute; left:-30px; top:5px;
  width:22px; height:22px; padding:0; line-height:1;
  border:1px solid transparent; border-radius:7px;
  background:none; color:var(--dim); cursor:pointer;
  font-family:inherit; font-size:13px; opacity:0;
  transition:opacity .12s;
}
.blk:hover .flag{opacity:.45}
.flag:hover{opacity:1 !important; background:var(--panel); border-color:var(--line)}
.blk.flagged{
  box-shadow:-14px 0 0 -12px var(--warn);
}
.blk.flagged .flag{
  opacity:1; color:var(--warn); border-color:var(--warn);
  background:var(--bg);
}
.flag-box{
  margin:-4px 0 20px; padding:14px 16px;
  border:1px solid var(--line); border-left:3px solid var(--warn);
  border-radius:9px; background:var(--panel);
}
.flag-box .fb-lab{font-size:13.5px; color:var(--fg); margin-bottom:9px}
.flag-box .fb-lab .opt{margin-left:8px; font-size:12.5px; color:var(--dim)}
.flag-box .fb-lab.done{color:var(--ok); margin:0}
.flag-box textarea{
  width:100%; padding:9px 11px; font-family:inherit; font-size:14px;
  border:1px solid var(--line); border-radius:8px;
  background:var(--bg); color:var(--fg); resize:vertical; line-height:1.6;
}
.flag-act{display:flex; gap:8px; justify-content:flex-end; margin-top:9px}

@media (max-width:1100px){
  .flag{left:auto; right:-4px; top:-2px}
  .blk.flagged{box-shadow:none; background:color-mix(in srgb,var(--warn) 7%,transparent);
    border-radius:7px}
}

/* ---------- 맨 위로 ---------- */
.to-top{
  position:fixed; right:22px; bottom:22px; width:40px; height:40px;
  border-radius:99px; border:1px solid var(--line); background:var(--bg);
  color:var(--fg); cursor:pointer; font-size:17px; opacity:0;
  transition:opacity .18s; pointer-events:none;
}
.to-top.on{opacity:1; pointer-events:auto}

/* ---------- 수식 ---------- */
.katex-display{overflow-x:auto; overflow-y:hidden; padding:4px 0; margin:20px 0}

/* ---------- 좁은 화면 ---------- */
@media (max-width:900px){
  .sidebar{
    position:fixed; left:0; top:52px; z-index:40;
    box-shadow:0 10px 30px rgba(0,0,0,.14);
  }
  body:not(.nav-open) .sidebar{display:none}
  .doc{padding:26px 18px 100px}
  .doc h1{font-size:27px}
}
"""

JS = """
(function(){
  var body = document.body;

  /* 사이드바 */
  var wide = window.matchMedia('(min-width:901px)');
  var navBtn = document.getElementById('navToggle');
  function setNav(open, remember){
    if(wide.matches){ body.classList.toggle('nav-closed', !open); }
    else { body.classList.toggle('nav-open', open); }
    /* 화면이 좁아서 강제로 닫힌 건 기억하지 않는다 */
    if(remember && wide.matches){ localStorage.setItem('nav', open ? '1':'0'); }
  }
  setNav(wide.matches ? localStorage.getItem('nav') !== '0' : false, false);
  wide.addEventListener('change', function(){
    setNav(wide.matches ? localStorage.getItem('nav') !== '0' : false, false);
  });
  navBtn.addEventListener('click', function(){
    var open = wide.matches ? !body.classList.contains('nav-closed')
                            : body.classList.contains('nav-open');
    setNav(!open, true);
  });

  /* 링크 표시 토글 */
  var linkBtn = document.getElementById('linkToggle');
  function setLinks(on){
    body.classList.toggle('show-links', on);
    linkBtn.classList.toggle('on', on);
    localStorage.setItem('links', on ? '1' : '0');
  }
  setLinks(localStorage.getItem('links') !== '0');   /* 기본 켜짐 */
  linkBtn.addEventListener('click', function(){
    setLinks(!body.classList.contains('show-links'));
  });

  /* 다크모드 */
  var root = document.documentElement;
  var themeBtn = document.getElementById('themeToggle');
  var saved = localStorage.getItem('theme');
  if(!saved){
    saved = window.matchMedia('(prefers-color-scheme:dark)').matches ? 'dark':'light';
  }
  root.setAttribute('data-theme', saved);
  themeBtn.addEventListener('click', function(){
    var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    root.setAttribute('data-theme', next);
    localStorage.setItem('theme', next);
  });

  /* 맨 위로 */
  var top = document.getElementById('toTop');
  window.addEventListener('scroll', function(){
    top.classList.toggle('on', window.scrollY > 500);
  });
  top.addEventListener('click', function(){
    window.scrollTo({top:0, behavior:'smooth'});
  });

  /* 피드백 (지금은 화면만) */
  var fb = document.querySelector('.feedback');
  if(fb){
    var more = fb.querySelector('.fb-more');
    var done = fb.querySelector('.fb-done');
    var btns = fb.querySelector('.fb-btns');
    fb.querySelector('.fb.ok').addEventListener('click', function(){
      btns.hidden = true; fb.querySelector('.fb-q').hidden = true; done.hidden = false;
    });
    fb.querySelector('.fb.hard').addEventListener('click', function(){
      more.hidden = false; btns.hidden = true;
    });
    fb.querySelectorAll('.chip-btn').forEach(function(c){
      c.addEventListener('click', function(){ c.classList.toggle('on'); });
    });
    fb.querySelectorAll('.fb-send button').forEach(function(b){
      b.addEventListener('click', function(){
        more.hidden = true; fb.querySelector('.fb-q').hidden = true; done.hidden = false;
      });
    });
  }

  /* 문단마다 "모르겠어요" 표시 버튼 */
  var page = location.pathname;
  var marked = JSON.parse(localStorage.getItem('flag:'+page) || '[]');
  var blocks = document.querySelectorAll('.content > p, .content > ul, .content > ol');
  Array.prototype.forEach.call(blocks, function(el, i){
    el.classList.add('blk');
    el.setAttribute('data-b', i);
    if(marked.indexOf(i) !== -1){ el.classList.add('flagged'); }
    var b = document.createElement('button');
    b.className = 'flag';
    b.type = 'button';
    b.textContent = '?';
    b.title = '이 부분 모르겠어요';
    function save(){ localStorage.setItem('flag:'+page, JSON.stringify(marked)); }
    function mark(on){
      el.classList.toggle('flagged', on);
      var idx = marked.indexOf(i);
      if(on && idx === -1) marked.push(i);
      if(!on && idx !== -1) marked.splice(idx, 1);
      save();
    }
    b.addEventListener('click', function(){
      var open = el.nextElementSibling &&
                 el.nextElementSibling.classList.contains('flag-box');
      if(open){ el.nextElementSibling.remove(); return; }
      mark(true);

      var box = document.createElement('div');
      box.className = 'flag-box';
      box.innerHTML =
        '<div class="fb-lab">건의 사항</div>' +
        '<textarea rows="2"></textarea>' +
        '<div class="flag-act">' +
        '<button type="button" class="ghost fx">취소</button>' +
        '<button type="button" class="solid fs">보내기</button></div>';
      el.after(box);
      var ta = box.querySelector('textarea');
      ta.focus();

      box.querySelector('.fx').addEventListener('click', function(){
        mark(false); box.remove();
      });
      box.querySelector('.fs').addEventListener('click', function(){
        var txt = ta.value.trim();
        if(txt){
          var notes = JSON.parse(localStorage.getItem('note:'+page) || '{}');
          notes[i] = txt;
          localStorage.setItem('note:'+page, JSON.stringify(notes));
        }
        /* 나중에 여기서 서버로 전송 */
        box.innerHTML = '<div class="fb-lab done">전달되었습니다.</div>';
        setTimeout(function(){ if(box.parentNode) box.remove(); }, 1600);
      });
      ta.addEventListener('keydown', function(e){
        if(e.key === 'Escape'){ box.querySelector('.fs').click(); }
      });
    });
    el.appendChild(b);
  });

  /* 단축키 : Ctrl+B 사이드바 */
  document.addEventListener('keydown', function(e){
    if((e.ctrlKey||e.metaKey) && e.key.toLowerCase()==='b'){
      e.preventDefault(); navBtn.click();
    }
  });

  /* 수식 */
  if(window.renderMathInElement){
    renderMathInElement(document.querySelector('.content'), {
      delimiters:[
        {left:'$$', right:'$$', display:true},
        {left:'$',  right:'$',  display:false}
      ],
      throwOnError:false
    });
  }
})();
"""


# ---------------------------------------------------------------- index.html
def index_html(pages, subj_color):
    docs = [p for p in pages if p["kind"] == "doc"]
    exps = [p for p in pages if p["kind"] == "experiment"]
    cards = []
    for p in docs + exps:
        c = subj_color[p["subject"]]
        kind = "실험" if p["kind"] == "experiment" else p["subject"]
        cards.append(
            f'<a class="card" href="{p["url"]}">'
            f'<div class="kicker" style="color:{c}">{html.escape(kind)}</div>'
            f'<div class="card-t">{html.escape(p["title"])}</div></a>')
    body = ('<p>기계공학 전공 개념을 정리하고 서로 연결한 문서 모음입니다.</p>'
            f'<div class="cards">{"".join(cards)}</div>')
    page = {"title": "홈", "meta": {}, "subject": docs[0]["subject"] if docs else "기타",
            "kind": "doc", "stem": "__index__", "body": "", "links": []}
    sidebar = build_sidebar(pages, subj_color)
    return TEMPLATE.format(
        title="홈", site=html.escape(SITE_NAME), sidebar=sidebar,
        kind="", subj_color="var(--dim)", pagetitle=html.escape(SITE_NAME),
        meta_pre="", meta_tag="", byline="", body=body, backlinks="")


EXTRA_CSS = """
.cards{display:grid; grid-template-columns:repeat(auto-fill,minmax(210px,1fr));
  gap:12px; margin-top:24px}
.card{display:block; padding:16px 18px; border:1px solid var(--line);
  border-radius:11px; background:var(--panel); color:var(--fg)}
.card:hover{border-color:var(--accent)}
.card-t{font-weight:600; margin-top:4px; font-size:15.5px}
"""


# ---------------------------------------------------------------- main
if __name__ == "__main__":
    pages = collect()
    if not pages:
        raise SystemExit("docs/ 또는 experiments/ 에 .md 파일이 없습니다.")

    INDEX = {p["stem"]: p for p in pages}
    for p in pages:
        if p["meta"].get("title"):
            INDEX.setdefault(p["meta"]["title"], p)

    subjects = []
    for p in pages:
        if p["subject"] not in subjects:
            subjects.append(p["subject"])
    subj_color = {s: SUBJECT_COLORS[i % len(SUBJECT_COLORS)]
                  for i, s in enumerate(subjects)}

    # 1차 렌더로 링크 수집 -> 백링크
    backlinks = {}
    for p in pages:
        p["links"] = []
        render_body(dict(p, body=p["body"]), INDEX)
    for p in pages:
        tmp = dict(p)
        tmp["links"] = []
        render_body(tmp, INDEX)
        for t in set(tmp["links"]):
            if t != p["stem"]:
                backlinks.setdefault(t, []).append(p)

    # 폴더 자체는 두고 안의 내용만 지운다 (서버가 열어둔 상태여도 안전)
    OUT.mkdir(parents=True, exist_ok=True)
    for item in OUT.iterdir():
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            try:
                item.unlink()
            except OSError:
                pass

    (OUT / "style.css").write_text(CSS + EXTRA_CSS, encoding="utf-8")
    (OUT / "app.js").write_text(JS, encoding="utf-8")

    if (ROOT / "assets").exists():
        shutil.copytree(ROOT / "assets", OUT / "assets")

    for p in pages:
        p["links"] = []
        (OUT / p["url"]).write_text(
            page_html(p, pages, subj_color, backlinks), encoding="utf-8")

    (OUT / "index.html").write_text(index_html(pages, subj_color), encoding="utf-8")

    print(f"완료 · 문서 {len(pages)}편  ->  {OUT}")
    for p in pages:
        print(f"   {p['url']}")

    # ---- python build.py --serve  :  서버 띄우고 기본 브라우저로 열기
    if "--serve" in sys.argv:
        import http.server, socketserver, functools
        PORT = 8900
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory=str(OUT))
        socketserver.TCPServer.allow_reuse_address = True
        with socketserver.TCPServer(("127.0.0.1", PORT), handler) as srv:
            url = f"http://127.0.0.1:{PORT}/index.html"
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()
            print(f"\n{url}  ·  끄려면 Ctrl+C 또는 창 닫기")
            try:
                srv.serve_forever()
            except KeyboardInterrupt:
                print("\n종료")
