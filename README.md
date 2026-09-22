# DataPilot · 数据处理 Agent

用自然语言完成数据的查询、新增、修改、删除、导入、导出、检查和报表生成。

打开浏览器就是一张工作台：左栏会话与轨迹，中栏对话流，右栏产物。工具调用、思考过程、确认卡片都摊在对话里，每一步都看得见。

- 输入「李津伊负责的项目有几个」→ 自动生成 SQL、执行、回答
- 输入「删掉测试项目」→ 搜索候选、确认、软删除（7 天内可恢复）
- 输入「所有打回次数加 1」→ 按规则重塑、展示改前改后、确认执行
- 输入「加一列 priority，表示优先级」→ 改表结构
- 输入「从 data/新数据.xlsx 导入」→ 扫描差异、确认、导入
- 输入「给我一份上周周报，和上上周对比」→ 统计、画图、算环比、生成 PDF

## 特性

**WebUI**
- 三栏布局 + SSE 流式：思考、工具调用、工具返回、回答边跑边出
- 工具调用卡片化：参数、完整返回、耗时、状态
- 产物内嵌对话流：PDF 可预览可下载，Excel 直接取走
- 确认卡片带 diff：候选清单、影响行数、改前改后
- 会话持久化 + 上下文压缩 + 对话归档
- 设置页：四组 23 个参数在线可调，改完即生效

**数据库概览（数据字典）**
- 表结构、字段类型、必填从库里现读；中文含义由你标
- 字典只存"用户可改的那部分"，所以数据库加列改类型它不会过期

**模型接入**
- 多套模型配置存成卡片，随时切换（测试的、生产的、公司的各存一把 key）
- 供应商预设 + 连接测试；配置与 key 分开存，key 不进版本库

**数据处理**
- 完整 CRUD：查询 / 新增 / 修改 / 删除，支持单条和批量
- Excel 导入：扫描差异（新记录 / 冲突 / 软删除），三阶段确认，支持追问详情
- Excel 导出：中文列名、日期格式化、中文文件名
- 规则重塑：按自然语言规则批量改值（"打回次数加 1"、"owner 去掉首尾空格"）
- 加列改结构：加字段并顺手登记它的中文含义
- 一致性检查：发现状态字段矛盾、日期顺序异常
- 日/周/月报：统计 + 图表 + 环比 + LLM 概述，输出 PDF
- 安全删除：双层确认 + 软删除（7 天可恢复）

**工程底座**
- 状态联动：修改状态字符串时自动重算五个布尔字段
- 完整审计：所有写操作记录到 `logs/audit.jsonl`
- 多层防护：LLM 重试、熔断、行数上限、SQL 超时、Loop 超时
- 可观测：每次问答的完整链路写入 `logs/traces.jsonl`
- 评测驱动：底层评测 + Agent 层评测

## 评测结果

| 评测 | 用例数 | 结果 |
|---|---|---|
| 底层评测 | 34 | **34/34** |
| Agent 层评测 | 15 | **15/15** |

底层评测覆盖布尔筛选、数值筛选、聚合、分组、组合条件、空结果、排序七类问题。

## 架构

```
[浏览器] Vue 3 + marked（CDN 引入，无构建步骤）
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
[工具层] tools.py（菜单 + 传话筒，12 个工具）
   ├─ query_database                    查询
   ├─ request_create / batch_create     新增（单条 / 批量）
   ├─ request_update                    修改（新值由用户给出）
   ├─ transform_data                    修改（新值由规则算出）
   ├─ add_column                        加列（改表结构）
   ├─ request_delete / request_restore  软删除 / 恢复
   ├─ request_import / export_to_excel  导入 / 导出
   └─ check_consistency / generate_report   检查 / 报告
   ↓
[服务层] services/（业务逻辑，按表构建上下文）
   ├── query / create / update / delete / restore / pending
   ├── import / consistency / export / transform / add_column
   └── report（stats + charts + render + templates）
   ↓
[数据层] db.py（统一访问层，收敛后端差异）
   ├─ PostgreSQL（默认）
   └─ DuckDB（本地单文件，保留兼容）

[横切] guard（安全）· trace（可观测）· audit（审计）· cleanup（清理）· display（展示）
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
- PostgreSQL（默认后端；也可改用本地的 DuckDB，见配置一节）

报告中转 PDF 用的是 Playwright 自带的 Chromium，不依赖系统浏览器 —— 装过之后到哪都一样。

### 安装

```bash
git clone https://github.com/niannian-Gzh/datapilot.git
cd datapilot
uv sync

# 下载报告 PDF 渲染用的 Chromium（约 115MB，只需一次）
uv run playwright install chromium
```

### 配置

`.env` 里放模型的 key（首次启动会迁移到 `secrets.json`，二者都不进版本库）：

```
DEEPSEEK_API_KEY=你的key
```

`config.yaml` 指定数据源：

```yaml
data:
  excel_path: data/软著项目申报管理系统.xlsx
  db_url: "postgresql://用户:密码@localhost:5432/库名?client_encoding=utf8"
  table_name: projects
```

数据库要换成 DuckDB，把 `db_url` 改成 `duckdb:///data/projects.duckdb` 即可 —— 两者的差异收敛在 `db.py` 一个文件里，其余代码不感知。

模型地址、key、以及 Agent 行为（熔断上限、超时、压缩阈值）都能在 WebUI 的设置页里改，不必回来动配置文件。

### 导入数据

```bash
uv run src/ingest.py
```

Excel 是唯一的数据来源，列名映射、状态拆布尔字段、清洗都在这一个文件里。导入完会自动同步数据字典。

### 启动

```bash
uv run uvicorn api:app --app-dir src
```

