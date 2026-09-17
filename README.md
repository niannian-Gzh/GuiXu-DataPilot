# DataPilot · 数据处理 Agent

用自然语言完成数据的查询、新增、修改、删除、导入、导出、检查和报告生成。

- 输入「张三负责的项目有几个」→ 自动生成 SQL、执行、回答
- 输入「删掉家装项目」→ 搜索候选、确认、软删除
- 输入「从 data/新数据.xlsx 导入」→ 扫描差异、确认、导入
- 输入「给我一份上个月的月报」→ 统计、画图、生成 PDF

## 特性

- **Agent 架构**：基于 Tool Calling，模型自主决定调用哪个工具
- **完整 CRUD**：查询 / 新增 / 修改 / 删除，支持单条和批量
- **Excel 导入**：扫描差异（新记录 / 冲突 / 软删除），三阶段确认，支持追问详情
- **Excel 导出**：中文列名、日期格式化、中文文件名
- **一致性检查**：发现状态字段矛盾、日期顺序异常
- **日/周/月报**：统计 + 图表 + LLM 概述，输出 PDF
- **安全删除**：双层确认 + 软删除（7 天可恢复）
- **状态联动**：修改状态字符串时自动重算五个布尔字段
- **完整审计**：所有写操作记录到 `logs/audit.jsonl`
- **多层防护**：LLM 重试、熔断、行数上限、SQL 超时、Loop 超时
- **评测驱动**：底层评测 + Agent 层评测

## 评测结果

| 评测 | 用例数 | 结果 |
|---|---|---|
| 底层评测 | 34 | **34/34** |
| Agent 层评测 | 15 | **15/15** |

底层评测覆盖布尔筛选、数值筛选、聚合、分组、组合条件、空结果、排序七类问题。

## 架构

```
用户输入
   ↓
[入口层] main.py（读输入、处理待确认、打印输出）
   ↓
[Agent 层] agent.py（Loop：决策 + 熔断 + 超时）
   ↓
[工具层] tools.py（菜单 + 传话筒）
   ├─ query_database       查询
   ├─ request_create       新增（单条）
   ├─ request_batch_create 新增（批量）
   ├─ request_update       修改
   ├─ request_delete       删除
   ├─ request_import       导入
   ├─ export_to_excel      导出
   ├─ check_consistency    一致性检查
   └─ generate_report      报告生成
   ↓
[服务层] services/（业务逻辑）
   ├── query / create / update / delete / pending
   ├── import / consistency / export
   └── report（stats + charts + render + templates）
   ↓
[数据层] DuckDB
   ├─ projects_all（真实表）
   └─ projects（视图，自动过滤软删除）
   ↓
[横切] guard（安全）· trace（可观测）· audit（审计）· cleanup（清理）· display（展示）
```

**设计原则**：
- Agent 层薄、工具层薄、服务层厚
- 工具是 Agent 与世界交互的途径，不是限制
- 确认机制在 Loop 外部处理（跨轮次状态）

## 快速开始

### 环境要求

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

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

在项目根目录创建 `.env`：

```
DEEPSEEK_API_KEY=你的key
```

`config.yaml` 默认指向示例数据，可直接跑。

### 导入数据

```bash
uv run src/ingest.py
```

### 开始使用

```bash
uv run src/main.py
```

```
DataPilot · 数据处理 Agent
输入问题，exit 退出

你问：已下证的项目有几个
  [工具] query_database({"question": "已下证的项目有几个"})
[回答] 已下证的项目共有 2 个。

你问：给我一份本周周报
  [工具] generate_report({"period": "week"})
[回答] 周报已生成：data\reports\2026年9月第3周周报_xxx.pdf
```

### 跑评测

```bash
# 底层评测
uv run python eval/run_eval.py

# Agent 层评测
uv run python eval/run_agent_eval.py
```

## 技术栈

| 组件 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.12 | Agent 生态成熟 |
| 包管理 | uv | 快、锁文件可靠 |
| 数据库 | DuckDB | 本地单文件，零运维 |
| 模型 | DeepSeek | 性价比高，中文好 |
| 编排 | 手写 Agent Loop | 拒绝 LangChain，掌控每一步 |
| PDF 渲染 | Playwright + Chromium | 浏览器版本锁定，不受系统环境摆布 |
| 图表 | matplotlib | 成熟稳定 |

