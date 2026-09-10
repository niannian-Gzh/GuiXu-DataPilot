# DataPilot · 数据领航员

用自然语言查询、分析项目数据的 AI Agent。

输入「张三负责的项目有几个」，它会自动生成 SQL、执行查询、用自然语言回答你。

## 特性

- **自然语言转 SQL**：无需懂 SQL，用中文提问即可
- **多轮对话**：支持「那李四呢」这类追问，自动补全上下文
- **意图判断**：能区分「明确查询」和「模糊输入」，模糊时主动反问而非乱猜
- **安全护栏**：拒绝所有写操作，SQL 层与意图层双重拦截
- **自我修正**：SQL 执行失败时，带报错信息让模型自动修正
- **完整可观测**：每次问答记录完整生命周期到 trace 日志
- **评测驱动**：内置 Golden Set 和自动跑分脚本

## 评测结果

| 指标 | 结果 |
|---|---|
| 通过率 | **15/15** |
| 一次通过率 | **15/15** |

Golden Set 覆盖布尔筛选、数值筛选、聚合、分组、组合条件、空结果六类问题。

> 注：一次通过率是关键指标。它衡量系统"不依赖自修正就能答对"的稳定性，比单纯的通过率更能反映系统的健康度。

## 架构

```
用户问题
   ↓
[接口层] main.py
   ↓
[会话层] session.py ← 对话历史
   ↓
[编排层] rewrite.py（多轮改写）→ intent.py（意图判断）
   ↓
[能力层] nl2sql.py（生成+自修正）→ execute.py（执行）→ summarize.py（总结）
   ↓
[数据层] DuckDB
   ↓
[横切] guard.py（安全）· trace.py（可观测）· eval/（评测）
```

**设计原则**：编排层薄，能力层厚。每个模块单一职责，通过"接缝"隔离变化。

## 快速开始

### 环境要求

- Python 3.11+
- [uv](https://github.com/astral-sh/uv)

### 安装

```bash
git clone https://github.com/你的用户名/datapilot.git
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
  max_tokens: 1024
  temperature: 0

data:
  excel_path: "data/projects_sample.xlsx"
  db_path: "data/projects.duckdb"
  table_name: "projects"
```

### 准备数据

`data/projects_sample.xlsx` 是一个示例表格，包含以下列：

| 项目名称 | 负责人 | 状态 | 项目下发时间 | ... |
|---|---|---|---|---|
| 项目A | 张三 | 已结算 | 2025-01-01 | ... |

### 导入数据

```bash
uv run src/ingest.py
```

### 开始使用

```bash
uv run src/main.py
```

```
DataPilot · 数据领航员
输入问题，exit 退出

你问：已下证的项目有几个？
[SQL] SELECT COUNT(*) FROM projects WHERE is_certified = true
[回答] 已下证的项目有 10 个。

你问：那待提交的呢？
  [改写] 待提交的项目有哪些？
[SQL] SELECT * FROM projects WHERE is_pending = true
[回答] 待提交的项目有 3 个：...
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
| 编排 | 手写 | 拒绝 LangChain，保持对每一步的完全掌控 |

## 设计亮点

### 1. 自修正机制（Reflexion）

SQL 执行失败时，把「原始问题 + 错误 SQL + 数据库报错」发回给模型，让它修正。最多重试 2 次。

### 2. 安全边界：拒绝 ≠ 可修复

自修正机制有一个已知陷阱：它会为了"通过检查"，把用户的非法操作（如 DELETE）"洗白"成合法操作（如 SELECT）。

DataPilot 的解法：**安全拒绝不走自修正**。写操作在进入重试循环前就被 `guard.py` 拦截。

### 3. 表名显式传入

初版 prompt 只给了表结构（列名），没给表名。模型每次都在猜表名，导致 8/15 题需要重试。

显式加入表名后，一次通过率从 **7/15 提升到 15/15**。

### 4. 保守的查询改写

多轮改写最大的风险不是"改得不够"，而是"改得太多"。改写器会把语义完整的问题（如"打回次数最多的项目"）错误地锁进历史上下文（改成"张三的项目中打回最多的"）。

解法：**prompt 里明确"不确定就原样返回"，并加 few-shot 示例。**

### 5. 可观测作为证据链

每次问答写一条 JSON 到 `logs/traces.jsonl`，只追加不修改。记录：

```json
{
  "trace_id": "e8cd8ac4",
  "timestamp": "2026-09-10T15:32:11",
  "question": "那李四呢",
  "standalone": "李四负责的项目有几个？",
  "intent": "QUERY",
  "sql": "SELECT COUNT(*) FROM projects WHERE owner = '李四'",
  "retries": 0,
  "row_count": 1,
  "answer_head": "李四负责的项目有 76 个。",
  "elapsed_ms": 2657,
  "error": null
}
```

## 已知限制

- **仅支持单表查询**，多表关联未实现
- **仅支持读操作**，写操作（增删改）会安全拒绝
- **无权限控制**，所有用户看到相同数据
- **无 RAG 能力**，仅支持结构化数据查询
- **无多租户支持**，为单用户场景设计

## Roadmap

- [x] MVP：NL2SQL + 多轮对话 + 意图判断 + 安全护栏
- [x] 评测体系：Golden Set + 自动跑分
- [ ] 代码规范化与文档完善
- [ ] 写操作确认流程（CRUD）
- [ ] RAG 能力（文档检索 + 向量库）
- [ ] 多表支持（表选择 + 动态 schema）
- [ ] 可观测升级（接入 Langfuse）
- [ ] 权限、成本、限流

## 项目文档

- [设计决策记录](docs/decisions.md)

## 许可证

MIT