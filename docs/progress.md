# 进度存档

> 上下文压缩前留的。**设计见 [design.md](design.md)，本文只记"做到哪了"。**
> 最近更新：2026-10-20

## 当前位置

**模型层完成**（能力清单）。下一步是**横切层**。

> 中间插了一轮界面调整（品牌区搬进左栏、工作区上移、产物栏占满），
> 已落地并提交（`e240db6`）。品牌字样式一个字没改，只搬位置。

## 已经完成的

### 数据层（已落地）

| 模块 | 管什么 |
|---|---|
| `src/storage.py` | 表 · 软删除隔离（视图 + 触发器）· 表定义 · 关系 · 唯一约束 · 改列类型 |
| `src/snapshot.py` | 结构 + 数据的快照 · 回滚 · 覆盖导入 · 30 天清理 |
| `src/runner.py` | 跑 SQL：连接 · 事务 · 超时 |

- 数据源已从 PG 换到 **SQLite 单文件**（`data/guixu.db`）
- `db.py`（322 行）、`ingest.py`（364 行）**已删**
- 依赖去掉 duckdb / psycopg / sqlalchemy（63 → 59 个包）
- 启动时 `repair()` 会把绕过系统建的裸表补上保护

### 工具层

| 步骤 | 状态 |
|---|---|
| `query_database` 返回数据（不是成品答案） | ✅ |
| 确认卡片通用化（后端给 columns + records，前端只管画） | ✅ |
| 增删改查 + 导入通用化（只认表定义，不认业务字段） | ✅ |
| 结构类 5 个（建表 / 加列 / 改列 / 删列 / 删表） | ✅ |
| 快照类 + 列出已删（list_snapshots / rollback_version / list_deleted） | ✅ |
| **`ask_user` + 中断统一 + 断点续跑** | ✅ |
| 收尾：删一致性 · 合并新增 · 报告换内核 | ✅ |

**工具 18 个**，和设计对齐。

收尾时换了两个内核：

- **新增**：`create` + `batch_create` 合成一个，**单条也传数组**。一个工具一种参数形状，
  不会让模型猜"这次算单条还是批量"，也不会留下两条会漂移的实现
- **报告**：`report/stats.py` 整个删了（软著日期列/负责人/分类全在里面）。
  现在是**纯排版**——模型先用 `query_database` 算清楚，再把 `sections`
  （文字 / 表格 / 图表数据）交给它渲染成 PDF。工具不再知道任何业务字段

### 中断与续跑（这次落地的）

| 部件 | 做法 |
|---|---|
| 统一模型 | **工具挂起 + 续体**。`ask_user` 的续体 = 答案就是返回值；确认卡片的续体 = 执行结果 |
| 断点存什么 | 这一轮已发生的消息片段（assistant(tool_calls) + 已完成的 tool 结果 + 挂起调用）；system 和历史每次重组 |
| 续跑怎么喂 | 用户回答伪装成那次工具调用的 `tool` 返回，接在断点上继续循环 |
| 落盘 | `session.pending` 进会话文件，重启后仍能接上（已实测） |
| 前端 | 未解决 = 底部弹窗（占 composer 位置）；已解决 = 对话流一行缩略 |

### 记忆层（已落地）

| | 放哪 | 规则 |
|---|---|---|
| **存证** | `session.messages` | 完整，**只增不减**，压缩不碰它 |
| **记忆** | `summary` + `summary_upto` | 摘要覆盖到第几条；`get_history()` 只发指针之后的 |

- `compact()` 从「删消息」改成「推进指针」——旧版压缩会把用户能回看的早期对话一起删掉
- 摘要的输入里带上动作凭据（`[query_database → 成功，3 行]`），否则模型回看会否认做过
- `gx_tools` 不再存 8000 字符的 `raw`，改存结构化字段：
  `gist`（一句结果要点）/ `sql` / `file_path` / `preview`（前 3 行）
- 参数**全给**，不按位置截前 3——那样 `table_name` 会被切掉
- 压缩 prompt 从「写一段摘要」改成「要点列表」——散文的信息不可控

### 编排层（已落地）

design 编排层 §四的五条账：

| 账 | 怎么清的 |
|---|---|
| 熔断按 (工具 + 参数) | 参数改用**规范化 JSON**（`sort_keys`）——以前换个键序就是新 key，绕过熔断 |
| 压缩检查在循环外 | 挪进循环，每轮 LLM 调用前检查；压缩后重建 messages 前缀，断点起点跟着挪 |
| 强制结束不回写历史 | 所有退出路径统一走 `_end()`：先 `add_assistant` 再返回 |
| 两层重试叠影 | **删掉 `nl2sql` 的内层自修正**。SQL 错就如实返回，让模型自己换 |
| `dispatch` 无参数防御 | 多传 / 少传 / 非对象 / 非法 JSON 都返回 `invalid_arguments`，不击穿整轮 |

顺带修了两个判定的根：

- **成败只看 `ok`**（以前靠"有没有 error 键"猜，`not_found` 会被判成功）；所有工具返回统一带 `ok`
- **安全拒绝认 `error_type: "security"`**（以前检查 `is_security`，而工具从来不返回这个字段——安全拒绝一直被当成普通失败，还会计入熔断）
- **`generate_filter_sql` 以前没有安全检查**——导出、删除、恢复、修改的候选筛选全走它

### 模型层（已落地）

**能力清单** `capabilities`：`tool_calling` / `reasoning` / `reasoning_echo` /
`reasoning_effort` / `context_window`。

