"""Publish v1.4 of the Case Service API PDF with caller-specific callbacks."""

from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

REPLACED_PAGE_INDEX = 6
PLAYLIST_FRONTEND_PAGE_INDEX = 7
GENERATION_PAGE_INDEX = 4
CALLBACK_INSERT_AFTER_INDEX = 2
FONT = "CasePilotSans"
NAVY = colors.HexColor("#102A43")
BLUE = colors.HexColor("#1769E0")
INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#50647A")
PALE = colors.HexColor("#EEF4FB")
LINE = colors.HexColor("#C7D5E5")
GREEN = colors.HexColor("#087F5B")


def register_font() -> None:
    pdfmetrics.registerFont(TTFont(FONT, "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"))


def wrapped_lines(text: str, max_units: int) -> list[str]:
    lines: list[str] = []
    current = ""
    units = 0
    for char in text:
        char_units = 2 if ord(char) > 127 else 1
        if current and units + char_units > max_units:
            lines.append(current)
            current, units = char, char_units
        else:
            current += char
            units += char_units
    if current:
        lines.append(current)
    return lines or [""]


def draw_table(
    pdf: canvas.Canvas,
    *,
    y: float,
    rows: list[tuple[str, str, str, str]],
    widths: tuple[float, float, float, float] = (118, 78, 64, 235),
    font_size: float = 7.4,
) -> float:
    x = 50
    header_height = 23
    pdf.setFillColor(NAVY)
    pdf.rect(x, y - header_height, sum(widths), header_height, fill=1, stroke=0)
    pdf.setFont(FONT, 8.1)
    pdf.setFillColor(colors.white)
    offset = x
    for header, width in zip(("字段", "类型", "必填", "说明与约束"), widths, strict=True):
        pdf.drawString(offset + 6, y - 15, header)
        offset += width
    y -= header_height
    heights: list[float] = []
    for row_index, row in enumerate(rows):
        cell_lines = [
            wrapped_lines(value, max(10, int(width / 4.75)))
            for value, width in zip(row, widths, strict=True)
        ]
        row_height = max(24, 11 * max(len(lines) for lines in cell_lines) + 8)
        heights.append(row_height)
        pdf.setFillColor(colors.white if row_index % 2 == 0 else PALE)
        pdf.rect(x, y - row_height, sum(widths), row_height, fill=1, stroke=0)
        offset = x
        pdf.setFont(FONT, font_size)
        pdf.setFillColor(INK)
        for lines, width in zip(cell_lines, widths, strict=True):
            for line_index, line in enumerate(lines):
                pdf.drawString(offset + 6, y - 15 - line_index * 10.5, line)
            offset += width
        pdf.setStrokeColor(LINE)
        pdf.line(x, y - row_height, x + sum(widths), y - row_height)
        y -= row_height
    table_height = header_height + sum(heights)
    offset = x
    pdf.setStrokeColor(LINE)
    for width in widths:
        pdf.line(offset, y, offset, y + table_height)
        offset += width
    pdf.line(x + sum(widths), y, x + sum(widths), y + table_height)
    return y


def draw_page_header(pdf: canvas.Canvas, page_number: int) -> None:
    width, height = A4
    pdf.setFillColor(MUTED)
    pdf.setFont(FONT, 8)
    pdf.drawString(48, height - 38, "CASE SERVICE INTEGRATION API")
    pdf.drawRightString(width - 48, height - 38, "v1.4 · Caller callbacks")
    pdf.setStrokeColor(LINE)
    pdf.line(48, height - 47, width - 48, height - 47)
    pdf.drawRightString(width - 48, height - 60, str(page_number))


def draw_page_footer(pdf: canvas.Canvas, page_number: int) -> None:
    width, _height = A4
    pdf.setStrokeColor(LINE)
    pdf.line(48, 34, width - 48, 34)
    pdf.setFillColor(MUTED)
    pdf.setFont(FONT, 7.5)
    pdf.drawString(48, 20, "TestWeb / CasePilot / TestTool")
    pdf.drawRightString(width - 48, 20, str(page_number))


