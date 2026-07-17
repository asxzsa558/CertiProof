#!/usr/bin/env python3
"""Build the standalone product-design page from ARCHITECTURE.md."""

from __future__ import annotations

import base64
import html
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".opencode/plans/ARCHITECTURE.md"
LOGO = ROOT / "frontend/public/verisure-logo.svg"
OUTPUT = ROOT / "docs/certiproof-product-design.html"
MERMAID_RUNTIME = ROOT / "frontend/node_modules/mermaid/dist/mermaid.min.js"


def inline(text: str) -> str:
    value = html.escape(text.strip())
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    value = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", value)
    return value


def is_table_separator(line: str) -> bool:
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def render_markdown(markdown: str) -> tuple[str, list[tuple[str, str, int]], bool]:
    lines = markdown.splitlines()
    output: list[str] = []
    toc: list[tuple[str, str, int]] = []
    heading_index = 0
    has_mermaid = False
    index = 0

    def special(line: str, next_line: str = "") -> bool:
        stripped = line.strip()
        return (
            not stripped
            or stripped.startswith(("#", ">", "```", "- "))
            or stripped == "---"
            or bool(re.match(r"\d+\.\s", stripped))
            or ("|" in stripped and is_table_separator(next_line))
        )

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""

        if not stripped:
            index += 1
            continue

        if stripped.startswith("```"):
            language = stripped[3:].strip()
            block: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].strip().startswith("```"):
                block.append(lines[index])
                index += 1
            index += 1
            if language == "mermaid":
                has_mermaid = True
                source = html.escape(chr(10).join(block))
                output.append(f'<div class="diagram-shell"><pre class="mermaid">{source}</pre></div>')
                continue
            language_class = f' class="language-{html.escape(language)}"' if language else ""
            output.append(f"<pre><code{language_class}>{html.escape(chr(10).join(block))}</code></pre>")
            continue

        heading = re.match(r"^(#{1,3})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2)
            if level == 1:
                index += 1
                continue
            heading_index += 1
            anchor = f"section-{heading_index}"
            if level in (2, 3):
                toc.append((anchor, title, level))
            output.append(f'<h{level} id="{anchor}">{inline(title)}<a href="#{anchor}" aria-label="链接到本节">#</a></h{level}>')
            index += 1
            continue

        if stripped == "---":
            output.append("<hr>")
            index += 1
            continue

        if stripped.startswith(">"):
            quote: list[str] = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip()[1:].strip())
                index += 1
            output.append(f"<blockquote>{inline(' '.join(quote))}</blockquote>")
            continue

        if "|" in stripped and is_table_separator(next_line):
            headers = [cell.strip() for cell in stripped.strip("|").split("|")]
            index += 2
            rows: list[list[str]] = []
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append([cell.strip() for cell in lines[index].strip().strip("|").split("|")])
                index += 1
            head = "".join(f"<th>{inline(cell)}</th>" for cell in headers)
            body = "".join(
                "<tr>" + "".join(f"<td>{inline(cell)}</td>" for cell in row) + "</tr>"
                for row in rows
            )
            output.append(f'<div class="table-wrap"><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>')
            continue

        if stripped.startswith("- "):
            items: list[str] = []
            while index < len(lines) and lines[index].strip().startswith("- "):
                items.append(lines[index].strip()[2:])
                index += 1
            output.append("<ul>" + "".join(f"<li>{inline(item)}</li>" for item in items) + "</ul>")
            continue

        if re.match(r"\d+\.\s", stripped):
            items: list[str] = []
            while index < len(lines) and re.match(r"\d+\.\s", lines[index].strip()):
                items.append(re.sub(r"^\d+\.\s+", "", lines[index].strip()))
                index += 1
            output.append("<ol>" + "".join(f"<li>{inline(item)}</li>" for item in items) + "</ol>")
            continue

        paragraph = [stripped]
        index += 1
        while index < len(lines):
            candidate = lines[index].strip()
            following = lines[index + 1].strip() if index + 1 < len(lines) else ""
            if special(candidate, following):
                break
            paragraph.append(candidate)
            index += 1
        output.append(f"<p>{inline(' '.join(paragraph))}</p>")

    return "\n".join(output), toc, has_mermaid


