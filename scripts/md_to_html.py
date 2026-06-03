"""Markdown → 简单 HTML 包装（无外部依赖）。"""
import re
import sys
from pathlib import Path

md_path = Path(sys.argv[1])
md = md_path.read_text(encoding="utf-8")

# 极简 markdown 处理
def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

# 表格转换（处理 |...| 形式）
def table_to_html(md_text):
    lines = md_text.split("\n")
    out = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.strip().startswith("|") and i + 1 < len(lines) and "---" in lines[i + 1]:
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                rows.append(cells)
                i += 1
            if len(rows) < 2:
                continue
            html_t = ['<table><thead><tr>']
            for c in rows[0]:
                html_t.append(f'<th>{esc(c)}</th>')
            html_t.append("</tr></thead><tbody>")
            for r in rows[2:]:  # 跳过分隔行
                html_t.append("<tr>")
                for c in r:
                    # 处理 **bold**
                    c_html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", esc(c))
                    # 处理 *italic* (不用)
                    c_html = re.sub(r"`(.+?)`", r"<code>\1</code>", c_html)
                    html_t.append(f"<td>{c_html}</td>")
                html_t.append("</tr>")
            html_t.append("</tbody></table>")
            out.append("\n".join(html_t))
        else:
            out.append(line)
            i += 1
    return "\n".join(out)

html_body = table_to_html(md)

# 标题 / 列表 / 段落
lines = html_body.split("\n")
out = []
in_ul = False
for line in lines:
    if line.startswith("#### "):
        if in_ul:
            out.append("</ul>")
            in_ul = False
        out.append(f"<h4>{esc(line[5:].strip())}</h4>")
    elif line.startswith("### "):
        if in_ul:
            out.append("</ul>")
            in_ul = False
        out.append(f"<h3>{esc(line[4:].strip())}</h3>")
    elif line.startswith("## "):
        if in_ul:
            out.append("</ul>")
            in_ul = False
        out.append(f"<h2>{esc(line[3:].strip())}</h2>")
    elif line.startswith("# "):
        if in_ul:
            out.append("</ul>")
            in_ul = False
        out.append(f"<h1>{esc(line[2:].strip())}</h1>")
    elif line.startswith("- "):
        if not in_ul:
            out.append("<ul>")
            in_ul = True
        li_text = esc(line[2:].strip())
        li_text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", li_text)
        out.append(f"<li>{li_text}</li>")
    elif line.strip() == "---":
        if in_ul:
            out.append("</ul>")
            in_ul = False
        out.append("<hr>")
    elif line.strip() == "":
        if in_ul:
            out.append("</ul>")
            in_ul = False
    elif line.lstrip().startswith("<"):
        # HTML 块（table / script 等）原样输出，不包 <p>
        if in_ul:
            out.append("</ul>")
            in_ul = False
        out.append(line)
    else:
        if in_ul:
            out.append("</ul>")
            in_ul = False
        p_text = esc(line)
        p_text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", p_text)
        out.append(f"<p>{p_text}</p>")

if in_ul:
    out.append("</ul>")

body = "\n".join(out)

html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>AI 算力链多票分析 2026-06-03</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif; max-width: 1100px; margin: 0 auto; padding: 32px 24px; background: #fff; color: #1a1a1a; line-height: 1.65; }}
  h1 {{ font-size: 24px; border-bottom: 2px solid #2962ff; padding-bottom: 8px; }}
  h2 {{ font-size: 19px; margin-top: 32px; padding-left: 10px; border-left: 4px solid #2962ff; }}
  h3 {{ font-size: 16px; margin-top: 20px; color: #2962ff; }}
  h4 {{ font-size: 14px; margin-top: 14px; color: #444; }}
  hr {{ border: 0; border-top: 1px solid #ddd; margin: 28px 0; }}
  p {{ margin: 8px 0; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13px; }}
  th, td {{ padding: 8px 12px; border: 1px solid #e0e0e0; }}
  th {{ background: #f5f7fa; font-weight: 600; text-align: left; }}
  td {{ text-align: right; }}
  td:first-child, th:first-child {{ text-align: left; }}
  ul {{ padding-left: 24px; margin: 8px 0; }}
  li {{ margin: 4px 0; }}
  b {{ color: #2962ff; }}
  code {{ background: #f5f5f5; padding: 1px 6px; border-radius: 3px; font-size: 12px; }}
  .footer {{ margin-top: 40px; padding-top: 16px; border-top: 1px solid #ddd; color: #888; font-size: 12px; }}
</style>
</head>
<body>
{body}
<div class="footer">
  <p>本报告由 chinaStock 框架 + Claude 编排生成，仅供研究参考，不构成投资建议。</p>
  <p>数据源：westock-data (Node CLI 腾讯自选股) + AKShare (东方财富)。</p>
</div>
</body>
</html>
"""

out_path = md_path.with_suffix(".html")
out_path.write_text(html, encoding="utf-8")
print(f"HTML 已生成: {out_path}")
print(f"大小: {out_path.stat().st_size / 1024:.1f} KB")
