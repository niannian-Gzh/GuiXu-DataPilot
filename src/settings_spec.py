"""可配置参数的注册表。

这里是设置页唯一的真相来源：界面按它渲染分组和表单，后端按它校验写入。

## 分组按「用户会怎么找」，不按后端模块

早年的分组是 llm / agent / display / safety——那是代码的目录结构。
用户找"删除的东西留几天"，不会想到去 safety 组；他想到的是"数据保留"。

现在四组给用户看：**模型 · 展示与确认 · 数据保留 · 上传**。
第五组 `developer` 默认不出现，要开「开发者模式」。

## 没有 normal / advanced 分级

以前按「改坏了多严重」分——那是给维护者看的。用户找东西靠的是分类。
`risk` 降级成每个参数的一句说明，不再当开关用。
"""

GROUPS = [
    {"id": "model",     "name": "模型",       "desc": "连哪个模型、怎么生成"},
    {"id": "display",   "name": "展示与确认", "desc": "界面上显示多少、确认门槛多高"},
    {"id": "keep",      "name": "数据保留",   "desc": "删掉的东西留多久"},
    {"id": "upload",    "name": "上传",       "desc": "Excel 导入相关"},
    {"id": "developer", "name": "开发者",     "desc": "内部参数，默认不显示"},
]


