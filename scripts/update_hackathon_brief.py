from __future__ import annotations

import argparse
from pathlib import Path

from docx import Document
from docx.enum.section import WD_SECTION_START
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


REPO_ROOT = "<repo-root>"


def set_run_font(run, name="Microsoft YaHei", size=None, bold=None, italic=None, color=None):
    run.font.name = name
    run._element.get_or_add_rPr().rFonts.set(qn("w:ascii"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:hAnsi"), name)
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), name)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold
    if italic is not None:
        run.italic = italic
    if color:
        run.font.color.rgb = RGBColor.from_string(color)


def set_cell_shading(cell, fill: str):
    tc_pr = cell._tc.get_or_add_tcPr()
    shading = tc_pr.find(qn("w:shd"))
    if shading is None:
        shading = OxmlElement("w:shd")
        tc_pr.append(shading)
    shading.set(qn("w:fill"), fill)


def set_cell_width(cell, width_dxa: int):
    tc_pr = cell._tc.get_or_add_tcPr()
    tc_w = tc_pr.find(qn("w:tcW"))
    if tc_w is None:
        tc_w = OxmlElement("w:tcW")
        tc_pr.append(tc_w)
    tc_w.set(qn("w:w"), str(width_dxa))
    tc_w.set(qn("w:type"), "dxa")


def set_table_geometry(table, widths_dxa: list[int]):
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = False
    tbl_pr = table._tbl.tblPr
    layout = tbl_pr.find(qn("w:tblLayout"))
    if layout is None:
        layout = OxmlElement("w:tblLayout")
        tbl_pr.append(layout)
    layout.set(qn("w:type"), "fixed")
    tbl_w = tbl_pr.find(qn("w:tblW"))
    if tbl_w is None:
        tbl_w = OxmlElement("w:tblW")
        tbl_pr.append(tbl_w)
    tbl_w.set(qn("w:w"), str(sum(widths_dxa)))
    tbl_w.set(qn("w:type"), "dxa")
    grid = table._tbl.tblGrid
    for child in list(grid):
        grid.remove(child)
    for width in widths_dxa:
        col = OxmlElement("w:gridCol")
        col.set(qn("w:w"), str(width))
        grid.append(col)
    for row in table.rows:
        for index, cell in enumerate(row.cells):
            set_cell_width(cell, widths_dxa[index])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_after = Pt(3)
                paragraph.paragraph_format.space_before = Pt(3)


def style_table_text(table, header_rows: int = 1):
    for row_index, row in enumerate(table.rows):
        for cell in row.cells:
            if row_index < header_rows:
                set_cell_shading(cell, "D9EAF7")
            else:
                set_cell_shading(cell, "F7FAFC")
            for paragraph in cell.paragraphs:
                for run in paragraph.runs:
                    set_run_font(run, size=9.5, bold=row_index < header_rows, color="1F4D78" if row_index < header_rows else "263238")


def add_para(doc, elements, text="", style="Normal", *, bold_prefix=None, italic=False, align=None, after=6):
    paragraph = doc.add_paragraph(style=style)
    if align is not None:
        paragraph.alignment = align
    paragraph.paragraph_format.space_after = Pt(after)
    paragraph.paragraph_format.line_spacing = 1.18
    if bold_prefix and text.startswith(bold_prefix):
        first = paragraph.add_run(bold_prefix)
        set_run_font(first, bold=True)
        rest = paragraph.add_run(text[len(bold_prefix):])
        set_run_font(rest, italic=italic)
    else:
        run = paragraph.add_run(text)
        set_run_font(run, italic=italic)
    elements.append(paragraph._p)
    return paragraph


def add_bullet(doc, elements, text):
    return add_para(doc, elements, text, style="List Bullet", after=3)


def add_number(doc, elements, text):
    return add_para(doc, elements, text, style="List Number", after=3)


