<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="archive/brand/guixu-mark.svg">
    <img src="archive/brand/guixu-mark-dark.svg" alt="归墟" width="120">
  </picture>
</p>

<h1 align="center">归墟 · 数据处理 Agent</h1>

用自然语言完成数据的查询、新增、修改、删除、导入、导出、检查和报表生成。

一个桌面窗口就是一张工作台：左栏资产与会话，中栏对话流（对话 / 轨迹切换），右栏产物。工具调用、思考过程、确认卡片都摊在对话里，每一步都看得见。

- 输入「上个月新增了多少条记录」→ 自动生成 SQL、执行、回答
- 输入「删掉测试数据」→ 搜索候选、确认、软删除（默认 7 天内可恢复）
- 输入「所有计数加 1」→ 按规则重塑、展示改前改后、确认执行
- 输入「加一列 priority，表示优先级」→ 改表结构
- 输入「从 data/新数据.xlsx 导入」→ 扫描差异、确认、导入
- 输入「给我一份上周周报，和上上周对比」→ 统计、画图、算环比、生成 PDF

## 特性

**WebUI**
- 三栏布局 + SSE 流式：思考、工具调用、工具返回、回答边跑边出
- 工具调用卡片化：参数、完整返回、耗时、状态
- 产物进侧栏并可预览：Excel 表格、PDF 内嵌、Word 段落、Markdown 渲染、纯文本等宽
- 确认卡片带 diff：候选清单、影响行数、改前改后
- 会话持久化 + 上下文压缩 + 对话归档
- 设置页：27 个参数在线可调，改完即生效（其中 16 个在开发者模式里，含文档库的 5 个检索数值）

**数据库概览（数据字典）**
- 表结构、字段类型、必填从库里现读；中文含义由你标
- 字典只存"用户可改的那部分"，所以数据库加列改类型它不会过期

**文档库（RAG）**
- 上传 PDF / Word / txt / md：自动解析、分块、向量化
- 扫描件 PDF 交给当前多模态模型逐页读图；模型不支持图片会明确报错
- 检索是一个工具：制度、手册、规范这类资料由它查；表数据仍走 SQL
- 文档库页：上传、原文预览（全文 + 分块）、重建索引、检索测试
- 删除是软删：进回收站，保留期内可恢复；上传/删除/恢复都写审计
- 切片原文归 SQLite（唯一真源），FAISS 只是派生索引；reranker 留接口，权重需自行导出 ONNX

**模型接入**
- 多套模型配置存成卡片，随时切换（测试的、生产的、公司的各存一把 key）
- 供应商预设 + 连接测试；配置与 key 分开存，key 不进版本库

**数据处理**
- 完整 CRUD：查询 / 新增 / 修改 / 删除，支持单条和批量
- Excel 导入：扫描差异（新记录 / 冲突 / 软删除），三阶段确认，支持追问详情
- Excel 导出：中文列名、日期格式化、中文文件名
- 规则重塑：按自然语言规则批量改值（"所有计数加 1"、"某一列去掉首尾空格"）
- 加列改结构：加字段并顺手登记它的中文含义
- 日/周/月报：统计 + 图表 + 环比 + LLM 概述，输出 PDF
- 文档产物：PDF / Word / md / txt，写完直接进侧栏；说「收进文档库」才复制一份进语料
- 安全删除：双层确认 + 软删除（默认 7 天可恢复）

**工程底座**
- 完整审计：所有写操作记录进库（和写入同一个事务）
- 多层防护：LLM 重试、熔断、行数上限、SQL 超时、Loop 超时
- 可观测：每次问答的完整链路写入 `logs/traces.jsonl`
- 评测驱动：178 条用例，九个维度

## 评测

**178 条，九个维度**：功能正确性、写操作、确认与中断、注入与越权、边界与畸形、韧性、诚实性、可观测与完整性、文档库与产物。

- **离线 138 条**：不调模型，秒级。闸门绕过、路径穿越、畸形参数、并发、审计与快照、文档入库/软删/恢复/清理、扫描件、四种产物写出
- **Agent 40 条**：真调模型。20 个工具、确认/取消/跳过、提示注入、文档检索、不编造

```bash
uv run python eval/run.py --suite offline   # 免费，随便跑
uv run python eval/run.py --suite agent     # 需要可用的 key
```

期望值从 fixture 现算，不硬编码；每条用例重跑一个临时库，**不碰 `data/guixu.db`**。
攻击用例的判据是「拒绝 + 数据零变化 + 该保护的还在」三件事同时成立。