def draw_title(pdf: canvas.Canvas, title: str, endpoint: str) -> float:
    width, height = A4
    y = height - 82
    pdf.setFillColor(BLUE)
    pdf.setFont(FONT, 16)
    pdf.drawString(50, y, title)
    y -= 31
    pdf.setFillColor(BLUE)
    pdf.rect(42, y - 22, width - 84, 38, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont(FONT, 11.2)
    pdf.drawString(50, y - 7, endpoint)
    return y - 44


def section_label(pdf: canvas.Canvas, y: float, text: str) -> float:
    pdf.setFillColor(INK)
    pdf.setFont(FONT, 10.5)
    pdf.drawString(50, y, text)
    return y - 9


def update_cover(pdf: canvas.Canvas) -> None:
    width, _height = A4
    pdf.setFillColor(colors.white)
    pdf.rect(168, 490, 328, 20, fill=1, stroke=0)
    pdf.setFillColor(INK)
    pdf.setFont(FONT, 7.6)
    pdf.drawString(174, 497, "v1.4")
    pdf.setFillColor(PALE)
    pdf.rect(168, 471, 328, 19, fill=1, stroke=0)
    pdf.setFillColor(INK)
    pdf.drawString(174, 478, "2026-09-08")
    pdf.setFillColor(colors.white)
    pdf.rect(54, 452, 442, 20, fill=1, stroke=0)
    pdf.setStrokeColor(LINE)
    pdf.rect(54, 452, 442, 20, fill=0, stroke=1)
    pdf.line(168, 452, 168, 472)
    pdf.setFillColor(INK)
    pdf.drawString(60, 459, "相对 v1.3")
    pdf.drawString(174, 459, "有状态接口增加 callback_url，按操作通知实际调用方")
    pdf.setFillColor(colors.white)
    pdf.rect(42, 327, width - 84, 58, fill=1, stroke=0)
    pdf.setFillColor(BLUE)
    pdf.setFont(FONT, 13)
    pdf.drawString(54, 369, "v1.4 变更说明")
    pdf.setFillColor(PALE)
    pdf.setStrokeColor(BLUE)
    pdf.rect(42, 327, width - 84, 31, fill=1, stroke=1)
    pdf.setFillColor(INK)
    pdf.setFont(FONT, 7.5)
    pdf.drawString(52, 339, "用例生成、Playlist 创建及执行任务等有状态操作保存 callback_url，并向调用方投递状态事件。")


def new_callback_contract_page(page_number: int) -> PdfReader:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    draw_page_header(pdf, page_number)
    y = draw_title(pdf, "2.2 有状态操作回调配置", "CallbackConfig（嵌入异步或有状态接口的 Request Body）")
    y = section_label(pdf, y, "字段定义")
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("callback_url", "URI", "是", "调用方接收状态通知的完整 HTTPS 地址；按本次操作保存，不使用全局固定地址。"),
            ("callback_events", "enum[]", "否", "订阅事件；默认发送该操作全部进度与终态事件。"),
            ("callback_correlation_id", "string", "否", "调用方关联键；原样回传，1..200。"),
        ],
    )
    y -= 18
    y = section_label(pdf, y, "适用接口与事件")
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("case-generation-jobs", "stateful", "是", "generation-status、case-summary。"),
            ("playlist-creation-sessions", "stateful", "是", "playlist-created；可选 playlist-creation-cancelled / expired。"),
            ("playlist task creation", "stateful", "是", "task-status、case-execution-status；可继承 Playlist 创建会话地址。"),
        ],
    )
    y -= 18
    y = section_label(pdf, y, "回调请求 Header")
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("Authorization", "Bearer token", "是", "环境级回调凭证；不得放入 callback_url 查询参数。"),
            ("X-Callback-Event-ID", "UUID", "是", "事件幂等键；同一事件重试保持不变。"),
            ("X-Callback-Event-Type", "string", "是", "事件类型，例如 generation-status 或 playlist-created。"),
            ("X-Callback-Signature", "string", "否", "推荐 HMAC-SHA256(body)；密钥由双方线下配置。"),
        ],
    )
    y -= 18
    pdf.setFillColor(colors.HexColor("#E8F5EF"))
    pdf.setStrokeColor(GREEN)
    pdf.rect(42, y - 91, A4[0] - 84, 83, fill=1, stroke=1)
    pdf.setFillColor(GREEN)
    pdf.setFont(FONT, 7.4)
    notes = [
        "callback_url 必须通过 HTTPS、域名/IP allowlist 与 SSRF 校验；禁止访问环回、链路本地及云元数据地址。",
        "仅 2xx 视为成功；采用指数退避重试。调用方按 X-Callback-Event-ID 幂等处理并返回 204。",
        "重试期间使用创建操作时保存的 callback_url；后续修改全局配置不得改变历史操作的通知目标。",
        "回调失败不回滚业务状态；超过重试上限进入 dead-letter，并保留人工重放能力。",
    ]
    for index, note in enumerate(notes):
        pdf.drawString(52, y - 24 - index * 16, f"{index + 1}. {note}")
    draw_page_footer(pdf, page_number)
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer)