## 设计亮点

### 1. Agent Loop 替代 Workflow

核心循环不到 100 行：模型返回 tool_calls 就执行工具、把结果塞回消息、继续循环；没有就返回最终答案。

### 2. 工具是"交互途径"，不是"限制"

Agent 可以自主组合工具（删除时没找到目标 → 用查询搜索候选 → 问用户确认 → 再删除）。这是合理规划，不是降级。唯一的底线是"不欺骗用户"。

### 3. 分层：tools 薄、services 厚

工具只做"菜单 + 传话筒"，所有业务逻辑在 services。加新功能 = 加 service + 在 tools 里注册。

### 4. 三层确认机制

- **A1（意图模糊）**：引导澄清
- **A2（方向不唯一）**：≤3 种全展示，>3 种触发澄清
- **B（操作确认）**：增删改执行前二次确认
- **B+（大批量）**：>20 条需输入式确认

原则：宁可多问，不可猜错。

### 5. 报告生成的三层架构

- **统计层**（硬编码）：口径固定，可信
- **编排层**（Agent 决定）：要哪些项、什么时间窗
- **渲染层**（HTML → PDF）：样式统一，未来 WebUI 可复用

报告 = 数据（硬编码）+ 概述（LLM 生成）。

### 6. 多层防护

| 层 | 机制 |
|---|---|
| 底层 | LLM 重试、SQL 超时、行数上限 |
| 中层 | 思维熔断、异常熔断 |
| 顶层 | Loop 总超时 |

### 7. 可观测作为证据链

- `logs/traces.jsonl`：每次问答的完整链路
- `logs/audit.jsonl`：所有写操作（增/改/删/导入）

## 项目结构

```
src/
├── main.py             入口层
├── agent.py            Agent Loop
├── tools.py            工具定义与分发
├── display.py          统一 markdown 展示
│
├── services/           业务逻辑
│   ├── __init__.py     共享：异常、上下文、常量
│   ├── query_service.py
│   ├── create_service.py
│   ├── update_service.py
│   ├── delete_service.py
│   ├── pending_service.py
│   ├── import_service.py
│   ├── consistency_service.py
│   ├── export_service.py
│   ├── report_service.py
│   └── report/
│       ├── stats.py       原子统计
│       ├── charts.py      图表生成
│       ├── render.py      HTML → PDF
│       └── templates/
│           └── report.html
│
├── nl2sql.py           自然语言 → SQL
├── execute.py          执行 SQL（含超时和上限）
├── summarize.py        结果 → 自然语言
├── llm.py              模型调用（含重试）
├── session.py          会话管理
├── guard.py            安全检查
├── trace.py            可观测
├── audit.py            审计日志
├── cleanup.py          过期数据清理
├── config.py           配置与路径解析
└── ingest.py           Excel → DuckDB

tests/                  测试脚本
eval/                   评测
docs/                   设计文档
```

## 已知限制

- **仅支持单表操作**，多表关联未实现
- **无权限控制**，所有用户看到相同数据
- **无 RAG 能力**，仅支持结构化数据查询
- **工具返回存的是截断版**（8000 字符），超长结果在历史会话里回看时不全

## Roadmap

- [x] Agent 架构（从 workflow 重构为 tool calling）
- [x] 完整 CRUD（单条 + 批量）
- [x] 多层确认机制（A1/A2/B/B+）
- [x] 软删除 + 审计 + 过期清理
- [x] Excel 导入（差异扫描 + 三阶段确认）
- [x] Excel 导出
- [x] 一致性检查
- [x] 日/周/月报（PDF + 图表）
- [x] 多层防护（重试、熔断、超时）
- [x] 上下文压缩 + 对话归档
- [x] 会话持久化
- [x] Web UI（三栏布局 + SSE 流式执行可视化）
- [x] Playwright 替代系统 Edge
- [ ] 容器化（Dockerfile）
- [ ] RAG（文档检索）
- [ ] 多表支持
- [ ] Web UI
- [ ] 权限、成本、限流


## 许可证

MIT