def build_page(
    article: str,
    toc: list[tuple[str, str, int]],
    has_mermaid: bool,
    version: str,
    updated_at: str,
) -> str:
    logo_uri = "data:image/svg+xml;base64," + base64.b64encode(LOGO.read_bytes()).decode("ascii")
    mermaid_runtime = ""
    mermaid_setup = ""
    if has_mermaid:
        if not MERMAID_RUNTIME.exists():
            raise FileNotFoundError("Mermaid runtime missing; run npm install in frontend")
        mermaid_source = MERMAID_RUNTIME.read_text(encoding="utf-8").replace("</script", "<\\/script")
        mermaid_runtime = f"<script>{mermaid_source}</script>"
        mermaid_setup = """
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: 'strict',
      theme: 'base',
      themeVariables: {
        background: '#030711', primaryColor: '#0b2633', primaryTextColor: '#edf7ff',
        primaryBorderColor: '#53def1', lineColor: '#4ca6bc', secondaryColor: '#101b31',
        tertiaryColor: '#071322', clusterBkg: '#06111d', clusterBorder: '#285567',
        fontFamily: 'Inter, PingFang SC, Microsoft YaHei, system-ui, sans-serif', fontSize: '13px'
      },
      flowchart: { curve: 'basis', htmlLabels: true, useMaxWidth: true },
      sequence: { useMaxWidth: true, wrap: true },
      state: { useMaxWidth: true }
    });
    mermaid.run({ querySelector: '.mermaid' }).catch(error => console.error('Diagram render failed', error));
"""
    section_number = 0
    navigation_items = []
    for anchor, title, level in toc:
        if level == 2:
            section_number += 1
            marker = f"{section_number:02d}"
            css_class = ""
        else:
            marker = "·"
            css_class = ' class="sub"'
        navigation_items.append(
            f'<a{css_class} href="#{anchor}"><span>{marker}</span>{html.escape(title)}</a>'
        )
    navigation = "\n".join(navigation_items)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="CertiProof 产品定位、结构、模块和功能设计文档">
  <title>CertiProof 产品设计文档</title>
  <style>
    :root {{ color-scheme: dark; --bg:#030711; --panel:#071322; --line:rgba(83,222,241,.17); --line2:rgba(83,222,241,.34); --text:#edf7ff; --muted:#91a8ba; --cyan:#53def1; --blue:#57a9ff; --gold:#f6c85f; }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{ margin:0; min-height:100vh; color:var(--text); background:linear-gradient(rgba(83,222,241,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(83,222,241,.03) 1px,transparent 1px),linear-gradient(125deg,#020611,#060c1b 50%,#071120); background-size:34px 34px,34px 34px,100% 100%; font-family:Inter,"PingFang SC","Microsoft YaHei",system-ui,sans-serif; letter-spacing:0; }}
    body::after {{ content:""; position:fixed; right:4vw; bottom:4vh; width:min(27vw,330px); aspect-ratio:1; opacity:.045; pointer-events:none; background:url('{logo_uri}') center/contain no-repeat; }}
    .progress {{ position:fixed; inset:0 auto auto 0; z-index:20; width:0; height:2px; background:var(--cyan); box-shadow:0 0 12px var(--cyan); }}
    .layout {{ display:grid; grid-template-columns:260px minmax(0,1fr); min-height:100vh; }}
    aside {{ position:sticky; top:0; height:100vh; padding:24px 18px; overflow:auto; border-right:1px solid var(--line); background:rgba(3,9,21,.94); scrollbar-width:thin; }}
    .brand {{ display:flex; align-items:center; gap:12px; padding:0 8px 24px; border-bottom:1px solid var(--line); }}
    .brand img {{ width:43px; height:43px; filter:drop-shadow(0 0 13px rgba(83,222,241,.42)); }}
    .brand strong {{ display:block; font:700 22px/1 Georgia,serif; }}
    .brand small {{ display:block; margin-top:6px; color:var(--muted); font-size:10px; }}
    .toc-label {{ margin:24px 9px 9px; color:#69869c; font-size:10px; }}
    nav {{ display:grid; gap:3px; }}
    nav a {{ display:grid; grid-template-columns:27px 1fr; align-items:center; min-height:37px; padding:7px 9px; color:#a9becd; border:1px solid transparent; border-radius:4px; text-decoration:none; font-size:12px; line-height:1.35; transition:150ms ease; }}
    nav a span {{ color:#4f8298; font:600 10px/1 ui-monospace,monospace; }}
    nav a.sub {{ min-height:31px; padding-block:5px; padding-left:18px; color:#8099aa; font-size:11px; }}
    nav a.sub span {{ color:#3a6c80; font-size:13px; }}
    nav a:hover,nav a.active {{ color:#f7fcff; border-color:var(--line2); background:rgba(39,161,188,.13); }}
    nav a.active span {{ color:var(--cyan); }}
    .aside-meta {{ margin:24px 9px 0; padding-top:16px; border-top:1px solid var(--line); color:#678095; font-size:10px; line-height:1.8; }}
    main {{ min-width:0; padding:34px clamp(24px,5vw,82px) 80px; }}
    .toolbar {{ display:flex; justify-content:space-between; align-items:center; gap:12px; margin:auto; max-width:1100px; }}
    .toolbar a,.toolbar button {{ min-height:34px; padding:0 12px; color:#b8cedd; border:1px solid var(--line); border-radius:4px; background:rgba(7,19,34,.68); cursor:pointer; text-decoration:none; font:600 12px/1 inherit; }}
    .toolbar a:hover,.toolbar button:hover {{ color:#fff; border-color:var(--line2); }}
    .version {{ color:#7190a7; font:600 10px/1 ui-monospace,monospace; }}
    .hero {{ max-width:1100px; margin:62px auto 58px; }}
    .eyebrow {{ color:var(--cyan); font:600 11px/1 ui-monospace,monospace; }}
    h1 {{ max-width:830px; margin:17px 0 19px; font:700 clamp(38px,5.8vw,72px)/1.06 Georgia,"Songti SC",serif; }}
    .lead {{ max-width:790px; color:#a9bfce; font-size:16px; line-height:1.9; }}
    .signals {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:27px; }}
    .signals span {{ padding:7px 10px; color:#b7d9e5; border:1px solid var(--line); background:rgba(9,31,48,.62); font-size:11px; }}
    .flow {{ display:grid; grid-template-columns:repeat(4,1fr); max-width:1100px; margin:0 auto 58px; border-block:1px solid var(--line); }}
    .flow div {{ position:relative; padding:18px 14px; border-right:1px solid var(--line); }}
    .flow div:last-child {{ border:0; }}
    .flow b {{ display:block; color:var(--cyan); font:600 10px/1 ui-monospace,monospace; }}
    .flow span {{ display:block; margin-top:7px; font-size:13px; }}
    article {{ max-width:1100px; margin:auto; }}
    article h2 {{ scroll-margin-top:24px; margin:68px 0 24px; padding-top:26px; border-top:1px solid var(--line2); font:700 28px/1.3 Georgia,"Songti SC",serif; }}
    article h3 {{ scroll-margin-top:24px; margin:38px 0 15px; color:#dceef8; font-size:18px; }}
    article h2 a,article h3 a {{ margin-left:9px; color:transparent; text-decoration:none; font-size:12px; }}
    article h2:hover a,article h3:hover a {{ color:#4c869c; }}
    article p,article li {{ color:#b1c3d0; font-size:14px; line-height:1.86; }}
    article p {{ margin:11px 0; }}
    article ul,article ol {{ margin:10px 0 20px; padding-left:23px; }}
    article li {{ margin:5px 0; padding-left:3px; }}
    article li::marker {{ color:var(--cyan); }}
    article blockquote {{ margin:0 0 24px; padding:13px 16px; color:#acd6e4; border-left:2px solid var(--cyan); background:rgba(15,52,69,.32); font-size:13px; line-height:1.7; }}
    article code {{ padding:2px 5px; color:#8be8f5; border:1px solid rgba(83,222,241,.12); background:#06111d; border-radius:3px; font:12px/1.5 ui-monospace,SFMono-Regular,Consolas,monospace; }}
    article pre {{ overflow:auto; margin:18px 0 26px; padding:18px 20px; border:1px solid var(--line); background:#020812; scrollbar-width:thin; }}
    article pre code {{ padding:0; color:#a8d8e5; border:0; background:none; line-height:1.7; }}
    .diagram-shell {{ overflow:auto; margin:20px 0 30px; padding:20px; border:1px solid var(--line2); background:rgba(2,8,18,.82); scrollbar-width:thin; }}
    .diagram-shell .mermaid {{ display:flex; justify-content:center; min-width:720px; margin:0; padding:0; border:0; background:transparent; }}
    .diagram-shell svg {{ height:auto; max-width:100%; }}
    .diagram-shell .edgeLabel {{ color:#c9eaf2; background:#071322 !important; }}
    .table-wrap {{ overflow:auto; margin:17px 0 28px; border:1px solid var(--line); scrollbar-width:thin; }}
    table {{ width:100%; min-width:650px; border-collapse:collapse; background:rgba(5,17,31,.72); }}
    th,td {{ padding:12px 14px; border-right:1px solid var(--line); border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:12px; line-height:1.65; }}
    th {{ color:#dff9ff; background:rgba(26,91,111,.24); font-weight:600; }}
    td {{ color:#a9bfce; }}
    tr:last-child td {{ border-bottom:0; }}
    th:last-child,td:last-child {{ border-right:0; }}
    hr {{ margin:54px 0 28px; border:0; border-top:1px solid var(--line); }}
    footer {{ max-width:1100px; margin:70px auto 0; padding-top:24px; border-top:1px solid var(--line); color:#607a8e; font-size:11px; }}
    @media (max-width:900px) {{ .layout {{ display:block; }} aside {{ position:sticky; z-index:10; height:auto; padding:10px 14px; border-right:0; border-bottom:1px solid var(--line); }} .brand {{ display:none; }} .toc-label,.aside-meta {{ display:none; }} nav {{ display:flex; overflow:auto; }} nav a {{ min-width:max-content; grid-template-columns:auto; }} nav a span {{ display:none; }} main {{ padding:24px 18px 60px; }} .hero {{ margin:42px auto; }} .flow {{ grid-template-columns:1fr 1fr; }} .flow div {{ border-bottom:1px solid var(--line); }} }}
    @media (max-width:520px) {{ h1 {{ font-size:39px; }} .lead {{ font-size:14px; }} .flow {{ grid-template-columns:1fr; }} .flow div {{ border-right:0; }} article h2 {{ font-size:23px; }} .toolbar .version {{ display:none; }} }}
    @media print {{ body {{ color:#111; background:#fff; }} body::after,.progress,aside,.toolbar {{ display:none; }} .layout {{ display:block; }} main {{ padding:0; }} .hero {{ margin:0 0 24px; }} h1,article h2,article h3 {{ color:#111; }} .lead,article p,article li,td {{ color:#333; }} .signals span,.table-wrap,table,th,td,article pre {{ border-color:#bbb; background:#fff; }} article code,article pre code {{ color:#222; background:#f5f5f5; }} }}
  </style>
</head>
<body>
  <div class="progress" aria-hidden="true"></div>
  <div class="layout">
    <aside>
      <div class="brand"><img src="{logo_uri}" alt=""><div><strong>CertiProof</strong><small>PRODUCT DESIGN / {html.escape(version)}</small></div></div>
      <div class="toc-label">文档目录</div>
      <nav>{navigation}</nav>
      <div class="aside-meta">最后更新 {html.escape(updated_at)}<br>CertiProof Team</div>
    </aside>
    <main>
      <div class="toolbar"><span class="version">CERTIPROOF / PRODUCT BLUEPRINT</span><button type="button" onclick="window.print()">打印文档</button></div>
      <header class="hero">
        <div class="eyebrow">// ENTERPRISE COMPLIANCE SELF-ASSESSMENT</div>
        <h1>CertiProof<br>产品设计文档</h1>
        <p class="lead">面向被测评企业的等保合规自查平台，从资产与文档检查出发，贯通差距发现、直接整改复测和 HTML 报告。</p>
        <div class="signals"><span>企业自查</span><span>自动化检测</span><span>文档合规</span><span>整改闭环</span><span>HTML 报告</span></div>
      </header>
      <section class="flow" aria-label="四阶段测评流程"><div><b>01</b><span>差距分析</span></div><div><b>02</b><span>现场测评</span></div><div><b>03</b><span>整改与复测</span></div><div><b>04</b><span>生成报告</span></div></section>
      <article>{article}</article>
      <footer>CertiProof 产品设计文档 · 由 ARCHITECTURE.md 自动生成</footer>
    </main>
  </div>
  {mermaid_runtime}
  <script>
    {mermaid_setup}
    const progress = document.querySelector('.progress');
    const links = [...document.querySelectorAll('nav a')];
    const sections = links.map(link => document.querySelector(link.hash)).filter(Boolean);
    const update = () => {{
      const max = document.documentElement.scrollHeight - innerHeight;
      progress.style.width = `${{max > 0 ? scrollY / max * 100 : 0}}%`;
      let active = sections[0];
      for (const section of sections) if (section.getBoundingClientRect().top <= 120) active = section;
      links.forEach(link => link.classList.toggle('active', active && link.hash === `#${{active.id}}`));
    }};
    addEventListener('scroll', update, {{ passive:true }});
    update();
  </script>
</body>
</html>
"""


def main() -> None:
    markdown = SOURCE.read_text(encoding="utf-8")
    version = re.search(r"\*\*文档版本\*\*:\s*(\S+)", markdown)
    updated_at = re.search(r"\*\*最后更新\*\*:\s*(\S+)", markdown)
    article, toc, has_mermaid = render_markdown(markdown)
    page = build_page(
        article,
        toc,
        has_mermaid,
        version.group(1) if version else "unversioned",
        updated_at.group(1) if updated_at else "未标记",
    )
    if "--check" in sys.argv[1:]:
        assert OUTPUT.exists() and OUTPUT.read_text(encoding="utf-8") == page, "product page is out of date"
        print(f"Checked {OUTPUT.relative_to(ROOT)}")
        return
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(page, encoding="utf-8")
    print(f"Built {OUTPUT.relative_to(ROOT)} from {SOURCE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