def add_heading(doc, elements, text, level=1):
    paragraph = doc.add_paragraph(text, style=f"Heading {level}")
    paragraph.paragraph_format.keep_with_next = True
    paragraph.paragraph_format.space_before = Pt(12 if level == 1 else 8)
    paragraph.paragraph_format.space_after = Pt(5)
    for run in paragraph.runs:
        set_run_font(run, size=16 if level == 1 else 12.5, bold=True, color="2E74B5")
    elements.append(paragraph._p)
    return paragraph


def add_front_matter(doc: Document):
    elements = []

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(5)
    title.paragraph_format.line_spacing = 1.0
    run = title.add_run("江湖 Online")
    set_run_font(run, size=26, bold=True, color="1F4D78")
    elements.append(title._p)

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    subtitle.paragraph_format.space_after = Pt(12)
    run = subtitle.add_run("项目说明、系统 README 摘要与本地运行指南")
    set_run_font(run, size=14, bold=True, color="4F6B82")
    elements.append(subtitle._p)

    lead = doc.add_paragraph()
    lead.alignment = WD_ALIGN_PARAGRAPH.CENTER
    lead.paragraph_format.space_after = Pt(15)
    lead.paragraph_format.line_spacing = 1.2
    run = lead.add_run("先看这一部分可以快速理解：系统是什么、仓库里有什么、如何真实启动、如何配置模型，以及如何验证一次多 Agent 生产流。")
    set_run_font(run, size=10.5, bold=True, color="38556B")
    elements.append(lead._p)

    table = doc.add_table(rows=1, cols=3)
    set_table_geometry(table, [1700, 3600, 4060])
    headers = ["项目项", "说明", "当前入口 / 默认值"]
    for cell, text in zip(table.rows[0].cells, headers):
        cell.text = text
    rows = [
        ("项目名称", "Agent Arena；中文产品名为“江湖 Online”。", "仓库根目录 README.md"),
        ("产品定位", "知识驱动、需求驱动的拟人化 Agent 组织与生产流平台。", "事项 → 团队 → 生产流 → 事件现场 → 交付"),
        ("本地 Web", "Vue 3 + TypeScript + Vite 开发前端。", "http://127.0.0.1:5173"),
        ("本地 API", "FastAPI 后端与真实运行接口。", "http://127.0.0.1:8003；/docs"),
        ("Docker Web", "FastAPI 同源托管前端生产构建。", "http://localhost:8000"),
        ("运行原则", "真实 LLM、真实 Agent 调用、真实工具与文件产物；不以 Mock 结果作为验收。", "未配置模型时只可浏览，执行会明确失败"),
    ]
    for values in rows:
        cells = table.add_row().cells
        for cell, text in zip(cells, values):
            cell.text = text
    set_table_geometry(table, [1700, 3600, 4060])
    style_table_text(table)
    elements.append(table._tbl)

    add_heading(doc, elements, "一、这套系统是什么", 1)
    add_para(doc, elements, "江湖 Online 不是一个把多个模型简单串起来的聊天页面，而是一个让社会中不同身份的人只需表达需求并提供知识，就能构建可运行生产组织的平台。平台把大江湖、小江湖、Agent、团队、知识、生产流和事件现场连接起来，让 Agent 在真实任务中讨论、协作、争辩、对抗、执行工具、提交产物并接受独立裁判。", after=6)
    add_para(doc, elements, "系统的核心对象不是聊天记录，而是可追溯的步骤产物和事件证据。每个节点都可以绑定一个 Agent 团队，节点之间通过 DAG 依赖、并行分支和有限 Loop 传递产物；失败会记录原因并进入版本化重试或定向返工。", after=6)

    add_heading(doc, elements, "二、当前 README 的核心能力摘要", 1)
    for text in [
        "大江湖与小江湖：大江湖保存组织公共知识、规则和人物资源，小江湖可以独立承接事项，也可以在授权范围内继承公共背景。",
        "可复用人物和团队：Agent 具有中文姓名、职业身份、能力、人格、记忆、技能、运行底座和组织关系；团队可以被保存、复用、复制和调整。",
        "事项驱动的组织形成：用户提出具体事项后，平台先判断现有组织是否适配；不适配时只给出缺口和候选，不会未经确认直接创建人物或团队。",
        "生产流工厂：平台支持复用现有 WorkflowVersion、基于已有版本创建副本优化，或根据需求生成新的 DAG；生产流中的节点可以串行、并行、返工和有限循环。",
        "真实执行现场：每个 Run 记录公开进度、节点状态、Agent 发言、工具、文件、命令、测试、产物、失败原因、人工介入和恢复结果；私有思维链不向其他 Agent 或用户公开。",
        "真实开发交付：工程节点可以在隔离工作区中真实写代码、执行命令、运行测试和提交工程产物；平台不把“生成文档”冒充为“完成开发”。",
        "知识空间与 RAG：用户可以上传文件或目录，平台保存来源、解析状态、索引、知识片段和关系图谱，并按组织、团队、任务和 Agent 权限进行选择性披露。",
        "大江湖隔离：组织、团队、Agent、Workflow、Run、Task、Artifact、Event 和介入记录都带有组织归属；事件现场按大江湖隔离，历史执行版本不会串到其他江湖。",
    ]:
        add_bullet(doc, elements, text)

    add_heading(doc, elements, "三、仓库与文档 README 导航", 1)
    add_para(doc, elements, "提交或拉取仓库后，建议按下面顺序阅读。所有路径均相对于仓库根目录。", after=5)
    for text in [
        "README.md：项目定位、产品理念、Docker 部署、本地开发、模型配置、打包和安全边界。",
        "docs/README.md：过程文档总索引，区分调研、需求、决策、设计、实现和路线图。",
        "docs/01-research/：OpenClaw、MiroFish、ChatDev 及相似开源多 Agent 方案的调研和技术选型。",
        "docs/02-requirements/：产品愿景、用户需求、系统需求和首个生产流的确认内容。",
        "docs/03-decisions/：平台优先、真实运行、领域运行时和 Agent Adapter 等关键 ADR。",
        "docs/04-design/：系统架构、Agent 协议、Workflow 工厂、客户端信息架构、OpenClaw Adapter 和详细设计。",
        "docs/05-implementation/：MVP 纵向切片、协作与对抗行为、真实运行和验证记录。",
        "examples/production-flow-comparison/：完整生产流对照案例，比较单 Agent 基线与多 Agent 协作/对抗流。",
    ]:
        add_bullet(doc, elements, text)

    add_heading(doc, elements, "四、本地运行说明（Windows PowerShell）", 1)
    add_para(doc, elements, "以下命令在仓库根目录执行。首次安装只需执行一次；后续启动可以直接运行 npm run dev。", after=5)
    add_number(doc, elements, "准备环境：Node.js 22+、Python 3.13+，并确保 npm 可用。")
    add_number(doc, elements, "创建 Python 环境：python -m venv .venv")
    add_number(doc, elements, "安装后端依赖：.\\.venv\\Scripts\\python.exe -m pip install -r server\\requirements.txt")
    add_number(doc, elements, "安装前端依赖：npm install；npm --prefix client install")
    add_number(doc, elements, "启动开发服务：npm run dev")
    add_para(doc, elements, "启动后：浏览器打开 http://127.0.0.1:5173；后端 API 为 http://127.0.0.1:8003；接口文档为 http://127.0.0.1:8003/docs。健康检查地址为 http://127.0.0.1:8003/api/health。", after=6)

    add_heading(doc, elements, "五、真实 LLM 配置与运行边界", 1)
    add_para(doc, elements, "平台的生产流验收必须使用真实模型调用。模型配置可以通过 Web 的“模型与凭据”页面保存，也可以通过不纳入 Git 的 .env.docker 注入。文档和仓库不得写入真实 API Key、Token 或个人数据。", after=6)
    add_para(doc, elements, "Docker 环境变量示例（只填写自己的值，不要提交该文件）：", bold_prefix="Docker 环境变量示例（只填写自己的值，不要提交该文件）：", after=3)
    for text in [
        "ANTHROPIC_BASE_URL=https://your-anthropic-compatible-endpoint.example.com",
        "ANTHROPIC_AUTH_TOKEN=your-token",
        "ANTHROPIC_DEFAULT_SONNET_MODEL=your-model-id",
        "JIANGHU_DATA_DIR=./.data",
    ]:
        add_bullet(doc, elements, text)
    add_para(doc, elements, "模型未配置或服务不可达时，平台应返回可读的失败原因和恢复入口，不应生成虚假的成功产物。真实执行产生的 Token、费用、时延、工具证据和产物版本会进入事件现场。", after=6)

    add_heading(doc, elements, "六、Docker 运行说明", 1)
    add_number(doc, elements, "复制环境模板：cp .env.docker.example .env.docker（PowerShell 可手动复制后编辑）。")
    add_number(doc, elements, "构建并启动：docker compose --env-file .env.docker up -d --build")
    add_number(doc, elements, "查看状态：docker compose ps；查看日志：docker compose logs -f jianghu-online")
    add_number(doc, elements, "停止服务：docker compose down")
    add_para(doc, elements, "Docker 默认将宿主机 .data 作为持久化目录，但 .data、数据库、知识文件、运行产物、加密密钥和模型凭据不会进入 Git、镜像层或源码包。不要删除 .data/.jianghu-secret.key，否则已保存的模型 Token 将无法解密。", after=6)

    add_heading(doc, elements, "七、最小真实验证路径", 1)
    for text in [
        "进入 Web 后先选择一个大江湖；未显式选择时不应被自动送入其他业务江湖。",
        "在组织页面检查人物、团队和组织公共知识；上传知识后确认解析、索引和图谱状态。",
        "输入具体事项，先让平台判断已有团队是否适配；若出现能力缺口，确认后再生成 Agent 或团队。",
        "选择可复用 WorkflowVersion，或复制一个版本进行调整；检查 DAG 节点、前置产物和每个节点绑定的团队。",
        "确认后创建并启动真实 Run；在事件现场查看 Agent 发言、工具、文件、命令、测试、产物和失败原因。",
        "若执行失败，从同一事件的执行版本入口重试；失败证据和历史版本应保留，不能新增一个看起来完全无关的事件。",
        "完成后检查最终 Artifact、独立裁判结论、测试证据和可下载的真实工程产物。",
    ]:
        add_bullet(doc, elements, text)

    add_heading(doc, elements, "八、测试与验收命令", 1)
    for text in [
        "后端测试：.\\.venv\\Scripts\\python.exe -m pytest -q -p no:cacheprovider",
        "前端构建：npm --prefix client run build",
        "完整测试：npm test",
        "Docker 打包：.\\scripts\\package-docker.ps1（脚本会扫描凭据，并排除 .data）",
    ]:
        add_bullet(doc, elements, text)
    add_para(doc, elements, "验收重点不是页面是否出现一组卡片，而是能否用真实 LLM 和真实并行 Agent 从事项进入组织适配、生产流执行、真实产物、测试验证、裁判和失败恢复的端到端闭环。", after=6)

    add_heading(doc, elements, "九、当前文档与案例的关系", 1)
    add_para(doc, elements, "后续正文仍保留本项目的愿景、创新点、New API 语义路由案例、界面运行证据和评测计划。新增前置部分是使用说明和仓库导航，不替代正文中的案例叙事；正文中的效果指标继续以真实对照实验为准，不把预期目标写成已经验证的结果。", after=6)

    page_break = doc.add_paragraph()
    page_break.paragraph_format.space_after = Pt(0)
    page_break.add_run().add_break(WD_BREAK.PAGE)
    elements.append(page_break._p)

    body = doc._body._element
    for element in reversed(elements):
        body.insert(0, element)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    doc = Document(args.input)
    add_front_matter(doc)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    doc.save(args.output)
    print(args.output)


if __name__ == "__main__":
    main()
