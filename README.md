# DataPilot · 数据领航员

用自然语言查询和操作项目数据的 AI Agent。

输入「关梓鹤负责的项目有几个」，它会自己决定调用查询工具、生成 SQL、执行、用自然语言回答你。
输入「删掉家装项目」，它会搜索候选、向你确认、执行软删除。
输入「新增一个项目，叫智能测试系统，负责人关梓鹤，分类 web」，它会校验字段、确认、写入。
输入「把智能测试系统的负责人改成李四」，它会展示改前改后、确认、更新。

## 特性

- **Agent 架构**：基于 Tool Calling，模型自主决定调用哪个工具，而非固定流程
- **完整 CRUD**：查询 / 新增 / 修改 / 删除，全部通过自然语言完成
- **安全删除**：双层确认（意图确认 + 操作确认），大批量需输入验证
- **软删除**：删除的数据 7 天内可恢复，7 天后自动清理
- **状态联动**：修改状态字符串时，自动重算五个布尔字段
- **完整审计**：所有写操作记录到 `logs/audit.jsonl`，可完全溯源
- **自我修正**：SQL 执行失败时，带报错信息让模型自动修正
- **完整可观测**：每次问答记录完整生命周期到 trace 日志
- **评测驱动**：底层评测 + Agent 层评测，双评测体系

## 评测结果

| 指标 | 结果 |
|---|---|
| 底层评测 | **15/15** |
| Agent 层评测 | **12/12** |

## 架构

```
用户输入
   ↓
[入口层] main.py（读输入、处理待确认、调 agent）
   ↓
[Agent 层] agent.py（Agent Loop：模型自主决定调哪个工具）
   ↓
[工具层] tools.py
   ├─ query_database   → 查询
   ├─ request_create   → 新增（校验 + 查重 + 确认）
   ├─ request_update   → 修改（展示 diff + 确认）
   └─ request_delete   → 删除（展示候选 + 双层确认）
   ↓
[能力层] nl2sql / execute / summarize / create_op / update_op / delete_op
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

编辑 `config.yaml`：

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
[回答] 已下证的项目共有 2 个。

你问：新增一个项目，叫智能测试系统，负责人张三，分类 web
  [工具] request_create({"project_name": "智能测试系统", "owner": "张三", "category": "web"})
[回答] 即将新增以下记录：
  项目名称：智能测试系统
  负责人：张三
  分类：web
  状态：已提交
  下发时间：2026-09-11
确认新增吗？回复「确认」执行，或「取消」放弃。

你问：确认
[回答] 已新增项目「智能测试系统」。

你问：把智能测试系统的负责人改成李四
  [工具] request_update({"keyword": "智能测试系统", "updates": {"owner": "李四"}})
[回答] 即将修改以下记录：
  项目名称：智能测试系统
  修改内容：
    owner: 张三 → 李四
确认修改吗？

你问：确认
[回答] 已修改项目「智能测试系统」。

你问：删掉智能测试系统
  [工具] request_delete({"keyword": "智能测试系统"})
[回答] 找到 1 条匹配：...
确认删除这 1 条吗？删除后 7 天内可恢复。
```

### 跑评测

```bash
# 底层评测（直接测能力层）
uv run python eval/run_eval.py

# Agent 层评测（走完整 Agent 流程）
uv run python eval/run_agent_eval.py
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

写操作需要跨轮次确认。Agent Loop 是单轮内循环，做不了跨轮次。所以确认机制在 `main.py` 里用 `pending_action` 处理。

### 3. 双层确认机制

- **A 级（意图确认）**：意图模糊时触发
- **B 级（操作确认）**：增删改操作执行前触发
- **B+ 级**：>20 条批量删除时，需输入"删除 N 条"确认

原则：宁可多问，不可猜错。

### 4. 状态联动

修改 `status_raw` 时，自动重算 `is_pending / is_submitted / is_rejected / is_settled / is_certified`。避免"状态说已下证，布尔字段说没有"的数据不一致。

### 5. 软删除 + 视图过滤

真实表 `projects_all` 存全部数据；视图 `projects` 自动过滤 `is_deleted = false`。模型和下游代码无感，过滤在数据库层保证。

### 6. 可观测作为证据链

- `logs/traces.jsonl`：每次问答的完整链路
- `logs/audit.jsonl`：所有写操作（增/改/删）

## 项目结构

```
src/
├── main.py          入口层
├── agent.py         Agent Loop
├── tools.py         工具定义与分发
├── nl2sql.py        自然语言 → SQL
├── execute.py       执行 SQL
├── summarize.py     结果转自然语言
├── create_op.py     新增操作
├── update_op.py     修改操作
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

- **仅支持单表操作**，多表关联未实现
- **无权限控制**，所有用户看到相同数据
- **无 RAG 能力**，仅支持结构化数据查询
- **修改仅支持单条**，批量修改未实现
- **无 Web UI**，仅命令行

## Roadmap

- [x] MVP：NL2SQL + 多轮对话
- [x] 评测体系：Golden Set + 自动跑分
- [x] Agent 架构：从 workflow 重构为 tool calling
- [x] 完整 CRUD：查询 / 新增 / 修改 / 删除
- [x] 双层确认 + 软删除 + 审计
- [ ] 批量修改
- [ ] RAG 能力（文档检索）
- [ ] 多表支持
- [ ] 可观测升级（接入 Langfuse）
- [ ] Web UI
- [ ] 权限、成本、限流

## 项目文档

- [设计决策记录](docs/decisions.md)

## 许可证

MIT