def draw_generation_page(pdf: canvas.Canvas) -> None:
    y = draw_title(pdf, "3.2 启动用例生成", "POST /case-projects/{case_project_id}/case-generation-jobs")
    y = section_label(pdf, y, "Path 参数")
    y = draw_table(
        pdf,
        y=y,
        rows=[("case_project_id", "string", "是", "CP-[0-9]{5,}；生成结果归属的用例项目。")],
    )
    y -= 16
    y = section_label(pdf, y, "Request Body")
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("test_target", "TestTarget|{}", "否", "为空时使用项目目标；非空时 target_type、target_id 必须匹配项目。"),
            ("test_context", "TestContext", "否", "本次生成上下文；与项目上下文合并。"),
            ("model_id", "string", "否", "默认 auto；Mock 模式使用固定 Prompt 与固定结果。"),
            ("callback_url", "URI", "是", "本次生成任务的状态通知地址；保存到 generation job。"),
            ("callback_events", "enum[]", "否", "generation-status、case-summary；默认两者均发送。"),
            ("callback_correlation_id", "string", "否", "调用方关联键；所有生成回调原样返回。"),
        ],
    )
    y -= 16
    y = section_label(pdf, y, "Response 202")
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("case_generation_id", "string", "是", "CASE-SESSION-[0-9]{5,}。"),
            ("case_generation_status", "enum", "是", "初始固定 generating。"),
            ("case_platform_url", "URI", "是", "打开本次生成会话的前端地址。"),
            ("callback_correlation_id", "string|null", "是", "回显调用方关联键。"),
        ],
    )
    y -= 17
    pdf.setFillColor(colors.HexColor("#E8F5EF"))
    pdf.setStrokeColor(GREEN)
    pdf.rect(42, y - 60, A4[0] - 84, 52, fill=1, stroke=1)
    pdf.setFillColor(GREEN)
    pdf.setFont(FONT, 7.4)
    pdf.drawString(52, y - 25, "生成开始、进度变化与终态均通知该 callback_url；approved 后发送完整 case-summary。")
    pdf.drawString(52, y - 41, "兼容期可回退到环境默认地址，但新调用必须显式传入 callback_url。")