| 层 | 怎么用 |
|---|---|
| `providers.py` | 预设打底：deepseek / openai / anthropic 写了明确值，其余用保守默认 |
| `config_store.py` | 卡片可覆盖（白名单收键，类型兜底） |
| `llm.py` | `resolve_capabilities()`：预设 → 卡片 → 默认 |
| 编排层 | 回传 reasoning 前问 `reasoning_echo`；压缩阈值 = `context_window × agent.compact_ratio` |

- `reasoning_effort` 从「填了才带」改成「填了**且认**才带」
- 不认工具调用的模型不发 `tools`——至少还能用文字回答
- 压缩阈值从硬编码 `500000` 改成 `128000 × 0.7`（跟随模型窗口）

### 横切层（1/3）

**执行前闸门 ✅** —— 新模块 `src/gate.py`，接在 `runner` 的两个出口：

| 出口 | 默认意图 | 谁走这条路 |
|---|---|---|
| `query_df` | read | 查询、筛选、导出预览、导入比对 |
| `execute` | write | 增删改、恢复、清理 |
| `tx.execute` | 不检查 | 事务内的内部 SQL（DDL 由 structure_service 自校验） |

检查三样：**语句类型对意图 · 表名白名单 · 系统列**。

- **表名白名单**不是为了防写错，是防**绕过视图直接打底表**（`orders_all`）——SQLite 不会替你拦
- **列名不校验**：写错的列名 SQLite 自己会报 `no such column`，模型看得懂；全量校验要处理别名和 JOIN 作用域，收益不抵复杂度
- **解析失败不再一律拒绝**：关键字兜底（开头词 + 禁用词），判据是"这条语句想干什么"，不是"解析器认不认识它"
- **`system=True` 特权旁路**：恢复已删行、清理回收站、导入比对、变换预览——它们本来就要碰底表和 `is_deleted`；旁路只跳过表名和系统列，语句类型照查

**audit 进库 ✅** —— 审计从追加文件改成内部表 `_gx_audit`。

| 动作 | 写法 |
|---|---|
| 增删改 / 恢复 / 变换 / 导入 / 结构变更 | `record(tx, ...)`，**和写入同一个事务** |
| 导出 / 清理（没有事务可依附） | `log(action, detail)`，自己开连接包事务 |

- `ensure_meta` 每次开连接都会建表（幂等），旧库不用迁移
- 事务回滚时审计跟着回滚——实测验证
- `_gx_audit` 不在 `list_tables` 里，模型看不见；要读它得走 `system=True`

## 下一步：横切层（3/3）

**设置页重分类** —— 用户偏好留下、内部参数搬进「开发者模式」；取消 `normal/advanced` 分级，改按用户会怎么找分组。

参数增删改（design 横切层 §三）：

- **删**：`llm.base_url` / `llm.model`（僵尸）、`env.DEEPSEEK_API_KEY`（与配置卡片重复）
- **改名**：`display.max_llm_rows` → 读类返回行数上限；`compact_threshold` 已改成比例
- **重定位**：`agent.tool_result_limit` → 界面展示上限
- **新增**：快照保留期、快照自动清理开关

## 已知缺口（留给后面的层）

- **已解决的确认卡片刷新后消失** —— `confirm` 只在运行时，没进会话文件。设计要的"事后留痕"目前只在当前会话里成立，留到交互层补
- **一次任务分散在多个 trace** —— 续跑是新 HTTP 请求、新 trace，追溯要串起来

## 关键约定（别忘）

- **软著数据只是测试数据**，与产品一点关系都没有。代码里出现 `project_name` / `status_raw` / `owner` 之类的字段就是硬编码
- **软删除隔离**：业务名是视图（`orders`），物理名是底表（`orders_all`）。露给外面的必须是安全的那张
- **表名约定**：`describe` / `uniques_of` 吃**业务名**，`pk_of` 吃**物理名**
- **系统表**：`_gx_` 前缀，不露面（meta / relation / snapshot）
- **工具返回只给模型**，不给用户；用户看到的东西走另一条路（卡片 / 产物）
- **`status: empty` 和 `ok` 分开**——空结果是事实，不是失败

## 实测踩出来的坑（都写进代码注释了）

- 视图的 INSERT 触发器会让**底表的 DEFAULT 失效**（显式列列表传 NULL 下去）→ 生成触发器时用 `COALESCE(NEW.col, 默认值)`
- `CREATE TABLE ... AS SELECT` / 重建表**不带索引**，唯一约束会静默丢 → 快照和 `change_column_type` 都要另存索引
- **游标嵌套**：`for row in con.execute(...)` 里再 `con.execute(...)`，外层会静默中断 → 先 `fetchall()`
- 删列前必须先拆触发器（它会引用该列，SQLite 因此拒绝 ALTER）
- `LIKE` 里的下划线是通配符，匹配文件/表名要用 `GLOB`
- **写操作打视图时 `rowcount` 恒为 0**（真实改动在 INSTEAD OF 触发器里）→ `execute` 用 `total_changes` 差值
- **同一个用户问题以前每轮发两遍**（api `add_user` + run_agent `append`）→ 只在 api 层写一次
- **重构换签名后冷路径不会自己报错**：`describe(table)` 旧调用藏在恢复链路里，一调就炸 → 已改走 `schema_store` + `render_schema`

## 剩下的整条路

1. 横切层（当前）
2. 交互层（确认卡片历史留痕 · 弹窗打磨 · 恢复页 · 数据字典页加关系）
3. **评测重写**（排在 RAG 之前）
4. **RAG**（最后一个环节，结束 = 项目结束）
5. 打包（Inno Setup）

## 仓库

`github.com/niannian-Gzh/GuiXu-DataPilot`（SSH 与 HTTPS 两条道时通时不通，哪条不行换另一条）
