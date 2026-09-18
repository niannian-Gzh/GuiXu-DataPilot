"""模型供应商预设。

集中放这里，是因为「切一个供应商」实际是三件事同时变：base_url、
可选模型列表、key 存在哪。散在前后端各写一份，加一家就要改三处，
迟早对不上。

关于模型名的可靠性——这份清单各条并不等价：

  · deepseek 是 2026-09-18 用真实 key 调 GET /models 实测得到的；
  · 其余各家来自官方 SDK 源码的模型枚举与官方文档，本机没有 key，
    未经实测。

2026 年内各家几乎都发生过旗舰换代（Llama 系列从 Groq 退役、
kimi-k2 下线、混元迁往 TokenHub）。所以预设里的模型名会过期，
这是必然的。note 里标了「未实测」的，首次接入前先点一次连接测试。

base_url 一律是 **OpenAI 兼容端点**，不是各家原生 SDK 的地址——
它会被直接塞进 OpenAI SDK 的 base_url 参数。
"""

PROVIDERS = [
    # ---------------- 国外 ----------------
    {
        "id": "openai",
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "models": ["gpt-6-astra", "gpt-5.6-sol", "gpt-5.6-luna", "gpt-5.4-mini"],
        "env": "OPENAI_API_KEY",
        "note": "原生端点。gpt-6-astra 需要企业工作区在 Trusted Access 里开通，个人层用不了",
    },
    {
        "id": "anthropic",
        "name": "Anthropic Claude",
        "base_url": "https://api.anthropic.com/v1/",
        "models": ["claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5", "claude-fable-5-1"],
        "env": "ANTHROPIC_API_KEY",
        # 这条提示很要紧：兼容层不报错，只是悄悄不生效
        "note": "走 OpenAI 兼容层。官方定位是测试/对比用，不支持 prompt caching "
                "和 response_format——不报错，但也不生效，生产环境建议用原生接口",
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": ["gemini-3.8-flash", "gemini-3.5-flash",
                   "gemini-3.1-pro-preview", "gemini-3.1-flash-lite"],
        "env": "GEMINI_API_KEY",
        "note": "官方文档里兼容层仍标 beta；只有 chat/completions，没有 responses",
    },
    {
        "id": "mistral",
        "name": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "models": ["mistral-large-latest", "mistral-medium-latest", "mistral-small-latest"],
        "env": "MISTRAL_API_KEY",
        "note": "原生兼容，但校验比 OpenAI 严：tool_choice 用 any 不是 required，"
                "多余字段直接 422",
    },
    {
        "id": "groq",
        "name": "Groq",
        "base_url": "https://api.groq.com/openai/v1",
        "models": ["openai/gpt-oss-120b", "openai/gpt-oss-20b",
                   "moonshotai/kimi-k2-instruct-0905", "qwen/qwen3-32b"],
        "env": "GROQ_API_KEY",
        "note": "LPU 推理，主打速度。原 llama 系列已于 2026-08 退役",
    },
    {
        "id": "xai",
        "name": "xAI Grok",
        "base_url": "https://api.x.ai/v1",
        "models": ["grok-4.6", "grok-4.3", "grok-4.20"],
        "env": "XAI_API_KEY",
        "note": "原生兼容。grok-4-1-fast 全系已于 2026-05 退役",
    },

    # ---------------- 国内 ----------------
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        # 2026-09-18 用真实 key 调 GET /models 实测得到，不是抄文档：
        # deepseek-chat / deepseek-reasoner 已下线，现在只有这两支
        "models": ["deepseek-flash", "deepseek-v4-pro"],
        "env": "DEEPSEEK_API_KEY",
        "note": "性价比高，中文好（模型名已实测）",
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ["glm-5.3", "glm-5.3-flash", "glm-5.2"],
        "env": "ZHIPU_API_KEY",
        "note": "未实测。注意 bigmodel 与 z.ai 两站 key 不互通，用错报 401",
    },
    {
        "id": "qwen",
        "name": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ["qwen3.8-max", "qwen3.7-plus", "qwen3.8-flash"],
        "env": "DASHSCOPE_API_KEY",
        "note": "未实测。国际站是 dashscope-intl，key 不互通",
    },
    {
        "id": "moonshot",
        "name": "月之暗面 Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "models": ["kimi-k3", "kimi-k2.7-code", "kimi-k2.6"],
        "env": "MOONSHOT_API_KEY",
        "note": "未实测。kimi-k2 / k2.5 / moonshot-v1 系列均已下线",
    },
    {
        "id": "stepfun",
        "name": "阶跃星辰 StepFun",
        "base_url": "https://api.stepfun.com/v1",
        "models": ["step-3.7-flash", "step-3.5-flash", "step-router-v1"],
        "env": "STEPFUN_API_KEY",
        "note": "未实测。国际区是 api.stepfun.ai，key 与区域必须匹配",
    },
    {
        "id": "minimax",
        "name": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "models": ["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"],
        "env": "MINIMAX_API_KEY",
        # 三个域名并存且 key 按 host 隔离，值得单独提醒
        "note": "未实测，且域名写法存疑：minimaxi.com / minimax.cn / minimax.io "
                "三种并存、key 按域名隔离。接入前务必先测",
    },
    {
        "id": "hunyuan",
        "name": "腾讯混元",
        "base_url": "https://api.hunyuan.cloud.tencent.com/v1",
        "models": ["hy3", "hunyuan-turbos-latest", "hunyuan-role-latest"],
        "env": "HUNYUAN_API_KEY",
        "note": "未实测，且平台正在迁移：混元能力逐步转向 TokenHub，"
                "老平台已停止新购",
    },
    {
        "id": "qianfan",
        "name": "百度文心",
        "base_url": "https://qianfan.baidubce.com/v2",
        "models": ["ernie-5.1", "ernie-5.0", "ernie-5.0-thinking-latest"],
        "env": "QIANFAN_API_KEY",
        "note": "未实测。v2 用 IAM Bearer，key 形如 bce-v3/ALTAK-...",
    },
    {
        "id": "spark",
        "name": "讯飞星火",
        "base_url": "https://spark-api-open.xf-yun.com/v1",
        "models": ["4.0Ultra", "generalv3.5", "lite"],
        "env": "SPARK_API_KEY",
        # 这条最容易踩：两个域名长得像，但一个是 WebSocket 一个是 HTTP
        "note": "未实测。务必用 spark-api-open 这个域名——"
                "spark-api.xf-yun.com 是 WebSocket 主机，不能当 OpenAI 端点",
    },
    {
        "id": "baichuan",
        "name": "百川智能",
        "base_url": "https://api.baichuan-ai.com/v1",
        "models": ["Baichuan-M3", "Baichuan-M3-Plus", "Baichuan4-Turbo"],
        "env": "BAICHUAN_API_KEY",
        "note": "未实测。该厂已转向医疗垂域，M3 系列是医疗增强模型，"
                "通用线更新停滞，是否长期可用存疑",
    },

    # ---------------- 本地 ----------------
    {
        "id": "ollama",
        "name": "Ollama（本地）",
        "base_url": "http://localhost:11434/v1",
        # 本地模型名由用户自己拉，给不出预设
        "models": [],
        "env": None,
        "note": "本地运行，不需要 key",
        "free_input": True,
    },
]

_BY_ID = {p["id"]: p for p in PROVIDERS}


def get_provider(provider_id: str):
    """按 id 取预设。找不到返回 None——调用方据此拒绝，别静默兜底。"""
    return _BY_ID.get(provider_id)


def guess_model(provider_id: str) -> str:
    """切换供应商时给的默认模型。"""
    p = get_provider(provider_id)
    if not p:
        return ""
    return p["models"][0] if p["models"] else ""