def draw_playlist_query_page(pdf: canvas.Canvas) -> None:
    y = draw_title(pdf, "3.4 查询 Playlist 任务详情", "GET /case-projects/{case_project_id}/playlist-tasks")
    y = section_label(pdf, y, "Query 参数")
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("creator", "string", "否", "创建人稳定用户 ID、用户名或邮箱；精确匹配。"),
            ("target_type", "string", "否", "目标类型；与 target_id 组合过滤。"),
            ("target_id", "integer", "否", "目标 ID；提供时必须大于 0。"),
            ("collection_id", "string[]", "否", "可重复；命中任一来源用例集合。"),
            ("playlist_id", "UUID", "否", "查询指定 Playlist。"),
            ("status", "enum[]", "否", "draft | ready | confirmed | running | completed | failed。"),
            ("cursor / limit", "string / int", "否", "游标分页；limit 默认 50，范围 1..100。"),
        ],
    )
    y -= 15
    y = section_label(pdf, y, "Response 200")
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("items", "PlaylistTaskDetail[]", "是", "匹配的 Playlist 及其最新执行任务；无任务时 task 为 null。"),
            ("items[].playlist_id", "UUID", "是", "Playlist 唯一 ID。"),
            ("items[].creator", "UserRef", "是", "id、username、email、display_name。"),
            ("items[].test_target", "TestTarget", "是", "target_type、target_id、target_key、title。"),
            ("items[].case_collections", "CollectionRef[]", "是", "collection_id、name、case_project_id、case_generation_id。"),
            ("items[].cases", "PlaylistCase[]", "是", "case_id、title、stage、test_domain、automation_type、revision_id。"),
            ("items[].task", "TaskSummary|null", "是", "test_task_id、assignee、execution_status、updated_at、progress。"),
            ("items[].case_platform_url", "URI", "是", "打开 Playlist 详情或任务详情页。"),
            ("next_cursor", "string|null", "是", "下一页游标；没有更多数据时为 null。"),
        ],
        font_size=7.1,
    )
    pdf.setFillColor(colors.HexColor("#E8F5EF"))
    pdf.setStrokeColor(GREEN)
    pdf.rect(42, y - 38, A4[0] - 84, 30, fill=1, stroke=1)
    pdf.setFillColor(GREEN)
    pdf.setFont(FONT, 7.5)
    pdf.drawString(52, y - 26, "只读接口：不会创建 Playlist 或执行任务；case_project_id 仍作为租户与目标边界。")


def new_playlist_handoff_page(page_number: int) -> PdfReader:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    draw_page_header(pdf, page_number)
    y = draw_title(pdf, "3.5 创建 Playlist 前端跳转会话", "POST /case-projects/{case_project_id}/playlist-creation-sessions")
    y = section_label(pdf, y, "Request Body")
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("creator", "string", "是", "预填创建人；稳定用户 ID、用户名或邮箱，服务端校验可访问空间。"),
            ("test_target", "TestTarget", "是", "预填目标；target_type 和 target_id 必须匹配 case_project_id。"),
            ("case_collections", "CollectionSeed[]", "是", "至少 1 项；包含 collection_id、case_project_id、case_generation_id。"),
            ("playlist", "PlaylistDraft", "否", "预填 name、description、execution_notes；不在此接口落库。"),
            ("playlist.case_ids", "string[]", "否", "预选用例；必须属于上述集合的有效 approved 快照。"),
            ("callback_url", "URI", "是", "Playlist 创建结果通知地址；按创建会话保存。"),
            ("callback_events", "enum[]", "否", "默认 playlist-created；可订阅 cancelled、expired。"),
            ("callback_context", "object", "否", "request_id、return_url 和调用方透传 metadata。"),
        ],
    )
    y -= 14
    y = section_label(pdf, y, "Response 201")
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("playlist_creation_id", "UUID", "是", "创建会话 ID，同时作为回调关联键和幂等键。"),
            ("creation_status", "enum", "是", "固定 pending_user_action。"),
            ("case_platform_url", "URI", "是", "前端创建页深链；页面通过会话 ID 读取并预填参数。"),
            ("expires_at", "datetime", "是", "带时区；过期后深链返回 410。"),
        ],
    )
    y -= 20
    pdf.setFillColor(colors.HexColor("#E8F5EF"))
    pdf.setStrokeColor(GREEN)
    pdf.rect(42, y - 60, A4[0] - 84, 52, fill=1, stroke=1)
    pdf.setFillColor(GREEN)
    pdf.setFont(FONT, 7.4)
    pdf.drawString(52, y - 25, "本接口只创建一次性前端跳转会话，不直接创建 Playlist。")
    pdf.drawString(52, y - 41, "调用方打开 case_platform_url；用户完成创建后，CasePilot 向保存的 callback_url 回调。")
    draw_page_footer(pdf, page_number)
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer)


