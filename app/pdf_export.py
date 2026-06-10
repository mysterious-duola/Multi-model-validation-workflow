# -*- coding: utf-8 -*-
"""PDF 导出模块 — 用 fpdf2 生成含中文、表格的 PDF 报告"""
import os, re
from datetime import datetime
from fpdf import FPDF


def export_pdf(question, results):
    """生成 PDF 报告的字节流"""
    pdf = FPDF()
    font_regular = "C:/Windows/Fonts/simhei.ttf"
    if not os.path.exists(font_regular):
        font_regular = None

    if font_regular:
        pdf.add_font("CJK", "", font_regular)
        pdf.add_font("CJK", "B", font_regular)
        font_name = "CJK"
    else:
        font_name = "Helvetica"

    pdf.add_page()
    usable_width = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_font(font_name, "B", 18)
    pdf.cell(0, 12, "多模型科研工作流 导出报告", new_x="LMARGIN", new_y="NEXT", align="C")
    pdf.ln(3)

    pdf.set_font(font_name, "", 10)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 7, f"问题：{question}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"导出时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_text_color(0, 0, 0)

    sections = [
        ("初始回答", "初始回答"),
        ("交叉验证修订", "修订后"),
        ("DeepSeek 最终综合", "DeepSeek 最终综合"),
    ]

    _emoji = re.compile(
        "["
        "\U0001F300-\U0001F9FF"  # 大部分 emoji 块（含杂项符号、表情、交通、旗帜等）
        "\U0001FA00-\U0001FAFF"  # 扩展-A
        "\U00002600-\U000027BF"  # 杂项符号
        "\U00002300-\U000023FF"  # 杂项技术
        "\U00002B00-\U00002BFF"  # 箭头等
        "\U0000FE00-\U0000FE0F"  # 变体选择符
        "\U0000200D"             # 零宽连接符
        "\U000020E3"             # 组合用封闭键帽
        "\U000000A9\U000000AE"  # © ®
        "\U00002122\U00002139"  # ™ ℹ
        "\U000025AA-\U000025FE"  # 几何形状
        "\U00002934-\U00002935"  # 箭头
        "\U00003030\U000030A0"  # 〰 ゠
        "\U00003297\U00003299"  # ㊗ ㊙
        "]+", re.UNICODE
    )

    def _clean(text):
        """去除 emoji、Markdown 加粗/斜体/链接标记"""
        text = _emoji.sub("", text)
        text = re.sub(r'\[([^\]]*)\]\(([^)]*)\)', r'\1 (\2)', text)  # [text](url) -> text (url)
        text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)   # **bold**
        text = re.sub(r'\*(.+?)\*', r'\1', text)         # *italic*
        text = re.sub(r'`(.+?)`', r'\1', text)           # `code`
        text = re.sub(r' {2,}', ' ', text)               # 合并多余空格
        return text.strip()

    def _is_table_row(line):
        return bool(re.match(r'^\|.*\|$', line.strip())) and "---" not in line

    def _is_table_separator(line):
        return bool(re.match(r'^\|[\s\-:|]+\|$', line.strip()))

    def _render_table(header, rows):
        if pdf.get_y() > 240:
            pdf.add_page()
        n_cols = len(header)
        if n_cols == 0:
            return
        col_w = usable_width / n_cols
        line_h = 4.5

        # 表头
        pdf.set_font(font_name, "B", 8)
        pdf.set_fill_color(230, 235, 245)
        for h in header:
            pdf.cell(col_w, 7, _clean(h), border=1, fill=True, align="C")
        pdf.ln()

        # 数据行（支持自动换行）
        pdf.set_font(font_name, "", 8)
        for row in rows:
            if pdf.get_y() > 250:
                pdf.add_page()

            max_lines = 1
            for cell_text in row:
                clean = _clean(cell_text)
                lines = pdf.multi_cell(col_w - 2, line_h, clean,
                                       dry_run=True, output="LINES")
                max_lines = max(max_lines, len(lines))

            row_h = max(6, max_lines * line_h)
            x_start = pdf.l_margin
            y_start = pdf.get_y()

            for cell_text in row:
                clean = _clean(cell_text)
                pdf.rect(x_start, y_start, col_w, row_h)
                pdf.set_xy(x_start + 1, y_start + 0.5)
                pdf.multi_cell(col_w - 2, line_h, clean, align="L")
                x_start += col_w

            pdf.set_xy(pdf.l_margin, y_start + row_h)
        pdf.ln(2)

    def _render_text_block(content):
        lines = content.split("\n")
        i = 0
        in_list = False
        list_indent = ""
        while i < len(lines):
            raw = lines[i]
            line = raw.strip()

            # 空行跳过，重置列表上下文
            if not line:
                in_list = False
                list_indent = ""
                i += 1
                continue

            # 检测原始行的缩进级别
            leading_spaces = len(raw) - len(raw.lstrip())

            # ---- Markdown 表格检测 ----
            # 表头行 + 紧跟分隔行（如 |---|---| ）
            if (_is_table_row(line)
                    and i + 1 < len(lines)
                    and _is_table_separator(lines[i + 1])):
                header = [c.strip() for c in line.split("|")[1:-1]]
                i += 2  # 跳过表头 + 分隔行
                rows = []
                while i < len(lines) and _is_table_row(lines[i]):
                    cols = [c.strip() for c in lines[i].split("|")[1:-1]]
                    while len(cols) < len(header):
                        cols.append("")
                    rows.append(cols[:len(header)])
                    i += 1
                _render_table(header, rows)
                in_list = False
                continue

            # 分隔行单独出现（表格残留），跳过
            if _is_table_separator(line):
                i += 1
                continue

            # ---- Markdown 标题 ----
            heading_match = re.match(r'^(#{1,6})\s+(.*)', line)
            if heading_match:
                level = len(heading_match.group(1))
                heading_text = _clean(heading_match.group(2))
                if not heading_text:
                    i += 1
                    continue
                if pdf.get_y() > 255:
                    pdf.add_page()
                size_map = {1: 14, 2: 13, 3: 12, 4: 11, 5: 10, 6: 10}
                pdf.set_font(font_name, "B", size_map.get(level, 10))
                pdf.set_text_color(30, 60, 120)
                pdf.cell(0, 8, heading_text, new_x="LMARGIN", new_y="NEXT")
                pdf.set_text_color(0, 0, 0)
                pdf.ln(1)
                in_list = False
                i += 1
                continue

            # ---- 水平线 ----
            if re.match(r'^-{3,}$|^\*{3,}$|^_{3,}$', line):
                pdf.set_draw_color(200, 200, 200)
                pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
                pdf.ln(2)
                in_list = False
                i += 1
                continue

            # ---- 普通文本（含列表项等）----
            if pdf.get_y() > 260:
                pdf.add_page()
            text = _clean(line)
            if text:
                url_pattern = re.compile(r'(https?://[^\s\)]+)')
                url_matches = list(url_pattern.finditer(text))

                # 判断是否为列表项
                is_list_item = bool(re.match(
                    r'^(\d+[\.\)]\s|\d+\s(?=\S)|[-*+]\s)', text))

                # 计算缩进：基于原始行缩进或列表上下文
                if is_list_item:
                    in_list = True
                    if leading_spaces >= 4:
                        indent = "        "  # 二级缩进
                    elif leading_spaces >= 2:
                        indent = "    "      # 一级缩进
                    else:
                        indent = "    "      # 顶层列表项
                    list_indent = indent
                elif in_list and leading_spaces > 0:
                    indent = list_indent     # 列表续行保持缩进
                else:
                    in_list = False
                    indent = ""

                if url_matches:
                    pdf.set_font(font_name, "", 9)
                    if len(url_matches) == 1 and re.match(
                            r'^(?:\d+[\.\)]\s|[-*+]\s)?https?://[^\s\)]+$', text):
                        url = url_matches[0].group()
                        pdf.set_text_color(0, 0, 200)
                        pdf.multi_cell(usable_width, 5, indent + text, link=url,
                                       new_x="LMARGIN", new_y="NEXT")
                        pdf.set_text_color(0, 0, 0)
                    else:
                        if indent:
                            pdf.write(5, indent)
                        last_end = 0
                        for m in url_matches:
                            before = text[last_end:m.start()]
                            if before:
                                pdf.write(5, before)
                            pdf.set_text_color(0, 0, 200)
                            pdf.write(5, m.group(), link=m.group())
                            pdf.set_text_color(0, 0, 0)
                            last_end = m.end()
                        after = text[last_end:]
                        if after:
                            pdf.write(5, after)
                        pdf.ln()
                else:
                    pdf.set_font(font_name, "", 9)
                    pdf.multi_cell(usable_width, 5, indent + text,
                                   new_x="LMARGIN", new_y="NEXT")
            i += 1

    for title, keyword in sections:
        if keyword == "DeepSeek 最终综合":
            val = results.get(keyword)
            keys = None
        else:
            keys = [k for k in results if keyword in k]
            val = None
        if not val and not keys:
            continue

        if pdf.get_y() > 250:
            pdf.add_page()
        pdf.set_font(font_name, "B", 13)
        pdf.set_text_color(30, 60, 120)
        pdf.cell(0, 9, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(200, 200, 200)
        pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        pdf.ln(3)
        pdf.set_text_color(0, 0, 0)

        if keyword == "DeepSeek 最终综合":
            _render_text_block(val)
        else:
            for k in keys:
                model_name = k.replace(f" {keyword}", "")
                if pdf.get_y() > 255:
                    pdf.add_page()
                pdf.set_font(font_name, "B", 10)
                pdf.cell(0, 7, model_name, new_x="LMARGIN", new_y="NEXT")
                _render_text_block(results[k])
                pdf.ln(2)
        pdf.ln(2)

    return bytes(pdf.output())
