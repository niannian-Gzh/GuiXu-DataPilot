# DataPilot · 数据领航员

用自然语言查询和操作项目数据的 AI Agent。

输入「关梓鹤负责的项目有几个」，它会自己决定调用查询工具、生成 SQL、执行、用自然语言回答你。
输入「删掉家装项目」，它会搜索候选、向你确认、执行软删除，全程记录审计日志。

## 特性

- **Agent 架构**：基于 Tool Calling，模型自主决定调用哪个工具，而非固定流程
- **自然语言转 SQL**：无需懂 SQL，用中文提问即可
- **多轮对话**：支持「那李津伊呢」这类追问，模型自动结合上下文
- **安全删除**：双层确认（意图确认 + 操作确认），大批量需输入验证
- **软删除**：删除的数据 7 天内可恢复，7 天后自动清理
- **完整审计**：所有高危操作记录到 `logs/audit.jsonl`，可完全溯源
- **自我修正**：SQL 执行失败时，带报错信息让模型自动修正
- **完整可观测**：每次问答记录完整生命周期到 trace 日志
- **评测驱动**：内置 Golden Set 和自动跑分脚本

## 评测结果

| 指标 | 结果 |
|---|---|
| 通过率 | **15/15** |
| 一次通过率 | **15/15** |

Golden Set 覆盖布尔筛选、数值筛选、聚合、分组、组合条件、空结果六类问题。

> 注：一次通过率是关键指标。它衡量系统"不依赖自修正就能答对"的稳定性。

## 架构

```
用户输入
   ↓
[入口层] main.py（读输入、处理待确认、调 agent）
   ↓
[Agent 层] agent.py（Agent Loop：模型自主决定调哪个工具）
   ↓
[工具层] tools.py
   ├─ query_database  → 查询
   └─ request_delete  → 请求删除（触发用户确认）
   ↓
[能力层] nl2sql.py / execute.py / summarize.py / delete_op.py
   ↓
[数据层] DuckDB（真实表 projects_all + 过滤视图 projects）
   ↓
[横切] guard.py（安全）· trace.py（可观测）· audit.py（审计）· cleanup.py（清理）
```

**设计原则**：
- Agent 层薄，工具层厚。模型只负责"决策"，工具负责"执行"
- 能力由工具列表决定，没有工具就没有能力
- 确认机制在 Loop 外部处理，因为它是跨轮次状态

## 从 Workflow 到 Agent

项目最初采用 workflow 架构（意图判断 → 改写 → 生成 SQL → 执行），后重构为 Agent。

**暴露的问题**：
1. 改写器会"过度改写"语义完整的问题
2. 意图判断接不住指代（"删了吧"）
3. 上下文被切碎，各模块各自为政
4. 加功能要加模块，越来越繁琐

**重构结果**：
- 代码量减少（删除 intent.py + rewrite.py 共约 200 行）
- "那李津伊呢"不再需要改写器，模型直接结合上下文
- 加功能 = 加工具，不再加模块

## 快速开始

### 环境要求

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

### 安装

```bash
git clone https://github.com/niannian-Gzh/datapilot.git
cd datapilot
uv sync
```

### 配置

在项目根目录创建 `.env`：

```
DEEPSEEK_API_KEY=你的key
```

编辑 `config.yaml`，确认模型和数据路径：

```yaml
llm:
  provider: "deepseek"
  model: "deepseek-v4-flash"
  base_url: "https://api.deepseek.com"
  max_tokens: 4096
  temperature: 0

data:
  excel_path: "data/projects_sample.xlsx"
  db_path: "data/projects.duckdb"
  table_name: "projects"
```

### 准备数据

`data/projects_sample.xlsx` 是示例数据（8 行），已包含在仓库中。

### 导入数据

```bash
uv run src/ingest.py
```

### 开始使用

```bash
uv run src/main.py
```

```
DataPilot · 数据领航员（Agent 版）
输入问题，exit 退出

你问：已下证的项目有几个
  [工具] query_database({"question": "已下证的项目有几个"})
[回答] 已下证的项目共有 10 个。

你问：删掉家装项目
  [工具] request_delete({"keyword": "家装"})
[回答] 找到 1 条匹配：
  1. 家装方案设计与客户运营综合平台（李沂松，已结算已下证）
确认删除这 1 条吗？删除后 7 天内可恢复。
回复「确认」执行删除，或回复「取消」放弃。

你问：确认
[回答] 已删除 1 条记录。7 天内可恢复。
```

### 跑评测

```bash
uv run python eval/run_eval.py
```

## 技术栈

| 组件 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.12 | Agent 生态最成熟 |
| 包管理 | uv | 快、现代、锁文件可靠 |
| 数据库 | DuckDB | 本地单文件，零运维，未来可换 Postgres |
| 模型 | DeepSeek | 性价比高，中文好，兼容 OpenAI 接口 |
| 编排 | 手写 Agent Loop | 拒绝 LangChain，保持对每一步的完全掌控 |

## 设计亮点

### 1. Agent Loop 替代 Workflow

核心循环不到 60 行：模型返回 tool_calls 就执行工具、把结果塞回消息、继续循环；没有 tool_calls 就返回最终答案。

### 2. 安全边界：确认机制在 Loop 外部

删除操作需要跨轮次确认（这轮问、下轮答）。Agent Loop 是单轮内循环，做不了跨轮次。所以确认机制在 `main.py` 里用 `pending_action` 处理，而不是做成工具。

### 3. 双层确认机制

- **A 级（意图确认）**：意图模糊时触发，引导用户澄清
- **B 级（操作确认）**：增删改操作执行前触发
- **B+ 级**：>20 条批量删除时，需用户输入"删除 N 条"确认

原则：宁可多问，不可猜错。

### 4. 软删除 + 视图过滤

真实表 `projects_all` 存全部数据；视图 `projects` 自动过滤 `is_deleted = false`。模型和下游代码无感，过滤在数据库层保证。

### 5. 可观测作为证据链

每次问答写 `logs/traces.jsonl`，每次高危操作写 `logs/audit.jsonl`，都只追加不修改。

## 项目结构

```
src/
├── main.py          入口层
├── agent.py         Agent Loop
├── tools.py         工具定义与分发
├── nl2sql.py        自然语言 → SQL
├── execute.py       执行 SQL
├── summarize.py     结果转自然语言
├── delete_op.py     删除操作
├── llm.py           模型调用封装
├── session.py       会话管理
├── guard.py         安全检查
├── trace.py         可观测
├── audit.py         审计日志
├── cleanup.py       过期数据清理
├── config.py        配置与路径解析
└── ingest.py        Excel → DuckDB

tests/              测试脚本
eval/               评测
docs/               设计文档
```

## 已知限制

- **仅支持单表查询**，多表关联未实现
- **仅支持查询和删除**，修改/新增未实现
- **无权限控制**，所有用户看到相同数据
- **无 RAG 能力**，仅支持结构化数据查询
- **评测未覆盖 Agent 层**，当前评测直接调能力层

## Roadmap

- [x] MVP：NL2SQL + 多轮对话
- [x] 评测体系：Golden Set + 自动跑分
- [x] Agent 架构：从 workflow 重构为 tool calling
- [x] 删除功能：软删除 + 双层确认 + 审计
- [ ] Agent 层评测
- [ ] 修改/新增功能
- [ ] RAG 能力（文档检索）
- [ ] 多表支持
- [ ] 可观测升级（接入 Langfuse）
- [ ] 权限、成本、限流

## 项目文档

- [设计决策记录](docs/decisions.md)

## 许可证

MIT