打开 http://127.0.0.1:8000

习惯命令行的话，同一套 Agent 也能直接在终端跑：

```bash
uv run src/main.py
```

```
DataPilot · 数据处理 Agent
输入问题，exit 退出

你问：已下证的项目有几个
  [工具] query_database({"question": "已下证的项目有几个"})
[回答] 已下证的项目共有 2 个。
```

### 跑评测

```bash
# 底层评测
uv run python eval/run_eval.py

# Agent 层评测
uv run python eval/run_agent_eval.py
```

Windows 控制台如果不是 UTF-8 代码页，脚本打印对勾时会抛 `UnicodeEncodeError`，前面加上 `PYTHONIOENCODING=utf-8` 即可。

## 技术栈

| 组件 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.12 | Agent 生态成熟 |
| 包管理 | uv | 快、锁文件可靠 |
| 数据库 | PostgreSQL | 生产形态；DuckDB 作为本地后端保留 |
| 数据访问 | 自建 `db.py` | 读路径的后端差异收在这一个文件里 |
| 接口 | FastAPI + uvicorn | SSE 原生好写，Pydantic 兜住入参 |
| 前端 | Vue 3 + marked（CDN） | 无构建步骤，改完刷新即可 |
| 模型 | DeepSeek | 性价比高，中文好 |
| 编排 | 手写 Agent Loop | 拒绝 LangChain，掌控每一步 |
| PDF 渲染 | Playwright + Chromium | 浏览器版本锁定，不受系统环境摆布 |
| 图表 | matplotlib | 成熟稳定 |

## 设计亮点

### 1. Agent Loop 替代 Workflow

核心循环不到 100 行：模型返回 tool_calls 就执行工具、把结果塞回消息、继续循环；没有就返回最终答案。

### 2. 工具是"交互途径"，不是"限制"

Agent 可以自主组合工具（删除时没找到目标 → 用查询搜索候选 → 问用户确认 → 再删除）。这是合理规划，不是降级。唯一的底线是"不欺骗用户"。

工具之间划了清楚的界：`request_update` 的新值由用户给出，`transform_data` 的新值由规则算出。混在一起会让模型在该问的时候自己算。

### 3. 分层：tools 薄、services 厚

工具只做"菜单 + 传话筒"，所有业务逻辑在 services。加新功能 = 加 service + 在 tools 里注册。

### 4. 数据源抽象：读路径的差异只在一个文件

查询、表结构描述、行数统计都走 `db.py`，连 `?` 占位符到 PG 具名参数的改写也收在那里。换数据库是改一个字符串，不是改一轮代码。

写路径是有意留的例外：`ingest.py` 要建表建视图，`api.py` 的 `/db/ping` 要探活，这两处直接拿驱动。

### 5. 数据字典只存"用户可改的"

字段名、类型、必填是数据库的事实，从库里现读；中文含义是你的标注，存在 `schema_meta.json`。两者分开，数据库加列改类型时字典不会过期。同一个入口还兼作数据库概览页。

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

23 个参数收在 `settings_spec.py` 一处定义，界面、校验、默认值都从它生成；代码里读的是 `setting()`。调一个阈值不需要改代码，也不需要重启。

### 9. 多层防护

| 层 | 机制 |
|---|---|
| 底层 | LLM 重试、SQL 超时、行数上限 |
| 中层 | 思维熔断、异常熔断 |
| 顶层 | Loop 总超时 |

### 10. 可观测作为证据链

- `logs/traces.jsonl`：每次问答的完整链路
- `logs/audit.jsonl`：所有写操作（增/改/删/导入）

## 项目结构

```
src/
├── api.py              FastAPI 入口（SSE、设置、字典、会话、文件）
├── main.py             命令行入口
├── agent.py            Agent Loop
├── tools.py            工具定义与分发
├── display.py          统一 markdown 展示
│
├── db.py               数据访问层（PostgreSQL / DuckDB）
├── schema_store.py     数据字典
├── config.py           配置与路径解析
├── config_store.py     模型配置卡片（configs.json + secrets.json）
├── providers.py        供应商预设
├── settings_spec.py    22 个参数的唯一真源
│
├── web/static/         前端（无构建）
│   ├── index.html
│   ├── css/            base / layout / chat / schema / settings / files / splash
│   └── js/
│       ├── components/ ChatView · SchemaView · SettingsView · FilesPanel · Splash
│       └── main.js · api.js · i18n.js · utils.js
│
├── services/           业务逻辑
│   ├── __init__.py     共享：异常、上下文、常量
│   ├── query / create / update / delete / restore / pending
│   ├── import / consistency / export / transform / add_column
│   └── report/
│       ├── stats.py       原子统计
│       ├── charts.py      图表生成
│       ├── render.py      HTML → PDF
│       └── templates/report.html
│
├── nl2sql.py           自然语言 → SQL
├── execute.py          执行 SQL（含超时和上限）
├── summarize.py        结果 → 自然语言
├── llm.py              模型调用（含重试）
├── session.py          会话管理与持久化
├── guard.py            安全检查
├── trace.py            可观测
├── audit.py            审计日志
├── cleanup.py          过期数据清理
└── ingest.py           Excel → 数据库

tests/                  测试脚本
eval/                   评测
```

## 已知限制

- **跨表关联未实现**：多表地基已经铺好（工具按表调用、schema 按表构建），但 JOIN 查询还没有
- **无权限控制**，所有用户看到相同数据
- **无 RAG 能力**，仅支持结构化数据查询
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
- [ ] 跨表关联查询
- [ ] RAG（文档检索）
- [ ] 容器化（Dockerfile）
- [ ] 权限、成本、限流

## 许可证

MIT