def new_playlist_callback_page(page_number: int) -> PdfReader:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    draw_page_header(pdf, page_number)
    y = draw_title(pdf, "3.6 Playlist 创建成功回调", "POST {callback_url}  （示例：/api/case-service/callbacks/playlist-created）")
    y = section_label(pdf, y, "Callback Body")
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("event_id", "UUID", "是", "回调幂等键；重试保持不变。"),
            ("playlist_creation_id", "UUID", "是", "关联 3.5 创建会话。"),
            ("case_project_id", "string", "是", "来源项目 ID。"),
            ("test_target", "TestTarget", "是", "创建时确认的目标。"),
            ("playlist", "PlaylistDetail", "是", "playlist_id、name、creator、case_collections、cases、case_count。"),
            ("created_at", "datetime", "是", "创建成功时间，ISO-8601 且带时区。"),
            ("case_platform_url", "URI", "是", "已创建 Playlist 的详情页。"),
            ("callback_correlation_id", "string|null", "是", "创建会话保存的调用方关联键。"),
            ("callback_context", "object", "是", "创建会话保存的调用方透传上下文。"),
        ],
    )
    y -= 20
    pdf.setFillColor(colors.HexColor("#E8F5EF"))
    pdf.setStrokeColor(GREEN)
    pdf.rect(42, y - 91, A4[0] - 84, 83, fill=1, stroke=1)
    pdf.setFillColor(GREEN)
    pdf.setFont(FONT, 7.4)
    notes = [
        "调用方成功接收后返回 204；CasePilot 按 event_id 重试，调用方必须幂等处理。",
        "callback_correlation_id 和 callback_context 原样回传，用于关联调用方业务记录。",
        "用户取消时不发送 created；订阅后可发送 playlist-creation-cancelled 或 expired。",
        "回调 Body 反映最终保存内容，而不是创建会话中的原始预填草稿。",
    ]
    for index, note in enumerate(notes):
        pdf.drawString(52, y - 24 - index * 16, f"{index + 1}. {note}")
    draw_page_footer(pdf, page_number)
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer)


def draw_playlist_frontend_page(pdf: canvas.Canvas) -> None:
    width, height = A4
    y = height - 82
    pdf.setFillColor(INK)
    pdf.setFont(FONT, 16)
    pdf.drawString(50, y, "4. CasePilot Playlist 创建页接口")
    y -= 31
    pdf.setFillColor(BLUE)
    pdf.setFont(FONT, 12)
    pdf.drawString(50, y, "4.1 读取创建会话与预填参数")
    y -= 25
    pdf.setFillColor(BLUE)
    pdf.rect(42, y - 18, width - 84, 31, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont(FONT, 10.2)
    pdf.drawString(50, y - 6, "GET /api/v1/playlist-creation-sessions/{playlist_creation_id}")
    y -= 37
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("playlist_creation_id", "UUID", "是", "Path；来自 3.5 返回的创建会话 ID。"),
            ("creator", "UserRef", "是", "创建页预填并锁定的创建人。"),
            ("test_target", "TestTarget", "是", "创建页展示的目标信息。"),
            ("case_collections", "CollectionSeed[]", "是", "允许选例的集合和 approved 快照范围。"),
            ("playlist", "PlaylistDraft", "是", "name、description、execution_notes、case_ids 默认值。"),
            ("callback_url", "URI", "是", "调用方通知地址；前端只读且不可修改。"),
            ("callback_context", "object", "是", "调用方 request_id、return_url、metadata；前端不可修改。"),
            ("expires_at", "datetime", "是", "到期后返回 410 playlist_creation_session_expired。"),
        ],
    )
    y -= 18
    pdf.setFillColor(BLUE)
    pdf.setFont(FONT, 12)
    pdf.drawString(50, y, "4.2 创建 Playlist")
    y -= 25
    pdf.setFillColor(BLUE)
    pdf.rect(42, y - 18, width - 84, 31, fill=1, stroke=0)
    pdf.setFillColor(colors.white)
    pdf.setFont(FONT, 10.2)
    pdf.drawString(50, y - 6, "POST /api/v1/playlist-creation-sessions/{playlist_creation_id}/complete")
    y -= 37
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("name", "string", "是", "1..200；空间内允许重名时按产品规则处理。"),
            ("description", "string", "否", "Playlist 说明，默认空字符串。"),
            ("case_ids", "string[]", "是", "至少 1 条；只能选择会话允许集合中的有效用例。"),
            ("execution_notes", "string", "否", "后续创建执行任务时的默认说明。"),
        ],
    )
    y -= 12
    y = section_label(pdf, y, "Response 201")
    y = draw_table(
        pdf,
        y=y,
        rows=[
            ("playlist", "PlaylistDetail", "是", "playlist_id、name、creator、test_target、case_collections、cases、case_count。"),
            ("creation_status", "enum", "是", "固定 created；同一会话重复提交返回同一 Playlist。"),
            ("created_at", "datetime", "是", "创建时间，ISO-8601 且带时区。"),
            ("case_platform_url", "URI", "是", "已创建 Playlist 的详情页。"),
        ],
        font_size=7.1,
    )
    pdf.setFillColor(colors.HexColor("#E8F5EF"))
    pdf.setStrokeColor(GREEN)
    pdf.rect(42, y - 44, width - 84, 35, fill=1, stroke=1)
    pdf.setFillColor(GREEN)
    pdf.setFont(FONT, 7.3)
    pdf.drawString(52, y - 29, "事务提交成功后异步发送 3.6 playlist-created 回调。创建 Playlist 不自动创建执行任务；任务另由 Playlist 页面发起。")


