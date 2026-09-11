"""Generate the CasePilot v1.4 integration and end-to-end test report."""

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    KeepTogether,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)

OUTPUT = Path("output/pdf/case-service-v1.4-interface-e2e-test-report.pdf")
FONT = "CasePilotSans"
NAVY = colors.HexColor("#102A43")
BLUE = colors.HexColor("#1769E0")
INK = colors.HexColor("#172033")
MUTED = colors.HexColor("#52677D")
PALE = colors.HexColor("#EEF4FB")
GREEN = colors.HexColor("#087F5B")
AMBER = colors.HexColor("#A15C00")
RED = colors.HexColor("#C92A2A")
LINE = colors.HexColor("#CAD7E5")


def register_font() -> None:
    pdfmetrics.registerFont(
        TTFont(FONT, "/System/Library/Fonts/Supplemental/Arial Unicode.ttf")
    )


def header_footer(canvas, doc) -> None:
    canvas.saveState()
    width, height = A4
    canvas.setFont(FONT, 8)
    canvas.setFillColor(MUTED)
    canvas.drawString(18 * mm, height - 13 * mm, "CASEPILOT v1.4 INTERFACE TEST REPORT")
    canvas.drawRightString(width - 18 * mm, height - 13 * mm, "2026-09-10")
    canvas.setStrokeColor(LINE)
    canvas.line(18 * mm, height - 16 * mm, width - 18 * mm, height - 16 * mm)
    canvas.line(18 * mm, 13 * mm, width - 18 * mm, 13 * mm)
    canvas.drawString(18 * mm, 8 * mm, "TestWeb -> CasePilot -> TestTool -> Callback")
    canvas.drawRightString(width - 18 * mm, 8 * mm, f"{doc.page}")
    canvas.restoreState()


def p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(text, style)


def table(data, widths, body, header, row_colors=None) -> Table:
    rows = [[p(str(cell), header if index == 0 else body) for cell in row] for index, row in enumerate(data)]
    result = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
    commands = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for index in range(1, len(rows)):
        commands.append(("BACKGROUND", (0, index), (-1, index), colors.white if index % 2 else PALE))
    for row, color in (row_colors or {}).items():
        commands.append(("TEXTCOLOR", (0, row), (-1, row), color))
    result.setStyle(TableStyle(commands))
    return result