第一轮跑出 117/141，抓到的 10 个缺陷全部修掉；加入文档库、产物与裸表兜底后，
离线 **138/138**；Agent 40 条在最近一次全量里 **39 通过**，1 条因模型偶发生成
被只读闸门拒绝的 SQL（单独复跑通过），详见 [eval/README.md](eval/README.md#评测驱动修掉的缺陷)
（新库快照表未初始化、规则变换必崩、会话 id 穿越、Markdown XSS 等，
逐条对照见 [eval/README.md](eval/README.md#评测驱动修掉的缺陷)）。

## 架构

```
[桌面窗口] pywebview + 系统 WebView2（前端 Vue 3 + marked，无构建步骤）
   ↓ HTTP / SSE
[API 层] api.py（FastAPI）
   ├─ /chat                    SSE 流式：start / think / tool_call / tool_result
   │                           / compact / answer / pending / final
   ├─ /settings /configs       参数配置、模型配置卡片、连接测试
   ├─ /schema                  数据字典（读表结构 + 写中文含义）
   ├─ /sessions                会话 CRUD
   └─ /upload /download /files /preview   文件进出
   ↓
[Agent 层] agent.py（Loop：决策 + 熔断 + 超时 + 上下文压缩）
   ↓
[工具层] tools.py（菜单 + 传话筒，20 个工具）
   ├─ search_documents                  检索文档库（RAG 的动作）
   ├─ query_database                    查询表
   ├─ request_create / request_update   新增 / 修改（新值由用户给出）
   ├─ transform_data                    修改（新值由规则算出）
   ├─ create_table / add_column / alter_column / drop_column / drop_table   结构
   ├─ request_delete / request_restore  软删除 / 恢复
   ├─ request_import / export_to_excel  导入 / 导出
   ├─ write_document / generate_report  文档产物 / 统计报告
   ├─ list_deleted / list_snapshots / rollback_version   看与回退
   └─ ask_user                          信息不足时挂起提问
   ↓
[服务层] services/（业务逻辑，按表构建上下文）
   ├── query / create / update / delete / restore / pending
   ├── import / export / transform / structure
   ├── document（PDF / Word / md / txt 产物）
   └── report（charts + render + templates）
   ↓
[数据层] storage.py   表 · 软删除隔离 · 表定义 · 关系
        snapshot.py  快照 · 回滚（破坏性操作前的退路）
        runner.py    跑 SQL：连接 · 事务 · 超时
        rag/         文档解析 · 分块 · embedding · FAISS · 检索
   └─ SQLite 单文件（切片真源） + FAISS 内存索引（派生）

[横切] guard（安全）· trace（可观测）· audit（审计）· cleanup（清理）
```

**设计原则**：
- Agent 层薄、工具层薄、服务层厚
- 工具是 Agent 与世界交互的途径，不是限制
- 确认机制在 Loop 外部处理（跨轮次状态）
- 多表地基已就绪：工具带 `table_name`、上下文按表构建、schema 按表渲染

## 快速开始

### 环境要求

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)

**不需要装数据库。** 数据存在一个 SQLite 文件里，备份就是复制它。

报告中转 PDF 用的是 Playwright 自带的 Chromium，不依赖系统浏览器 —— 装过之后到哪都一样。

### 安装

```bash
git clone https://github.com/niannian-Gzh/GuiXu-DataPilot.git
cd GuiXu-DataPilot
uv sync

# 下载报告 / PDF 产物渲染用的 Chromium（约 115MB，只需一次）
uv run playwright install chromium

# 下载文档库 embedding 权重（约 91MB，只需一次）
uv run python scripts/fetch_model.py
```

embedding 权重放在 `models/`（不进版本库——每次 clone 背 91MB 二进制不值得）；
默认走 hf-mirror，不通就 `--source huggingface`。

### 配置

`.env` 里放模型的 key（首次启动会迁移到 `secrets.json`，二者都不进版本库）：

```
DEEPSEEK_API_KEY=你的key
```

`config.yaml` **可选**：不写就用默认值（库在 `data/guixu.db`），设置页保存参数时会自动生成。它只存你改过的东西，默认值只有 `settings_spec` 一个来源。要换库位置才需要手写它：

```yaml
data:
  db_path: data/guixu.db
```

（打包后会指向 `%LOCALAPPDATA%\GuiXu\data\`——安装目录不该塞用户数据。）

模型地址、key、以及 Agent 行为（熔断上限、超时、压缩阈值）都能在 WebUI 的设置页里改，不必回来动配置文件。

### 导入数据

**在界面上传。** 新建的库是空的（0 表 0 字段）——这是正常状态，不是故障。
传一个 Excel，Agent 会先推测它可能是哪张表（或是一张新表）、跟已有的表有没有关联，
推完问你一次，确认后建表灌数据。

### 文档库

左栏「文档库概览」里上传 PDF / Word / txt / md。系统会解析、分块、向量化，
然后在页面上就能直接试一句检索。之后对话里问「制度里怎么写」「手册里有没有提」，
Agent 会自己调 `search_documents`；问表里的数据仍然走 SQL。

扫描件 PDF（没有文字层）会交给当前多模态模型逐页读图，再按文字入库。
模型不支持图片输入时会明确报错，不会假装入库成功。删除的文档进回收站，
保留期内可以恢复；原文预览能看到解析后的全文和每一块切片。

### 启动

```bash
uv run uvicorn api:app --app-dir src
```

打开 http://127.0.0.1:8000

## 技术栈

| 组件 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.12 | Agent 生态成熟 |
| 包管理 | uv | 快、锁文件可靠 |
| 数据库 | SQLite | 单文件、零依赖、备份即复制 |
| 数据访问 | 自建 `storage.py` + `runner.py` | 结构理解与语句执行分开 |
| 接口 | FastAPI + uvicorn | SSE 原生好写，Pydantic 兜住入参 |
| 前端 | Vue 3 + marked（本地引入） | 无构建步骤，改完刷新即可 |
| 模型 | DeepSeek | 性价比高，中文好 |
| 编排 | 手写 Agent Loop | 拒绝 LangChain，掌控每一步 |
| PDF 渲染 | Playwright + Chromium | 浏览器版本锁定，不受系统环境摆布 |
| 图表 | matplotlib | 成熟稳定 |
| embedding | bge-small-zh-v1.5 + ONNX Runtime | 91MB 随包；不引 torch |
| 向量检索 | FAISS | 切片归 SQLite，索引是派生的、可重建 |
| 文档解析 | pypdf / python-docx / PyMuPDF | 纯 Python；PyMuPDF 只负责把扫描页转图片 |
| 文档产出 | python-docx + markdown | 四种格式共用一条渲染链 |

## 设计亮点

### 1. Agent Loop 替代 Workflow

核心循环不到 100 行：模型返回 tool_calls 就执行工具、把结果塞回消息、继续循环；没有就返回最终答案。

### 2. 工具是"交互途径"，不是"限制"

Agent 可以自主组合工具（删除时没找到目标 → 用查询搜索候选 → 问用户确认 → 再删除）。这是合理规划，不是降级。唯一的底线是"不欺骗用户"。

工具之间划了清楚的界：`request_update` 的新值由用户给出，`transform_data` 的新值由规则算出。混在一起会让模型在该问的时候自己算。

### 3. 分层：tools 薄、services 厚

工具只做"菜单 + 传话筒"，所有业务逻辑在 services。加新功能 = 加 service + 在 tools 里注册。

### 4. 数据源：一个文件，两件事分开

SQLite 单文件。备份 = 复制一个文件。**没有要起、要停、要占端口、要设密码的进程。**

这一层分两个模块，按关注点分：`storage.py` 管**库长什么样**（表、软删除隔离、表定义、关系），`runner.py` 管**把语句跑出去**（连接、事务、超时）。混在一起，改一个会碰另一个。

### 5. 数据字典只存"用户可改的"

字段名、类型、必填是数据库的事实，从库里现读；中文含义是你的标注，存在库里的 `_gx_meta` 表。两者分开，数据库加列改类型时字典不会过期。同一个入口还兼作数据库概览页。

### 6. 三层确认机制

- **A1（意图模糊）**：引导澄清
- **A2（方向不唯一）**：≤3 种全展示，>3 种触发澄清
- **B（操作确认）**：增删改执行前二次确认
- **B+（大批量）**：>20 条需输入式确认

原则：宁可多问，不可猜错。

### 7. 报告生成的三层架构

- **统计层**（硬编码）：口径固定，可信
- **编排层**（Agent 决定）：要哪些项、什么时间窗、比不比上一期
- **渲染层**（HTML → PDF）：样式统一，WebUI 直接复用

报告 = 数据（硬编码）+ 概述（LLM 生成）。环比的上期数字同样走硬编码口径，不让模型自己算。

### 8. 参数是配置，不是常量

27 个参数收在 `settings_spec.py` 一处定义，界面、校验、默认值都从它生成；代码里读的是 `setting()`。调一个阈值不需要改代码，也不需要重启。

### 9. 多层防护

| 层 | 机制 |
|---|---|
| 底层 | LLM 重试、SQL 超时、行数上限 |
| 中层 | 思维熔断、异常熔断 |
| 顶层 | Loop 总超时 |

### 10. 可观测作为证据链

- `logs/traces.jsonl`：每次问答的完整链路
- `_gx_audit`（库内表）：所有写操作（增/改/删/导入），和写入同事务

## 项目结构

> 想知道**代码怎么分层**（每层负责什么、文件怎么归位），见 [archive/docs/design.md](archive/docs/design.md)。

```
src/
├── api.py              FastAPI 入口（SSE、设置、字典、文档库、文件）
├── desktop.py          桌面窗口入口
├── agent.py            Agent Loop
├── tools.py            工具定义与分发（20 个）
│
├── storage.py          表 · 软删除隔离 · 表定义 · 关系
├── snapshot.py         快照 · 回滚（破坏性操作前的退路）
├── runner.py           跑 SQL：连接 · 事务 · 超时
├── gate.py             执行前闸门（意图 / 表名 / 系统列）
├── execute.py          执行模型 SQL（含超时和行数上限）
├── nl2sql.py           自然语言 → SQL
├── schema_store.py     数据字典
├── config.py           配置与路径解析
├── config_store.py     模型配置卡片（configs.json + secrets.json）
├── providers.py        供应商预设
├── settings_spec.py    27 个参数的唯一真源
│
├── rag/                文档库子系统
│   ├── parser.py       PDF / Word / txt / md → 纯文本（扫描件转图片给多模态模型）
│   ├── chunker.py      按段落聚合，超长段落按句切
│   ├── embedding.py    bge-small-zh ONNX 推理
│   ├── index.py        FAISS 索引（派生，可重建）
│   ├── rerank.py       精排接口（权重按需下载，没有就原样返回）
│   ├── store.py        _gx_doc / _gx_chunk（唯一真源，软删）
│   └── service.py      入库 · 列表 · 删除/恢复/清理 · 重建 · 检索
│
├── web/static/         前端（无构建）
│   ├── index.html
│   ├── vendor/         vue · marked（本地引入，不走 CDN）
│   ├── audio/          开机动画音效
│   ├── css/            app.css（工作台）· splash.css（开机动画）
│   └── js/
│       ├── components/ ChatView · SchemaView · RecoverView · DocsView
│       │                SettingsView · FilesPanel
│       ├── boot.js · boot.config.js   开机动画 + 首次引导
│       └── main.js · api.js · strings.js · utils.js · mark.js
│
├── services/           业务逻辑
│   ├── __init__.py     共享：异常、上下文、常量
│   ├── query / create / update / delete / restore / pending
│   ├── import / export / transform / structure / recover
│   ├── document_service.py   PDF / Word / md / txt 产物
│   └── report/
│       ├── charts.py      图表生成
│       ├── render.py      HTML → PDF
│       └── templates/report.html
│
├── llm.py              模型调用（含重试）
├── session.py          会话管理与持久化
├── guard.py            安全检查
├── trace.py            可观测
├── audit.py            审计（进库，和写入同事务）
└── cleanup.py          过期数据清理

scripts/fetch_model.py  下载 RAG 权重（不进版本库）
models/                 权重落点（gitignore，打包时随安装包）
eval/                   178 条评测（见 eval/README.md）
```

## 已知限制

- **跨表关联未实现**：多表地基已经铺好（工具按表调用、schema 按表构建），但 JOIN 查询还没有
- **无权限控制**，所有用户看到相同数据
- **扫描件依赖模型视觉能力**：当前模型不支持图片输入时明确报错，需换配置
- **FAISS 索引在内存**：启动或数据变更后重建；它只是派生物，切片原文始终在 SQLite
- **工具返回存的是截断版**（8000 字符），超长结果在历史会话里回看时不全

## Roadmap

- [x] Agent 架构（从 workflow 重构为 tool calling）
- [x] 完整 CRUD（单条 + 批量）
- [x] 多层确认机制（A1/A2/B/B+）
- [x] 软删除 + 恢复 + 审计 + 过期清理
- [x] Excel 导入（差异扫描 + 三阶段确认）
- [x] Excel 导出
- [x] 一致性检查
- [x] 日/周/月报（PDF + 图表 + 环比）
- [x] 规则重塑（transform_data）+ 加列（add_column）
- [x] 多层防护（重试、熔断、超时）
- [x] 上下文压缩 + 对话归档
- [x] 会话持久化
- [x] Web UI（三栏布局 + SSE 流式执行可视化）
- [x] Playwright 替代系统 Edge
- [x] 数据源迁到 PostgreSQL + 统一访问层
- [x] 数据字典 + 数据库概览页
- [x] 参数配置化 + 模型配置卡片
- [x] 多表地基（工具带 table_name、按表构建上下文）
- [x] 数据源迁到 SQLite 单文件（弃 DuckDB 分支与视图约定）
- [x] 结构重组（文件按七层归位）
- [x] 接口按新设计逐层改造（工具返回格式 · 中断统一 · 执行前闸门 · audit 进库）
- [ ] 跨表关联查询
- [x] 评测重写（178 条 · 九维 · 全沙箱）
- [x] RAG（文档检索 + 向量 + FAISS）
- [x] 文档产物（PDF / Word / md / txt）+ 侧栏预览
- [ ] 桌面打包（Inno Setup 安装包）

## 许可证

MIT