def existing_page_overlay(source_index: int, final_page_number: int) -> PdfReader:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    if source_index in {GENERATION_PAGE_INDEX, REPLACED_PAGE_INDEX, PLAYLIST_FRONTEND_PAGE_INDEX}:
        pdf.setFillColor(colors.white)
        pdf.rect(0, 0, width, height, fill=1, stroke=0)
        draw_page_header(pdf, final_page_number)
        if source_index == GENERATION_PAGE_INDEX:
            draw_generation_page(pdf)
        elif source_index == REPLACED_PAGE_INDEX:
            draw_playlist_query_page(pdf)
        else:
            draw_playlist_frontend_page(pdf)
        draw_page_footer(pdf, final_page_number)
    else:
        pdf.setFillColor(colors.white)
        pdf.rect(width - 215, height - 70, 180, 53, fill=1, stroke=0)
        pdf.setFillColor(MUTED)
        pdf.setFont(FONT, 8)
        pdf.drawRightString(width - 48, height - 38, "v1.4 · Caller callbacks")
        pdf.drawRightString(width - 48, height - 60, str(final_page_number))
        if source_index > 0:
            pdf.setFillColor(colors.white)
            pdf.rect(width - 85, 8, 50, 24, fill=1, stroke=0)
            pdf.setFillColor(MUTED)
            pdf.setFont(FONT, 7.5)
            pdf.drawRightString(width - 48, 20, str(final_page_number))
        if source_index == 0:
            update_cover(pdf)
    pdf.save()
    buffer.seek(0)
    return PdfReader(buffer)


def update_pdf(source: Path, output: Path) -> None:
    register_font()
    reader = PdfReader(source)
    writer = PdfWriter()
    final_number = 1
    for source_index, page in enumerate(reader.pages):
        page.merge_page(existing_page_overlay(source_index, final_number).pages[0])
        writer.add_page(page)
        final_number += 1
        if source_index == CALLBACK_INSERT_AFTER_INDEX:
            writer.add_page(new_callback_contract_page(final_number).pages[0])
            final_number += 1
        if source_index == REPLACED_PAGE_INDEX:
            writer.add_page(new_playlist_handoff_page(final_number).pages[0])
            final_number += 1
            writer.add_page(new_playlist_callback_page(final_number).pages[0])
            final_number += 1
    writer.add_metadata(
        {
            "/Title": "Case Service Integration API v1.4",
            "/Subject": "Caller-specific callback URLs for stateful integration operations",
            "/Author": "CasePilot",
        }
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("wb") as stream:
        writer.write(stream)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    update_pdf(args.source, args.output)


if __name__ == "__main__":
    main()