def build() -> None:
    register_font()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    styles = getSampleStyleSheet()
    title = ParagraphStyle("title", fontName=FONT, fontSize=24, leading=31, textColor=NAVY, spaceAfter=12)
    subtitle = ParagraphStyle("subtitle", fontName=FONT, fontSize=10, leading=16, textColor=MUTED, spaceAfter=16)
    h1 = ParagraphStyle("h1", fontName=FONT, fontSize=16, leading=22, textColor=BLUE, spaceBefore=12, spaceAfter=10)
    h2 = ParagraphStyle("h2", fontName=FONT, fontSize=11, leading=16, textColor=NAVY, spaceBefore=9, spaceAfter=6)
    body = ParagraphStyle("body", fontName=FONT, fontSize=8.2, leading=12.3, textColor=INK)
    small = ParagraphStyle("small", fontName=FONT, fontSize=7.2, leading=10.5, textColor=INK)
    header = ParagraphStyle("header", fontName=FONT, fontSize=7.5, leading=10, textColor=colors.white)
    badge = ParagraphStyle("badge", fontName=FONT, fontSize=11, leading=15, textColor=colors.white, alignment=TA_CENTER)
    warning = ParagraphStyle("warning", fontName=FONT, fontSize=8.2, leading=12, textColor=RED)

    doc = BaseDocTemplate(
        str(OUTPUT), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
        topMargin=22 * mm, bottomMargin=18 * mm, title="CasePilot v1.4 接口与全链路测试报告",
        author="Codex",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="body")
    doc.addPageTemplates(PageTemplate(id="report", frames=[frame], onPage=header_footer))

    story = [
        Spacer(1, 10 * mm),
        p("CasePilot v1.4<br/>接口与全链路测试报告", title),
        p("重点：接口调用创建 Playlist、回调状态完整性、TestWeb / CasePilot / TestTool 闭环", subtitle),
        Table(
            [[p("自动化测试", badge), p("真实链路", badge), p("最终结论", badge)],
             [p("97 项通过", h2), p("浏览器 + API + PostgreSQL + Callback", h2), p("主流程通过，发现 6 项待补全", h2)]],
            colWidths=[doc.width / 3] * 3,
            style=TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), BLUE),
                ("BACKGROUND", (0, 1), (-1, 1), PALE),
                ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]),
        ),
        p("1. 测试范围与环境", h1),
        table([
            ["项目", "结果 / 值"],
            ["测试日期", "2026-09-10，Asia/Shanghai"],
            ["代码基线", "main @ c6e8842 + 本地未提交 v1.4 修改"],
            ["运行环境", "Docker Compose：Web :3000、API :8000、PostgreSQL、Redis、Celery Agent"],
            ["数据库迁移", "20260910_0022 (head)"],
            ["接口模式", "CASE_SERVICE_MOCK_MODE=true；回调通过同网络独立 HTTP 接收器实收"],
        ], [42 * mm, 132 * mm], body, header),
        p("2. 全流程动线", h1),
        table([
            ["阶段", "接口 / 动作", "验证结果"],
            ["1. 建项目", "POST /case-projects", "CP-00027"],
            ["2. 生成用例", "POST /case-projects/{id}/case-generation-jobs", "CASE-SESSION-00051；L0/L2/L4"],
            ["3. 生成回调", "POST {callback_url}", "generating、approved、case-summary 全部 delivered"],
            ["4. 创建跳转会话", "POST /case-projects/{id}/playlist-creation-sessions", "pending_user_action；返回前端深链"],
            ["5. 前端预填", "GET /api/v1/playlist-creation-sessions/{id}", "名称、集合、L0/L2/L4 三条用例正确"],
            ["6. 完成 Playlist", "POST .../{playlist_creation_id}/complete", "Playlist af735a4c...；3 cases"],
            ["7. Playlist 回调", "POST {callback_url}", "playlist-created delivered；关联 ID、上下文存在"],
            ["8. 查询 Playlist", "GET /case-projects/{id}/playlist-tasks", "creator/target/collection/playlist/status 过滤通过"],
            ["9. TestTool 执行", "查询 -> claim -> heartbeat -> PATCH", "TASK-00019 / TASK-00021 completed"],
            ["10. 执行回调", "task-status + case-execution-status", "双事件均 delivered"],
        ], [27 * mm, 87 * mm, 60 * mm], small, header),
        p("3. Playlist 创建接口专项", h1),
        table([
            ["检查点", "实际证据", "状态"],
            ["creator", "用户名 e2e-playlist-8f206e987d 成功解析至账号", "通过"],
            ["test_target", "fr_test / 150079209 与 CP-00027 一致", "通过"],
            ["case_collections", "项目 + approved generation 解析至唯一集合", "通过"],
            ["playlist.case_ids", "CP-00027-CASE-001/002/003，分别 L0/L2/L4", "通过"],
            ["callback 配置", "URL、events、correlation_id、callback_context 持久化", "通过"],
            ["深链", "playlist_creation_id 查询参数可登录后恢复会话", "通过"],
            ["前端预填", "名称、集合和三条用例均已勾选", "通过（见动线截图）"],
            ["完成幂等", "重复 complete 返回相同 playlist_id 和 3 条用例", "通过"],
            ["数据库", "creation_status=created；playlist_case_memberships=3", "通过"],
        ], [44 * mm, 96 * mm, 34 * mm], small, header),
        p("关键响应", h2),
        p("playlist_creation_id=0115338b-3469-432e-8477-87e59a151ad2；playlist_id=af735a4c-350c-4655-a00e-aceec1e42e61；creation_status=created；case_count=3。", body),
        p("4. 回调状态正确性", h1),
        table([
            ["聚合对象", "事件", "实收次数", "状态", "关键字段"],
            ["CASE-SESSION-00051", "generation-status", "2", "delivered", "generating -> approved；event_id；correlation_id"],
            ["CASE-SESSION-00051", "case-summary", "1", "delivered", "完整 cases 对象；L0/L2/L4"],
            ["Playlist session", "playlist-created", "1", "delivered", "playlist、creator、context、correlation_id"],
            ["TASK-00021", "task-status", "3", "delivered", "confirmed、running、completed"],
            ["TASK-00021", "case-execution-status", "2", "delivered", "not_run 初始快照、passed 终态"],
        ], [39 * mm, 42 * mm, 20 * mm, 25 * mm, 48 * mm], small, header),
        p("回调协议核对", h2),
        table([
            ["协议项", "验证"],
            ["Authorization", "Bearer test-web-local 实收"],
            ["X-Callback-Event-ID", "存在且与 Body event_id 一致"],
            ["X-Callback-Event-Type", "与 generation-status / case-summary / playlist-created / task-status / case-execution-status 一致"],
            ["幂等重试", "event_id 存储于 callback_deliveries；同一 delivery 重试不重建事件"],
            ["失败策略", "不可解析地址进入 pending，attempts 增长且记录 last_error；指数退避生效"],
        ], [52 * mm, 122 * mm], body, header),
        p("5. TestTool 执行闭环", h1),
        table([
            ["检查点", "证据", "状态"],
            ["当前用户隔离", "X-TestTool-User-ID 仅返回绑定账号任务", "通过"],
            ["组合查询", "target_type、target_id、project、generation、case、request", "通过"],
            ["指定任务领取", "worker_id=e2e-worker-macos-001", "通过"],
            ["租约", "lease_seconds=60；heartbeat 延长至 120 秒", "通过"],
            ["结果回传", "L0=passed、L2=failed、L4=blocked", "通过"],
            ["更新幂等", "重复 update_id 返回完全相同响应", "通过"],
            ["最终 UI", "2 个任务均 100%；三用例任务为 1 通过 / 1 失败 / 1 堵塞", "通过（见截图）"],
        ], [44 * mm, 96 * mm, 34 * mm], small, header),
        p("6. 自动化测试汇总", h1),
        table([
            ["测试层", "结果", "覆盖重点"],
            ["API", "54 passed", "鉴权、Schema、Playlist、TestWeb/TestTool 集成、Outbox"],
            ["Agent", "38 passed", "生成、流式、知识库、回调订阅与目的地址"],
            ["Web", "5 passed", "构建、服务端渲染、用例导入；ESLint 和 TypeScript 通过"],
            ["总计", "97 passed", "pnpm check 全量通过"],
        ], [35 * mm, 32 * mm, 107 * mm], body, header),
        p("7. 发现并已修复", h1),
        table([
            ["问题", "修复与复验"],
            ["case-execution-status 已允许订阅但未实际发送", "已在确认和执行更新时投递；TASK-00021 实收 2 次并 delivered；新增自动化断言。"],
            ["Web 开发服务缓存旧客户端模块", "重启 Web 服务后深链自动进入 Playlist 创建页；最终控制台无 error/warn。"],
        ], [62 * mm, 112 * mm], body, header),
        p("8. 仍有遗漏 / 上线前建议", h1),
        table([
            ["优先级", "遗漏", "影响 / 建议"],
            ["P0", "POST /tasks 未消费调用方已创建的 playlist_id", "当前会再次创建内部 Playlist，实测出现重复 FR-E2E execution。建议任务创建明确接收 playlist_id 或 playlist_creation_id，并冻结该 Playlist。"],
            ["P1", "playlist-created 回调中的 case_generation_id 丢失", "创建会话指定 CASE-SESSION-00051，但最终 callback 的 case_collections.case_generation_id 为 null。应从创建会话保留快照来源。"],
            ["P1", "description / execution_notes 未进入正式 Playlist 与回调", "complete 接口接收但 Playlist 模型无对应字段，回调无法还原最终输入。建议持久化并在 PlaylistDetail 返回。"],
            ["P1", "playlist-creation-cancelled 只在 enum 中声明", "没有取消接口或前端取消回调；订阅该事件不会收到通知。"],
            ["P1", "expired 回调不是主动调度", "当前仅在过期后再次 GET 会话时触发；无人访问就不会通知。建议后台定时扫描。"],
            ["P2", "callback_url 缺少生产级出站安全策略", "建议增加 HTTPS 强制、域名 allowlist、防 SSRF 和 HMAC 签名。"],
        ], [18 * mm, 60 * mm, 96 * mm], small, header, {1: RED, 2: AMBER, 3: AMBER, 4: AMBER, 5: AMBER}),
        Spacer(1, 4 * mm),
        KeepTogether([
            p("最终结论", h1),
            p("主流程已经可以完成：TestWeb 发起生成和 Playlist 创建 -> CasePilot 前端预填并保存 -> TestTool 按当前用户领取执行 -> 结果与状态回调到调用方。生成、Playlist 成功、任务和用例执行状态均已实际投递。当前不建议将接口标记为“无遗漏”：任务与已创建 Playlist 的绑定、取消/主动过期事件以及部分 Playlist 字段仍需补全。", body),
            Spacer(1, 3 * mm),
            p("截图证据：本次交付会话中已附“接口创建 Playlist 会话并自动预填”“L0/L2/L4 用例预填”“TestTool 全链路执行结果”三张真实浏览器截图。", warning),
        ]),
    ]
    doc.build(story)


if __name__ == "__main__":
    build()
