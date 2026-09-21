"""可配置参数的注册表。

这里是设置页唯一的真相来源：界面按它渲染分组和表单，后端按它校验写入。

每个参数要交代四件事：
  - 它是什么（label / hint）
  - 默认值是多少（default）—— 调坏了得有路可退
  - 谁能改（level）：normal 直接改，advanced 要开高级模式
  - 改坏了会怎样（risk，仅 advanced 需要）

分级依据是「改坏了会怎样」，不是「能不能改」：
  改坏只是体验差异      -> normal
  改坏会让系统变脆/变慢/烧钱 -> advanced，并且必须写明后果
  改坏会让系统崩或数据有损   -> 干脆不暴露（见文件末尾的说明）
"""

GROUPS = [
    {"id": "llm",     "name": "模型接入",   "desc": "连哪个模型、怎么连"},
    {"id": "agent",   "name": "Agent 行为", "desc": "Agent 循环怎么跑、什么时候刹车"},
    {"id": "display", "name": "交互与展示", "desc": "界面上显示多少、确认门槛多高"},
    {"id": "safety",  "name": "数据安全",   "desc": "写入、查询与保留策略"},
]


PARAMS = [
    # ---------------- 模型接入 ----------------
    {
        "key": "llm.base_url",
        "group": "llm",
        "label": "接口地址",
        "type": "text",
        "default": "https://api.deepseek.com",
        "level": "normal",
        "hint": "OpenAI 兼容的接口地址。换成别家服务时改这里",
    },
    {
        "key": "llm.model",
        "group": "llm",
        "label": "模型",
        "type": "text",
        "default": "deepseek-flash",
        "level": "normal",
        "hint": "模型名，需与服务端提供的名称一致",
    },
    {
        "key": "env.DEEPSEEK_API_KEY",
        "group": "llm",
        "label": "API Key",
        "type": "password",
        "source": "env",
        "env_name": "DEEPSEEK_API_KEY",
        "default": "",
        "level": "normal",
        "hint": "存在 .env 文件里，不进 config.yaml——避免误提交到仓库。留空表示不修改",
    },
    {
        "key": "llm.max_tokens",
        "group": "llm",
        "label": "单次输出上限",
        "type": "number",
        # 8192 是 config.yaml 里用了很久的值，迁走 llm 段时把它固化到这里，
        # 免得回落成概念上的 4096，把用户的设置悄悄改掉
        "default": 8192,
        "level": "normal",
        "hint": "模型一次回复的最大 token 数",
    },
    {
        "key": "llm.temperature",
        "group": "llm",
        "label": "生成随机性",
        "type": "number",
        "min": 0,
        "max": 2,
        "step": 0.1,
        "default": 0,
        "level": "normal",
        "hint": "0 最稳定，适合生成 SQL；调高回答更多样，但 SQL 更容易出错",
    },
    {
        "key": "llm.reasoning_effort",
        "group": "llm",
        "label": "思考强度",
        "type": "text",
        "default": "high",
        "level": "advanced",
        "hint": "推理型模型的思考深度，取值如 low / medium / high。"
                "非推理模型会忽略这个字段",
        "risk": "调低：回答更快但复杂任务的推理质量下降；"
                "调高：思考更充分，但更慢、更费 token",
    },

    # ---------------- Agent 行为 ----------------
    {
        "key": "agent.keep_recent_turns",
        "group": "agent",
        "label": "压缩保留轮数",
        "type": "number",
        "default": 6,
        "level": "normal",
        "hint": "上下文压缩时，保留最近几轮原文不摘要",
    },
    {
        "key": "agent.tool_result_limit",
        "group": "agent",
        "label": "工具返回截断",
        "type": "number",
        "default": 8000,
        "level": "normal",
        "hint": "推给界面的工具原始返回，超过这个字符数就截断",
    },
    {
        "key": "agent.loop_timeout",
        "group": "agent",
        "label": "单轮超时（秒）",
        "type": "number",
        "default": 240,
        "level": "advanced",
        "hint": "一次提问从发出到给出答案的总时长上限",
        "risk": "调小：耗时较长的批量操作会被中途掐断；调大：真卡住时你要干等更久",
    },
    {
        "key": "agent.max_retries",
        "group": "agent",
        "label": "LLM 重试次数",
        "type": "number",
        "default": 3,
        "level": "advanced",
        "hint": "调用模型失败（超时、限流、断连）后的重试次数",
        "risk": "调小：网络抖一下整轮对话就失败；调大：出问题时要等更久才报错",
    },
    {
        "key": "agent.read_tool_limit",
        "group": "agent",
        "label": "只读工具熔断上限",
        "type": "number",
        "default": 3,
        "level": "advanced",
        "hint": "同一个只读工具连续成功调用几次后判定为绕圈，强制结束",
        "risk": "调小：需要多步查询的正常任务会被误判成死循环；调大：真绕圈时白烧更多 token",
    },
    {
        "key": "agent.write_tool_limit",
        "group": "agent",
        "label": "写工具熔断上限",
        "type": "number",
        "default": 2,
        "level": "advanced",
        "hint": "同一个写工具连续调用几次后熔断。写操作风险高，默认比只读更严",
        "risk": "调小：批量新增/修改容易被打断；调大：一旦判断失误，误写的代价更大",
    },
    {
        "key": "agent.compact_threshold",
        "group": "agent",
        "label": "上下文压缩阈值",
        "type": "number",
        "default": 500000,
        "level": "advanced",
        "hint": "对话 token 数达到这个值时，把旧消息摘要掉",
        "risk": "调小：频繁压缩，容易丢失前文的关键约束；调大：可能撞上模型的上下文窗口上限",
    },

    # ---------------- 交互与展示 ----------------
    {
        "key": "display.bulk_threshold",
        "group": "display",
        "label": "批量确认阈值",
        "type": "number",
        "default": 20,
        "level": "normal",
        "hint": "影响超过这个条数时，确认方式升级为手打「删除 N 条」，防止手滑",
    },
    {
        "key": "display.display_all_threshold",
        "group": "display",
        "label": "全量展示阈值",
        "type": "number",
        "default": 20,
        "level": "normal",
        "hint": "候选记录不超过这个条数时全部列出，超过则只列样本",
    },
    {
        "key": "display.display_sample_count",
        "group": "display",
        "label": "抽样条数",
        "type": "number",
        "default": 10,
        "level": "normal",
        "hint": "超过全量展示阈值后，列出几条作为样本",
    },
    {
        "key": "display.conflict_sample_count",
        "group": "display",
        "label": "导入冲突抽样",
        "type": "number",
        "default": 20,
        "level": "normal",
        "hint": "Excel 导入时，字段冲突最多展示几条详情的上限",
    },
    {
        "key": "display.preview_rows",
        "group": "display",
        "label": "文件预览行数",
        "type": "number",
        "default": 50,
        "level": "normal",
        "hint": "预览导出的 Excel 时最多读几行。调大有卡顿风险",
    },
    {
        "key": "display.max_llm_rows",
        "group": "display",
        "label": "直读结果行数",
        "type": "number",
        "default": 20,
        "level": "normal",
        "hint": "查询结果不超过这个行数时，原始数据直接交给模型读；超过则先统计再回答",
    },

    # ---------------- 数据安全 ----------------
    {
        "key": "safety.retention_days",
        "group": "safety",
        "label": "软删除保留天数",
        "type": "number",
        "default": 7,
        "level": "normal",
        "hint": "删除的记录保留几天后可恢复，到期由系统物理清理",
    },
    {
        "key": "safety.query_timeout",
        "group": "safety",
        "label": "SQL 超时（秒）",
        "type": "number",
        "default": 30,
        "level": "advanced",
        "hint": "单条 SQL 的执行时间上限，超时即中断",
        "risk": "调小：复杂查询会直接失败；调大：慢查询卡住时更久才释放",
    },
    {
        "key": "safety.max_rows",
        "group": "safety",
        "label": "查询行数上限",
        "type": "number",
        "default": 1000000,
        "level": "advanced",
        "hint": "单次查询最多返回多少行，是内存的兜底护栏",
        "risk": "调大：超大表查询可能吃爆内存导致进程被杀",
    },
    {
        "key": "safety.max_upload_mb",
        "group": "safety",
        "label": "上传大小上限（MB）",
        "type": "number",
        "default": 20,
        "level": "advanced",
        "hint": "上传的 Excel 文件大小上限",
        "risk": "调大：超大文件在解析时会占用大量内存",
    },
]


# 刻意不暴露的参数，以及为什么
NOT_EXPOSED = {
    "data.db_url": "改成不存在的路径时 DuckDB 会静默新建一个空库，看起来像数据全丢了",
    "data.table_name": "改错只是查错表，但会让所有查询失效，属于配置错误而非偏好",
    "data.excel_path": "仅数据初始化时使用，改错只会导入失败",
    "上传/导出/报告目录": "系统级路径，界面按约定读写，不该由用户改",
}


def param_by_key(key: str):
    for p in PARAMS:
        if p["key"] == key:
            return p
    return None


def defaults() -> dict:
    """{key: default}，供后端校验和「恢复默认」使用。"""
    return {p["key"]: p["default"] for p in PARAMS}
