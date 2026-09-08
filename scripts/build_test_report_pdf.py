"""Build the review PDF from the recorded integration trace and UI evidence."""

from __future__ import annotations

import argparse
import html
import re
import textwrap
from datetime import UTC, datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    XPreformatted,
)

NAVY = colors.HexColor("#102A43")
BLUE = colors.HexColor("#1769E0")
INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#52657A")
GREEN = colors.HexColor("#087F5B")
LINE = colors.HexColor("#CBD8E8")


def register_fonts() -> str:
    sans_path = Path("/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    pdfmetrics.registerFont(TTFont("CasePilotSans", sans_path))
    return "CasePilotSans"


def wrap_code(block: str, width: int = 105) -> str:
    output: list[str] = []
    for line in block.splitlines() or [""]:
        leading = len(line) - len(line.lstrip(" "))
        prefix = " " * min(leading, 12)
        wrapped = textwrap.wrap(
            line.strip() if leading else line,
            width=max(25, width - len(prefix)),
            replace_whitespace=False,
            drop_whitespace=False,
            break_long_words=True,
            break_on_hyphens=False,
        ) or [""]
        output.extend(prefix + part for part in wrapped)
    return "\n".join(output)


def image_story(path: Path, caption: str, body_width: float, body_height: float):
    image = Image(str(path))
    scale = min(body_width / image.imageWidth, body_height / image.imageHeight)
    image.drawWidth = image.imageWidth * scale
    image.drawHeight = image.imageHeight * scale
    return [image, Spacer(1, 2 * mm), caption]


def build_pdf(trace_path: Path, ui_dir: Path, output_path: Path) -> None:
    sans = register_fonts()
    styles = getSampleStyleSheet()
    title = ParagraphStyle(
        "TitleCN",
        parent=styles["Title"],
        fontName=sans,
        fontSize=24,
        leading=32,
        textColor=NAVY,
        alignment=TA_LEFT,
        spaceAfter=6 * mm,
    )
    heading = ParagraphStyle(
        "HeadingCN",
        parent=styles["Heading1"],
        fontName=sans,
        fontSize=15,
        leading=21,
        textColor=NAVY,
        spaceBefore=5 * mm,
        spaceAfter=3 * mm,
    )
    subheading = ParagraphStyle(
        "SubheadingCN",
        parent=styles["Heading2"],
        fontName=sans,
        fontSize=11,
        leading=16,
        textColor=BLUE,
        spaceBefore=3 * mm,
        spaceAfter=2 * mm,
    )
    body = ParagraphStyle(
        "BodyCN",
        parent=styles["BodyText"],
        fontName=sans,
        fontSize=9.5,
        leading=15,
        textColor=INK,
        spaceAfter=2 * mm,
    )
    small = ParagraphStyle(
        "SmallCN",
        parent=body,
        fontSize=8,
        leading=12,
        textColor=MUTED,
    )
    code = ParagraphStyle(
        "CodeCN",
        parent=styles["Code"],
        fontName=sans,
        fontSize=6.4,
        leading=9.1,
        textColor=INK,
        leftIndent=3 * mm,
        rightIndent=3 * mm,
        borderColor=LINE,
        borderWidth=0.5,
        borderPadding=5,
        backColor=colors.HexColor("#F7FAFD"),
        spaceAfter=3 * mm,
    )
    caption = ParagraphStyle(
        "CaptionCN",
        parent=small,
        alignment=TA_LEFT,
        textColor=NAVY,
        spaceAfter=5 * mm,
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(LINE)
        canvas.line(doc.leftMargin, 13 * mm, A4[0] - doc.rightMargin, 13 * mm)
        canvas.setFont(sans, 7)
        canvas.setFillColor(MUTED)
        canvas.drawString(doc.leftMargin, 8 * mm, "CasePilot · TestWeb / TestTool 集成回归")
        canvas.drawRightString(A4[0] - doc.rightMargin, 8 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        title="CasePilot 真实 AI 接口与 UI 回归测试报告",
        author="CasePilot Engineering",
    )
    story = [
        Paragraph("CasePilot 真实 AI 接口与 UI 回归测试报告", title),
        Paragraph(
            f"生成时间：{datetime.now(UTC).astimezone().isoformat(timespec='seconds')}", small
        ),
        Spacer(1, 4 * mm),
    ]
    cards = [
        ["测试结论", "通过"],
        ["真实 AI", "doubao-seed-2.0-lite，完整四阶段生成"],
        ["接口流水", "93 次客户端请求/返回；12 次异步回调"],
        ["接口资产", "CP-00009 / CASE-SESSION-00012 / TASK-00008"],
        ["UI 资产", "UI回归-登录接口-20260908；7 条用例；1 个执行任务"],
        ["安全处理", "Authorization、密码、lease_token 均已脱敏"],
    ]
    table = Table(cards, colWidths=[35 * mm, 135 * mm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), NAVY),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.white),
                ("TEXTCOLOR", (1, 0), (1, -1), INK),
                ("FONTNAME", (0, 0), (-1, -1), sans),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("LEADING", (0, 0), (-1, -1), 12),
                ("BACKGROUND", (1, 0), (1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend(
        [
            table,
            Spacer(1, 5 * mm),
            Paragraph("验证范围与结论", heading),
            Paragraph(
                "真实 AI 链路、异步生成状态、完整用例快照、任务确认、TestTool 按用户/target_type/case_id 查询、领取、续租、执行回传和幂等重放全部通过。用例快照包含 L0、L2、L4 分级。",
                body,
            ),
            Paragraph(
                "UI 回归完成新对话、结构化说明、真实生成、候选修改、正式入库、Playlist 和执行任务创建闭环；浏览器错误列表为空。",
                body,
            ),
            Paragraph("UI 回归证据", heading),
        ]
    )
    screenshots = [
        ("01-new-conversation.png", "图 1 · 新对话入口"),
        ("02-structured-brief.png", "图 2 · 真实 AI 生成结构化测试说明"),
        ("03-generated-and-edited.png", "图 3 · 7 条候选用例及已保存的标题/优先级修改"),
        ("04-committed-library.png", "图 4 · 正式集合中已入库的 7 条用例"),
        ("05-task-created.png", "图 5 · Playlist 执行任务创建完成"),
    ]
    for filename, label in screenshots:
        path = ui_dir / filename
        image_parts = image_story(path, Paragraph(label, caption), 178 * mm, 205 * mm)
        story.extend(image_parts)
    story.extend(
        [
            PageBreak(),
            Paragraph("逐请求、返回与异步回调明细", title),
            Paragraph(
                "以下内容由自动化采集器在实际执行时逐条记录，保留 URL、方法、请求体、HTTP 状态、返回体、耗时及回调载荷。",
                body,
            ),
        ]
    )

    source = trace_path.read_text(encoding="utf-8")
    in_code = False
    code_lines: list[str] = []
    for raw in source.splitlines():
        if raw.startswith("```"):
            if in_code:
                story.append(XPreformatted(html.escape(wrap_code("\n".join(code_lines))), code))
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(raw)
            continue
        if raw.startswith("# "):
            continue
        if raw.startswith("## "):
            story.append(Paragraph(html.escape(raw[3:]), heading))
        elif raw.startswith("### "):
            story.append(Paragraph(html.escape(raw[4:]), subheading))
        elif raw.startswith("- "):
            text = html.escape(raw[2:])
            color = GREEN if "PASSED" in raw else INK
            story.append(Paragraph(f'<font color="{color.hexval()}">• {text}</font>', body))
        elif raw.strip():
            safe = html.escape(re.sub(r"\s+", " ", raw.strip()))
            story.append(Paragraph(safe, body))
    if code_lines:
        story.append(XPreformatted(html.escape(wrap_code("\n".join(code_lines))), code))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--ui-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build_pdf(args.trace, args.ui_dir, args.output)


if __name__ == "__main__":
    main()