PARAMS = [
    # ================= 模型 =================
    {
        "key": "llm.max_tokens",
        "group": "model",
        "label": "单次输出上限",
        "type": "number",
        # 8192 是 config.yaml 里用了很久的值，迁走 llm 段时把它固化到这里，
        # 免得回落成概念上的 4096，把用户的设置悄悄改掉
        "default": 8192,
        "hint": "模型一次回复的最大 token 数",
    },
    {
        "key": "llm.temperature",
        "group": "model",
        "label": "生成随机性",
        "type": "number",
        "min": 0,
        "max": 2,
        "step": 0.1,
        "default": 0,
        "hint": "0 最稳定，适合生成 SQL；调高回答更多样，但 SQL 更容易出错",
    },
    {
        "key": "llm.reasoning_effort",
        "group": "model",
        "label": "思考强度",
        # select 而不是 text：取值本来就是个封闭集合。写成 text 等于把
        # 「拼错一个值」的风险留给用户——拼错了不报错，只是模型静默忽略
        "type": "select",
        "options": [
            {"value": "low",    "label": "低"},
            {"value": "medium", "label": "中"},
            {"value": "high",   "label": "高"},
            {"value": "xhigh",  "label": "极高"},
        ],
        "default": "high",
        "hint": "推理型模型的思考深度。非推理模型会忽略这个字段",
        "risk": "调低：回答更快但复杂任务的推理质量下降；"
                "调高：思考更充分，但更慢、更费 token",
    },

    # ================= 展示与确认 =================
    {
        "key": "display.bulk_threshold",
        "group": "display",
        "label": "批量确认阈值",
        "type": "number",
        "default": 20,
        "min": 1,
        "max": 10000,
        "hint": "影响超过这个条数时，确认方式升级为手打「删除 N 条」，防止手滑",
    },
    {
        "key": "display.display_all_threshold",
        "group": "display",
        "label": "全量展示阈值",
        "type": "number",
        "default": 20,
        "min": 1,
        "max": 1000,
        "hint": "候选记录不超过这个条数时全部列出，超过则只列样本",
    },
    {
        "key": "display.display_sample_count",
        "group": "display",
        "label": "抽样条数",
        "type": "number",
        "default": 10,
        "min": 1,
        "max": 100,
        "hint": "超过全量展示阈值后，列出几条作为样本",
    },
    {
        "key": "display.conflict_sample_count",
        "group": "display",
        "label": "导入冲突抽样",
        "type": "number",
        "default": 20,
        "min": 1,
        "max": 100,
        "hint": "Excel 导入时，字段冲突最多展示几条详情的上限",
    },

    # ================= 数据保留 =================
    {
        "key": "safety.retention_days",
        "group": "keep",
        "label": "软删除保留天数",
        "type": "number",
        "default": 7,
        "min": 1,
        "max": 3650,
        "hint": "删除的记录保留几天后可恢复，到期由系统物理清理",
    },
    {
        "key": "safety.snapshot_retention_days",
        "group": "keep",
        "label": "快照保留天数",
        "type": "number",
        "default": 30,
        "min": 1,
        "max": 3650,
        "hint": "结构快照保留几天。比回收站长——快照更重，能回头的时间也该更长",
    },
    {
        "key": "safety.snapshot_auto_clean",
        "group": "keep",
        "label": "快照自动清理",
        "type": "select",
        "options": [
            {"value": "on",  "label": "按保留期自动清理"},
            {"value": "off", "label": "只增不减，我自己删"},
        ],
        "default": "on",
        "hint": "关掉之后快照不会自动消失，占的空间由你负责",
    },

    # ================= 上传 =================
    {
        "key": "display.preview_rows",
        "group": "upload",
        "label": "文件预览行数",
        "type": "number",
        "default": 50,
        "min": 10,
        "max": 1000,
        "hint": "预览导入的 Excel 时最多读几行。调大有卡顿风险",
    },

    # ================= 文档库 =================
    {
        "key": "rag.chunk_size",
        "group": "developer",
        "label": "分块大小",
        "type": "number",
        "default": 400,
        "min": 100,
        "max": 2000,
        "hint": "每块最多多少字。只影响之后上传的文档，已有切片不会自动重切",
        "risk": "调小：检索更精准，但同一段上下文可能被拆开；"
                "调大：上下文更完整，但无关内容一起进 prompt",
    },
    {
        "key": "rag.chunk_overlap",
        "group": "developer",
        "label": "分块重叠",
        "type": "number",
        "default": 50,
        "min": 0,
        "max": 500,
        "hint": "相邻两块重叠多少字，避免跨块的意思在边界断掉",
    },
    {
        "key": "rag.top_k",
        "group": "developer",
        "label": "检索条数",
        "type": "number",
        "default": 4,
        "min": 1,
        "max": 20,
        "hint": "一次检索返回几个最相关的切片。条数越多，模型看到的上下文越全，也越费 token",
    },
    {
        "key": "rag.min_score",
        "group": "developer",
        "label": "相关度门槛",
        "type": "number",
        "default": 0.35,
        "min": 0,
        "max": 1,
        "step": 0.05,
        "hint": "余弦相似度低于这个值的切片不返回。太低会塞进无关内容，太高可能一条都搜不到",
    },
    {
        "key": "rag.vision_max_pages",
        "group": "developer",
        "label": "扫描件页数上限",
        "type": "number",
        "default": 30,
        "min": 1,
        "max": 200,
        "hint": "扫描件 PDF 交给多模态模型识别时，最多处理多少页。超过要拆分上传",
    },

    # ================= 开发者 =================
    {
        "key": "agent.keep_recent_turns",
        "group": "developer",
        "label": "压缩保留轮数",
        "type": "number",
        "default": 6,
        "min": 1,
        "max": 50,
        "hint": "上下文压缩时，保留最近几轮原文不摘要",
    },
    {
        "key": "agent.compact_ratio",
        "group": "developer",
        "label": "上下文压缩比例",
        "type": "number",
        "default": 0.7,
        "min": 0.3,
        "max": 0.95,
        "hint": "上下文用到模型窗口的这个比例时，把旧消息摘要掉。窗口大小来自模型配置的能力清单",
        "risk": "调小：频繁压缩，容易丢失前文的关键约束；调大：可能撞上模型的上下文窗口上限",
    },
    {
        "key": "agent.loop_timeout",
        "group": "developer",
        "label": "单轮超时（秒）",
        "type": "number",
        "default": 240,
        "min": 30,
        "max": 3600,
        "hint": "一次提问从发出到给出答案的总时长上限",
        "risk": "调小：耗时较长的批量操作会被中途掐断；调大：真卡住时你要干等更久",
    },
    {
        "key": "agent.max_retries",
        "group": "developer",
        "label": "LLM 重试次数",
        "type": "number",
        "default": 3,
        "min": 0,
        "max": 10,
        "hint": "调用模型失败（超时、限流、断连）后的重试次数",
        "risk": "调小：网络抖一下整轮对话就失败；调大：出问题时要等更久才报错",
    },
    {
        "key": "agent.read_tool_limit",
        "group": "developer",
        "label": "只读工具熔断上限",
        "type": "number",
        "default": 6,
        "min": 1,
        "max": 50,
        "hint": "同一个只读工具以相同参数成功调用几次后判定为绕圈，强制结束。"
                "参数不同视为不同操作，不计入",
        "risk": "调小：需要多步查询的正常任务会被误判成死循环；"
                "调大：真绕圈时白烧更多 token",
    },
    {
        "key": "agent.write_tool_limit",
        "group": "developer",
        "label": "写工具熔断上限",
        "type": "number",
        "default": 2,
        "min": 1,
        "max": 20,
        "hint": "同一个写工具以相同参数成功调用几次后熔断。写操作风险高，默认比只读更严",
        "risk": "调小：批量新增/修改容易被打断；调大：一旦判断失误，误写的代价更大",
    },
    {
        "key": "agent.tool_result_limit",
        "group": "developer",
        "label": "工具返回展示上限",
        "type": "number",
        "default": 8000,
        "min": 500,
        "max": 100000,
        "hint": "推给界面的工具原始返回，超过这个字符数就截断。只影响界面上显示多少，不影响模型拿到什么",
    },
    {
        "key": "display.max_llm_rows",
        "group": "developer",
        "label": "读类返回给模型的行数上限",
        "type": "number",
        "default": 20,
        "min": 1,
        "max": 1000,
        "hint": "查询结果超过这个行数时截断后再交给模型，模型可以自己决定要不要继续取",
    },
    {
        "key": "safety.query_timeout",
        "group": "developer",
        "label": "SQL 超时（秒）",
        "type": "number",
        "default": 30,
        "hint": "单条 SQL 的执行时间上限，超时即中断",
        "risk": "调小：复杂查询会直接失败；调大：慢查询卡住时更久才释放",
    },
    {
        "key": "safety.max_rows",
        "group": "developer",
        "label": "查询行数上限",
        "type": "number",
        "default": 1000000,
        "hint": "单次查询最多返回多少行，是内存的兜底护栏",
        "risk": "调大：超大表查询可能吃爆内存导致进程被杀",
    },
    {
        "key": "safety.max_upload_mb",
        "group": "developer",
        "label": "上传大小上限（MB）",
        "type": "number",
        "default": 20,
        "hint": "上传的 Excel 文件大小上限",
        "risk": "调大：超大文件在解析时会占用大量内存",
    },
]


def param_by_key(key: str):
    for p in PARAMS:
        if p["key"] == key:
            return p
    return None


def defaults() -> dict:
    """{key: default}，供后端校验和「恢复默认」使用。"""
    return {p["key"]: p["default"] for p in PARAMS}
