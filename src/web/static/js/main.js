import {
  SQL_WORDS,
  escapeHtml, strongify, md, safeParse, prettyJson, highlightSql,
  fmtVal, shortTime, stamp, clockTime, toolGist, makeThinkNode, thinkGist,
  confirmColumns, confirmTitle, buildConfirm,
} from './utils.js';
import * as api from './api.js';
import { dict, fmt } from './i18n.js';
import { guixuMark } from './mark.js';
import ChatView from './components/ChatView.js';
import FilesPanel from './components/FilesPanel.js';
import SettingsView from './components/SettingsView.js';
import SchemaView from './components/SchemaView.js';

/* 应用入口。

   状态不再散在 setup 的返回值里，而是集中成一个 store 通过 provide 下发，
   各组件 inject 后展开——展开的是 ref 对象本身，响应性不丢。

   这样拆，是因为原来的 22 个 ref 横跨左中右三栏，按 props/emit 逐级传
   要重新分配归属、逐层转发，改动面大且没有任何功能收益。 */

const { createApp, ref, computed, watch, onMounted, nextTick, provide } = Vue;

createApp({
  components: { ChatView, FilesPanel, SettingsView, SchemaView },
  setup() {
    /* ---------------- 状态 ---------------- */
    const turns = ref([]);
    const input = ref('');
    const busy = ref(false);
    const sessionId = ref(localStorage.getItem('gx_session') || '');
    const sessions = ref([]);
    const rail = ref('artifacts');
    // 默认展开，三栏结构一眼可见；用户收起过才记住收起
    const railOpen = ref(localStorage.getItem('gx_rail') !== '0');
    const leftShut = ref(false);
    const viewer = ref(null);
    const overview = ref(null);            // 欢迎页读数：数据源 / 规模 / 模型

    /* ---------------- 设置 ---------------- */
    const view = ref('chat');              // 'chat' | 'settings' | 'schema'
    const settings = ref({ groups: [], params: [], info: {} });
    const activeGroup = ref('model');
    const leftTab = ref('sessions');        // 'sessions' | 'trace'
    const draft = ref({});                 // 只存改过的项：key -> 新值
    const advanced = ref(localStorage.getItem('gx_advanced') === '1');
    const saving = ref(false);
    const saveMsg = ref(null);

    /* 设置页的导航。settings_spec 里那 4 组是按「后端模块」分的，
       这里是按「用户想改什么」分的——两套划分本来就不是一回事，
       硬凑成一套只会让某一方别扭，所以在前端做一次映射 */
    const NAV_GROUPS = [
      { id: 'model',      name: '模型' },
      { id: 'layout',     name: '布局' },
      { id: 'prefs',      name: '交互偏好' },
      { id: 'advanced',   name: '高级' },
      { id: 'data',       name: '数据' },
      { id: 'about',      name: '关于' },
    ];

    /* 分组 -> 参数键。外观/布局/数据/关于不走后端参数表，所以不列；
       高级组按 level 现取，不在这儿再抄一遍清单 */
    const GROUP_KEYS = {
      model: ['llm.max_tokens', 'llm.temperature'],
      prefs: [
        'safety.retention_days',
        'display.bulk_threshold',
        'display.max_llm_rows',
        'display.display_all_threshold',
        'display.display_sample_count',
        'display.conflict_sample_count',
        'display.preview_rows',
        'agent.keep_recent_turns',
        'agent.tool_result_limit',
      ],
    };
    const dragging = ref(false);
    const fileInput = ref(null);
    const lastElapsed = ref(null);
    const streamEl = ref(null);

    /* ---------------- 派生 ---------------- */
    const currentTitle = computed(() => turns.value[0]?.question || '新会话');
    const allArtifacts = computed(() => turns.value.flatMap((t) => t.artifacts || []));
    // 轨迹面板统计的是"调了什么工具"，思考节点不算
    const allTools = computed(() =>
      turns.value.flatMap((t) => (t.tools || []).filter((x) => x.kind !== 'think')));

    /* 轨迹按「轮次」分组：光看一串扁平的调用，读不出
       「这一问花了多久、走了几步」，而那才是用户关心的单位 */
    const roundsWithTools = computed(() =>
      turns.value
        .map((t, i) => {
          // 同一数组里混着思考节点，这里只要工具调用
          const tools = (t.tools || []).filter((x) => x.kind !== 'think');
          return {
            roundIndex: i,
            question: t.question,
            tools,
            totalMs: tools.reduce((s, x) => s + (x.ms || 0), 0),
            // 还在跑的那一轮。时间轴上给它实心色块、耗时转强调色
            // （见 css 的 .gantt-row.run / .gantt-track i.run）
            running: tools.some((x) => x.state === 'run'),
          };
        })
        .filter((r) => r.tools.length));

    /* 时间轴的统一比例尺：满宽 = 最慢那一轮的总耗时。
       必须所有轮共用同一个基准 —— 如果按各轮自己的耗时归一化，
       每一轮都会被拉满，轮与轮之间就没法比，那块图也就白画了。 */
    const maxRoundMs = computed(() =>
      Math.max(1, ...roundsWithTools.value.map((r) => r.totalMs)));

    /* 左栏「资产」用的规模读数。取不到就给空对象，
       模板那边用 src.tables != null 判断，不显示假的 0 */
    const src = computed(() => (overview.value && overview.value.source) || {});

    const stateCount = computed(() => {
      const c = { ok: 0, err: 0, warn: 0, wait: 0, cancel: 0, run: 0 };
      allTools.value.forEach((t) => { if (c[t.state] !== undefined) c[t.state]++; });
      return c;
    });

    const STATE_LABELS = {
      ok: '成功', err: '失败', warn: '被拒绝',
      wait: '待确认', cancel: '已取消', run: '执行中',
    };
    const stateLabel = (s) => STATE_LABELS[s] || s;

    // 左栏点轮次，滚到中栏对应位置
    const scrollToRound = (i) => {
      nextTick(() => {
        const el = document.getElementById('round-' + i);
        if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    };

    /* 轨迹要能一眼看出「哪一步拖了后腿」，
       所以每条画一根相对条，基准取全场最慢的那一次调用 */
    const totalToolMs = computed(() =>
      allTools.value.reduce((sum, t) => sum + (t.ms || 0), 0));
    const maxToolMs = computed(() =>
      Math.max(1, ...allTools.value.map((t) => t.ms || 0)));


    /* ---------------- 设置 ---------------- */
    const allGroups = computed(() => NAV_GROUPS);

    // 这几组的内容模板直接写，不来自后端参数表
    const isLocalGroup = computed(() =>
      ['layout', 'data', 'about'].includes(activeGroup.value));

    /** 某个分组该显示哪些参数 */
    const paramsOfGroup = (gid) => {
      const params = settings.value.params || [];
      if (gid === 'advanced') {
        // 高级组就是全部 advanced 参数，按 level 现取——
        // 以后新增一个高级参数，不用回来补清单
        return params.filter((p) => p.level === 'advanced');
      }
      const keys = GROUP_KEYS[gid] || [];
      return params.filter((p) => keys.includes(p.key));
    };

    const activeGroupParams = computed(() => paramsOfGroup(activeGroup.value));

    const activeGroupDesc = computed(() => {
      const g = allGroups.value.find((x) => x.id === activeGroup.value);
      return g ? g.name : '';
    });

    const dirty = (key) => draft.value[key] !== undefined;

    const groupDirty = (gid) =>
      paramsOfGroup(gid).filter((p) => draft.value[p.key] !== undefined).length;

    const dirtyCount = computed(() => Object.keys(draft.value).length);

    // 密码框永不回填：留空 = 不修改，避免把掩码当成真值提交上去
    const editValue = (p) => {
      if (p.type === 'password') return draft.value[p.key] ?? '';
      return draft.value[p.key] ?? p.value;
    };

    const onEdit = (p, v) => {
      if (String(v) === String(p.value)) {
        delete draft.value[p.key];      // 改回原样就当没改过
      } else {
        draft.value[p.key] = v;
      }
    };

    const resetField = (p) => { draft.value[p.key] = p.default; };

    const discardDraft = () => { draft.value = {}; saveMsg.value = null; };

    watch(advanced, (v) => localStorage.setItem('gx_advanced', v ? '1' : '0'));

    const flash = (text, ok = true) => {
      saveMsg.value = { text, ok };
      setTimeout(() => { saveMsg.value = null; }, 3200);
    };

    /* 全局提示条：替代 alert()。原生的会阻断操作、样式脱离界面，
       按钮文案还跟随系统语言 */
    const toast = ref(null);
    let toastTimer = null;

    const notify = (text, ok = true) => {
      toast.value = { text, ok };
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => { toast.value = null; }, ok ? 2600 : 4200);
    };

    const loadSettings = async () => {
      const data = await api.getSettings();
      if (data) settings.value = data;
    };

    /* ── 离开拦截 ──────────────────────────────────────────────
       数据字典页编到一半时切走，那份草稿就没了。可触发离开的入口全在
       左栏（点会话、点新建、点设置、点资产），而左栏属于 shell、不属于
       任何一个视图——所以钩子挂在 store 上，由当前页自己注册：
       它知道有没有未保存的改动，这边只管在离开前问一声 */
    const leaveGuard = ref(null);

    /** 把一个「离开当前页」的动作包一层：有页面注册了拦截就先问它。
        被拦下时不返回 Promise——动作还没发生，等它没有意义；
        用户在弹窗上确认之后，那个闭包才会真正执行。 */
    const guarded = (fn) => (...args) => {
      const g = leaveGuard.value;
      if (g) { g(() => fn(...args)); return; }
      return fn(...args);
    };

    // 内部自己调自己的地方（删除会话后要新建）用 raw，别让拦截绕回来
    const newSessionRaw = () => {
      if (busy.value) return;
      sessionId.value = '';
      localStorage.removeItem('gx_session');
      turns.value = [];
      viewer.value = null;
      // 在设置页或数据字典页点「新建会话」，意图显然是回对话去写点什么
      view.value = 'chat';
    };

    const goSettingsRaw = async () => {
      draft.value = {};
      saveMsg.value = null;
      confirmKind.value = null;
      editor.value = null;          // 每次都从列表页进，别停在上次的编辑页
      view.value = 'settings';
      await Promise.all([loadSettings(), loadCounts(), loadProviders(), loadConfigs()]);
    };

    const goChatRaw = () => {
      draft.value = {};
      view.value = 'chat';
    };

    /* 数据字典页。加载由 SchemaView 自己 onMounted 做——这里的
       状态（草稿、改动）属于那个页面，离开即销毁，不该挂在 store 上 */
    const goSchemaRaw = () => { view.value = 'schema'; };

    const goSettings = guarded(goSettingsRaw);
    const goChat = guarded(goChatRaw);
    const goSchema = guarded(goSchemaRaw);
    const newSession = guarded(newSessionRaw);

    /* 从设置 / 数据字典退回对话。顶栏那个按钮和左栏点会话都走它
       （前者直接调，后者在 openSession 内部顺手把 view 摆回来） */
    const leaveView = () => { if (view.value !== 'chat') goChat(); };

    const saveSettings = async () => {
      if (!dirtyCount.value || saving.value) return;
      saving.value = true;
      try {
        const values = {};
        for (const [k, v] of Object.entries(draft.value)) {
          const p = (settings.value.params || []).find((x) => x.key === k);
          // 密码框留空 = 不改这一项，别把空串当成新密码写进去
          if (p && p.type === 'password' && String(v).trim() === '') continue;
          values[k] = v;
        }
        if (!Object.keys(values).length) { draft.value = {}; return; }

        const r = await api.saveSettings(values);
        if (!r.ok) { flash(r.message, false); return; }

        draft.value = {};
        await loadSettings();
        notify('已保存并生效');
      } finally {
        saving.value = false;
      }
    };

    /* ---------------- 模型配置 ---------------- */
    // 关于页的常量。前端是纯静态文件，读不到 pyproject.toml，
    // 所以版本号在这儿手写一份——改版本时记得两边一起改
    const APP_VERSION = 'v0.1.0';
    const REPO_URL = 'https://github.com/niannian-Gzh/GuiXu-DataPilot';

    const providers = ref([]);        // 供应商预设，新建配置时的模板
    const configs = ref([]);          // 已保存的配置卡片
    const activeId = ref(null);       // 生效中的那张

    /* 输入框里那个切换器显示什么：模型名。
       不显示配置名——配置名是「这条记录叫什么」，用户在那儿真正要切的
       是模型 */
    const currentModel = computed(() => {
      const c = configs.value.find((x) => x.id === activeId.value);
      return (c && c.model) || '';
    });
    const editor = ref(null);         // null = 停在列表页；否则是编辑中的表单
    const formModels = ref([]);       // 编辑页下拉里的候选模型
    const formState = ref({ fetching: false, fetch: null });
    // 卡片上的连接测试结果：id -> {running, ok, message}
    const testState = ref({});
    // 删除要二次确认。名字带 cfg 前缀，和会话那边的 pendingDelete 区分开
    const pendingCfgDelete = ref(null);

    const loadProviders = async () => {
      providers.value = await api.getProviders();
    };

    const loadConfigs = async () => {
      const data = await api.getConfigs();
      configs.value = data.configs || [];
      activeId.value = data.active_id || null;
    };

    /** 开一张空表单。默认带上第一个预设，省得从零填地址。 */
    const openNewConfig = () => {
      const first = providers.value[0] || {};
      editor.value = {
        id: null,
        name: '',
        provider: first.id || 'custom',
        base_url: first.base_url || '',
        model: (first.models || [])[0] || '',
        note: '',
        key: '',
        has_key: false,
      };
      formModels.value = first.models || [];
      formState.value = { fetching: false, fetch: null };
    };

    const openEditConfig = (c) => {
      const preset = providers.value.find((p) => p.id === c.provider);
      // key 永不回填——留空表示「不动这一项」，真值只在服务端
      editor.value = { ...c, key: '' };
      formModels.value = (preset && preset.models) || [];
      formState.value = { fetching: false, fetch: null };
    };

    const closeEditor = () => { editor.value = null; };

    /** 点预设格子：填地址，并把模型候选换成这家的 */
    const applyPreset = (p) => {
      const e = editor.value;
      if (!e) return;
      e.provider = p.id;
      e.base_url = p.base_url;
      if (!e.model) e.model = (p.models || [])[0] || '';
      formModels.value = p.models || [];
      formState.value.fetch = null;
    };

    /** 拉模型。用表单里的地址和 key——用户可能刚填完还没保存，
     *  这时候从服务端读是读不到的 */
    const fetchFormModels = async () => {
      const e = editor.value;
      if (!e) return;
      formState.value.fetching = true;
      const r = await api.fetchModels({
        provider: e.provider, base_url: e.base_url, key: e.key,
      });
      formState.value.fetching = false;
      if (r.ok) {
        formModels.value = r.models;
        formState.value.fetch = { ok: true, message: r.message };
      } else {
        formState.value.fetch = { ok: false, message: r.message };
      }
    };

    const saveConfig = async () => {
      const e = editor.value;
      if (!e) return;
      if (!e.name.trim()) { notify('请填名称', false); return; }
      if (!e.base_url.trim()) { notify('请填请求地址', false); return; }

      const payload = {
        name: e.name, provider: e.provider, base_url: e.base_url,
        model: e.model, note: e.note,
      };

      if (e.id) {
        const r = await api.updateConfig(e.id, payload);
        if (!r.ok) { notify(r.message, false); return; }
        // key 单独提交，留空表示不动——否则会把已有的 key 清掉
        if (e.key.trim()) {
          const kr = await api.setConfigKey(e.id, e.key.trim());
          if (!kr.ok) { notify(kr.message, false); return; }
        }
      } else {
        const r = await api.createConfig({ ...payload, key: e.key });
        if (!r.ok) { notify(r.message, false); return; }
      }

      await loadConfigs();
      editor.value = null;
      notify('已保存');
    };

    /** 删除要二次点击，和会话删除同一个套路：左栏/列表里塞不下确认条，
     *  浏览器原生 confirm 又跟界面完全脱节 */
    const removeConfig = async (id) => {
      if (pendingCfgDelete.value !== id) {
        pendingCfgDelete.value = id;
        setTimeout(() => {
          if (pendingCfgDelete.value === id) pendingCfgDelete.value = null;
        }, 3000);
        return;
      }
      pendingCfgDelete.value = null;
      const r = await api.deleteConfig(id);
      if (!r.ok) { notify(r.message, false); return; }
      await loadConfigs();
      notify('已删除');
    };

    const activateConfig = async (id) => {
      const r = await api.activateConfig(id);
      if (!r.ok) { notify(r.message, false); return; }
      await loadConfigs();
      notify('已切换生效');
    };

    /* ---------------- 输入框里的模型切换 ----------------
       它是「同一套 key 下换一个模型」，不是「换一条配置」。
       所以清单来自上游（问它到底有哪些模型），写入落在配置的 model 上。

       懒加载：没人展开就不问上游。这个请求每次几百毫秒，
       为了一个可能不点的菜单在启动时挂一次不划算 */
    const modelOptions = ref([]);
    const modelState = ref({ loading: false, message: '' });

    const loadModelOptions = async () => {
      const id = activeId.value;
      if (!id || modelState.value.loading) return;
      modelState.value = { loading: true, message: '' };
      const r = await api.getConfigModels(id);
      modelState.value = {
        loading: false,
        // 不是所有家都实现了 /models，拉不到是正常情况，把原因说出来
        message: r.ok ? '' : (r.message || '拉不到模型列表'),
      };
      if (r.ok) modelOptions.value = r.models;
    };

    /* 换模型 = 改这条配置的 model，不是只对本次会话生效。
       用户换它多半是要一直用下去；每次重启都忘了重选才是坑。
       改完后端会重建 LLM，立即生效 */
    const switchModel = async (name) => {
      if (!name || name === currentModel.value) return;
      const r = await api.updateConfig(activeId.value, { model: name });
      if (!r.ok) { notify(r.message, false); return; }
      await loadConfigs();
      notify('已切换到 ' + name);
    };

    /* 思考强度。它是应用级参数（所有配置共享），所以走 settings 那套，
       不跟着配置走。这里只给一个顺手的入口——完整的说明和风险提示在设置页 */
    const reasoningParam = computed(() =>
      (settings.value.params || []).find((p) => p.key === 'llm.reasoning_effort'));

    const reasoningEffort = computed(() =>
      (reasoningParam.value && reasoningParam.value.value) || '');

    const reasoningOptions = computed(() =>
      (reasoningParam.value && reasoningParam.value.options) || []);

    const setReasoningEffort = async (v) => {
      if (!v || v === reasoningEffort.value) return;
      const r = await api.saveSettings({ 'llm.reasoning_effort': v });
      if (!r.ok) { notify(r.message, false); return; }
      await loadSettings();
      notify('思考强度已调为「' +
        (reasoningOptions.value.find((o) => o.value === v) || {}).label + '」');
    };

    // 消散的两个计时器接力，共用 testTimers[id] 这一个槽：外层到点后把槽
    // 让给内层，于是「重新测试」时只清一次，就能清掉当下还在跑的那一个
    const testTimers = {};
    const fadingIds = ref({});        // 每个配置 id 是否正在消散

    const testConfig = async (id) => {
      // 结果留在卡片上：错误信息往往很长，用户要照着它改地址或换 key。
      // 成功则 4.5 秒后消散，0.55 秒动画结束后再清数据——总约 5 秒
      if (testTimers[id]) { clearTimeout(testTimers[id]); testTimers[id] = null; }
      fadingIds.value[id] = false;
      testState.value[id] = { running: true, ok: null, message: '' };
      const r = await api.testConfig(id);
      testState.value[id] = { running: false, ok: !!r.ok, message: r.message || '' };
      if (r.ok) {
        testTimers[id] = setTimeout(() => {
          testTimers[id] = null;
          fadingIds.value[id] = true;
          testTimers[id] = setTimeout(() => {
            delete testState.value[id];
            delete fadingIds.value[id];
            testTimers[id] = null;
          }, 560);
        }, 4500);
      }
    };


    /* ---------------- 数据加载 ---------------- */
    const loadSessions = async () => {
      sessions.value = await api.getSessions();
    };

    /* 欢迎页那几格读数。取不到就保持 null，那几行直接不渲染——
       它是锦上添花，不该在开屏第一眼给人一个错误提示 */
    const loadOverview = async () => {
      overview.value = await api.getOverview();
    };


    /* ---------------- 滚动 ---------------- */
    const scrollDown = async () => {
      await nextTick();
      const el = streamEl.value;
      if (el) el.scrollTop = el.scrollHeight;
    };

    /* ---------------- 事件处理 ---------------- */
    const collectArtifact = (turn, tool) => {
      const p = tool.parsed;
      if (!p || !p.file_path) return;
      const path = String(p.file_path).replace(/\\/g, '/');
      const name = path.split('/').pop();
      const isPdf = name.toLowerCase().endsWith('.pdf');
      turn.artifacts.push({
        name,
        path: p.file_path,
        kind: isPdf ? 'pdf' : 'xlsx',
        rows: p.row_count != null ? p.row_count : null,
        label: isPdf ? 'PDF 报告' : 'Excel 表格',
      });
    };

    const handleEvent = (ev, turn) => {
      switch (ev.type) {
        case 'start':
          sessionId.value = ev.session_id;
          localStorage.setItem('gx_session', ev.session_id);
          // 时刻以后端记的为准。前端在 send() 里先填了一个（不然后端回话前
          // 那几秒这行是空的），这里用真值覆盖掉，免得刷新后变成另一个数
          if (ev.at) turn.askedAt = ev.at;
          break;

        case 'think':
          turn.stage = ev.round === 1 ? '正在理解你的问题…' : '正在整理结果…';
          break;

        case 'reasoning':
          // 思考节点也进 tools 数组：界面要的是「先想后做」的时间线，
          // 单独存一份再合并，反而要多一层结构和一个排序步骤
          turn.tools.push(makeThinkNode(ev.round, ev.text));
          break;

        case 'compact':
          turn.stage = ev.message;
          break;

        case 'tool_call':
          turn.stage = '';
          turn.tools.push({
            callId: ev.call_id,
            name: ev.name,
            args: ev.args || {},
            state: 'run',
            open: false,
            ms: null,
            raw: '',
            parsed: null,
          });
          break;

        case 'tool_result': {
          const tool = turn.tools.find((t) => t.callId === ev.call_id);
          if (!tool) break;
          tool.ms = ev.elapsed_ms;
          tool.raw = ev.raw || '';
          tool.parsed = safeParse(tool.raw);
          tool.state = ev.security ? 'warn' : (ev.ok ? 'ok' : 'err');
          collectArtifact(turn, tool);
          break;
        }

        case 'pending':
          turn.stage = '';
          // 触发确认的那个工具没返回结果，停在"待确认"而不是一直转
          turn.tools.forEach((t) => { if (t.state === 'run') t.state = 'wait'; });
          turn.confirm = buildConfirm(ev.pending);
          break;

        case 'answer':
          turn.answer = ev.content || '';
          break;

        case 'error':
          turn.answer = '**出错了**\n\n' + ev.message;
          break;

        case 'done':
          lastElapsed.value = ev.elapsed_ms;
          // 这一轮答完的时刻，同样以后端记的为准。
          // 后端没给（理论上不该发生）时退回本地时间，总比空着强
          turn.answeredAt = ev.at || stamp();
          break;
      }
    };

    /* ---------------- 流式请求 ---------------- */
    const runStream = async (question, turn) => {
      busy.value = true;
      turn.stage = '正在处理…';

      try {
        // SSE 的解析细节收在 api.chat 里，这里只管把事件画到界面上
        await api.chat({
          question,
          sessionId: sessionId.value,
          onEvent: async (ev) => {
            handleEvent(ev, turn);
            await scrollDown();
          },
        });
      } catch (e) {
        turn.answer = '**连接中断**：' + e.message;
      } finally {
        turn.stage = '';
        busy.value = false;
        await scrollDown();
        loadSessions();
      }
    };

    /* ---------------- 发送 ---------------- */
    const send = async () => {
      const q = input.value.trim();
      if (!q || busy.value) return;

      turns.value.push({
        question: q, askedAt: stamp(),
        tools: [], artifacts: [], answer: '', stage: '',
      });

      /* 必须从 turns.value 取回代理再往下传。
         Vue 3 的 ref 只在「通过 proxy 访问」时返回响应式代理，
         直接持有并修改原始对象不经过 Proxy 的 set 陷阱——
         事件流里那些 turn.artifacts.push() / turn.answer = 就全都悄悄丢了，
         界面要等下一次无关的响应式变更才碰巧更新，看起来就是「得按 F5」 */
      const turn = turns.value[turns.value.length - 1];

      input.value = '';
      resetInputHeight();
      await scrollDown();

      await runStream(q, turn);
    };

    const ask = (q) => {
      if (busy.value) return;
      input.value = q;
      send();
    };

    const answerConfirm = async (ti, text) => {
      const turn = turns.value[ti];
      if (!turn || !turn.confirm || busy.value) return;

      const cancelled = text === '取消';
      const isAsk = turn.confirm.kind === 'ask';

      turn.confirm.resolved = true;
      turn.confirm.cancelled = cancelled;

      if (isAsk && !cancelled) {
        turn.confirm.answer = text;
        turn.confirm.verdict = `已回答：${text}`;
      } else {
        turn.confirm.verdict = cancelled ? '任务已被终止' : '正在执行…';
      }

      // 挂起的那次调用不会单独发 tool_result——它没有返回，答案就是
      // 用户这句话。续跑开始前先记下它，跑完把状态从「待确认」改成终态，
      // 否则那一行永远停在等待中
      const waiting = turn.tools.filter((t) => t.state === 'wait');

      // 取消掉的那个工具不会再有结果回来，别让它永远停在「待确认」
      if (cancelled) {
        waiting.forEach((t) => { t.state = 'cancel'; });
      }

      await runStream(text, turn);

      // 非取消：续跑成功即视为这次调用完成。续跑里新挂起的工具
      // 不在 waiting 里（它是这一趟新出现的），状态由新事件决定
      if (!cancelled) waiting.forEach((t) => { t.state = 'ok'; });

      // 续跑后模型会给出自己的回答，那是正文（prose），不是卡片的终态。
      // 这里只记一句结果，卡片保持一行——把它塞进 verdict 就糊了
      if (cancelled) {
        turn.confirm.verdict = isAsk ? '已跳过' : '任务已被终止';
      } else if (isAsk) {
        turn.confirm.verdict = `已回答：${turn.confirm.answer}`;
      } else {
        turn.confirm.verdict = '已执行';
      }
    };


    /* ---------------- 输入框 ---------------- */
    const autoGrow = (e) => {
      const el = e.target;
      el.style.height = 'auto';
      el.style.height = Math.min(el.scrollHeight, 168) + 'px';
    };

    const resetInputHeight = () => {
      nextTick(() => {
        const el = document.querySelector('.composer textarea');
        if (el) el.style.height = 'auto';
      });
    };

    const toggleRail = () => {
      railOpen.value = !railOpen.value;
      localStorage.setItem('gx_rail', railOpen.value ? '1' : '0');
    };

    /* ---------------- 会话 ---------------- */
    /* 回看历史会话时，把当时走过的工具一并还原。
       否则「导出了 Excel」这类会话打开后，右栏产物是空的——
       数据一直在 gx_tools 里，只是以前没收 */
    const messagesToTurns = (messages) => {
      const out = [];
      let cur = null;
      for (const m of messages) {
        if (m.role === 'user') {
          cur = {
            question: m.content, askedAt: m.gx_at || '',
            tools: [], artifacts: [], answer: '', stage: '',
          };
          out.push(cur);
        } else if (m.role === 'assistant' && cur) {
          cur.answer = m.content;
          cur.answeredAt = m.gx_at || '';

          // 思考链和工具是两条独立记录，各自带轮次，合起来按轮次排。
          // 直接全堆在前面的话，回放出来的顺序会和实时看到的不一样
          const timeline = [
            ...(m.gx_reasonings || []).map((r) => ({ kind: 'think', round: r.round, src: r })),
            ...(m.gx_tools || []).map((t) => ({ kind: 'tool', round: t.round, src: t })),
          ];
          // sort 在现代 JS 里是稳定的，同轮次内 think 排在 tool 之前
          timeline.sort((a, b) => (a.round ?? 0) - (b.round ?? 0));

          for (const item of timeline) {
            if (item.kind === 'think') {
              cur.tools.push(makeThinkNode(item.round, item.src.text));
              continue;
            }
            const t = item.src;
            // 新会话文件存的是结构化字段（sql / preview / file_path / gist），
            // 不再存整段 raw；旧文件里还有 raw，先按原样解析，保持兼容
            const legacyRaw = t.raw || '';
            // 空字段不放进去：展开时一串 `"file_path": ""` 只是噪音
            const parsed = legacyRaw ? safeParse(legacyRaw) : (
              (t.sql || t.preview || t.file_path || t.gist)
                ? {
                    ...(t.sql ? { sql: t.sql } : {}),
                    ...(t.preview ? { rows: t.preview } : {}),
                    ...(t.file_path ? { file_path: t.file_path } : {}),
                    ...(t.gist ? { gist: t.gist } : {}),
                  }
                : null
            );
            const tool = {
              callId: '',
              name: t.name,
              args: t.args || {},
              state: t.security ? 'warn' : (t.ok ? 'ok' : 'err'),
              open: false,
              ms: t.ms,
              raw: legacyRaw,
              parsed,
            };
            cur.tools.push(tool);
            collectArtifact(cur, tool);
          }
        }
      }
      return out;
    };

    const openSessionRaw = async (id, silent) => {
      if (busy.value) return;
      try {
        const data = await api.loadSession(id);
        if (!data) {
          if (!silent) notify('这个会话已经不在了', false);
          return;
        }
        sessionId.value = id;
        localStorage.setItem('gx_session', id);
        // 左栏是常驻的，所以在数据字典 / 设置页里点会话也得能回到对话。
        // 加载失败时不切——那时留在原地才看得出"这个会话已经没了"
        view.value = 'chat';
        turns.value = messagesToTurns(data.messages || []);

        // 服务端可能还挂着 pending_action，但 messages 里没有它——
        // 不重建的话，用户看不到确认入口，下一条消息会被当成"确认"吞掉
        if (data.pending) {
          const lastTurn = turns.value[turns.value.length - 1];
          if (lastTurn && !lastTurn.confirm) {
            lastTurn.confirm = buildConfirm(data.pending);
          }
        }

        await scrollDown();
      } catch (e) {
        if (!silent) notify('读取会话失败：' + e.message, false);
      }
    };

    const openSession = guarded(openSessionRaw);

    /* 删除单个会话用二次点击，不用浏览器弹窗。
       左栏窄，塞不下内联确认条；而原生弹窗突兀，
       按钮文案还跟随系统语言，跟界面完全脱节 */
    const pendingDelete = ref(null);
    let pendingTimer = null;

    const removeSession = async (id) => {
      if (pendingDelete.value !== id) {
        pendingDelete.value = id;
        clearTimeout(pendingTimer);
        // 3 秒不点就自动收回，避免悬在半空
        pendingTimer = setTimeout(() => { pendingDelete.value = null; }, 3000);
        return;
      }
      clearTimeout(pendingTimer);
      pendingDelete.value = null;
      await api.deleteSession(id);
      // raw：删掉当前会话之后新建一个，不是「用户主动离开」，不该被拦
      if (id === sessionId.value) newSessionRaw();
      loadSessions();
    };

    /* ---------------- 文件 ---------------- */
    // 模板里是 @click="download(...)"，包一层让调用点不用改
    const download = (path, name) => api.download(path, name);

    /* 预览开在对话区里分屏，不再弹浮层。
       浮层会盖住对话——用户在核对表格时往往正需要看旁边的对话 */
    const previewFile = async (f) => {
      try {
        const data = await api.preview(f.path);
        if (!data) { notify('无法预览这个文件', false); return; }

        if (data.type === 'excel') {
          viewer.value = {
            name: f.name, path: f.path, kind: 'xlsx',
            columns: data.columns, rows: data.rows, total: data.total_rows,
          };
        } else if (data.type === 'pdf') {
          viewer.value = { name: f.name, path: f.path, kind: 'pdf', url: data.url };
        } else {
          // 不支持预览的类型不再偷偷下载，明说
          viewer.value = { name: f.name, path: f.path, kind: 'other' };
        }
      } catch (e) {
        notify('预览失败：' + e.message, false);
      }
    };

    const upload = async (file) => {
      if (!file) return;
      try {
        const data = await api.upload(file);

        // 上传是同步完成的，所以两头同一个时刻
        const at = stamp();
        turns.value.push({
          question: '上传文件：' + file.name,
          askedAt: at, answeredAt: at,
          tools: [], artifacts: [], stage: '',
          answer: '已上传到 `' + data.path + '`\n\n现在可以说「从 ' + data.path + ' 导入数据」。',
        });
        await scrollDown();
      } catch (e) {
        notify('上传失败：' + e.message, false);
      }
    };

    const triggerUpload = () => fileInput.value && fileInput.value.click();

    const handleFileSelect = async (e) => {
      const file = e.target.files && e.target.files[0];
      e.target.value = '';            // 同一个文件连选两次也要能触发
      await upload(file);
    };

    const onDrop = async (e) => {
      dragging.value = false;
      const file = e.dataTransfer.files[0];
      await upload(file);
    };

    const dragLeave = (e) => {
      if (!e.currentTarget.contains(e.relatedTarget)) dragging.value = false;
    };

    /* 维护组的危险操作：内联二次确认，不用浏览器原生弹窗 */
    const confirmKind = ref(null);
    const fileCount = ref(null);

    const loadCounts = async () => {
      fileCount.value = (await api.getFiles()).length;
    };

    const doClearFiles = async () => {
      confirmKind.value = null;
      try {
        const deleted = await api.clearFiles();
        notify('已清空 ' + deleted + ' 个文件');
        loadCounts();
      } catch (e) {
        flash('清空失败：' + e.message, false);
      }
    };

    const doClearSessions = async () => {
      confirmKind.value = null;
      for (const s of sessions.value) {
        await api.deleteSession(s.session_id);
      }
      newSession();
      loadSessions();
      notify('已删除全部会话');
    };

    /* ---------------- 挂载 ---------------- */
    /* 开机动画不在这里驱动。它是 js/boot.js 那套独立运行时 ——
       自己建 DOM、自己盖在应用上面演，演完写 sessionStorage 再退场，
       全程不经过 Vue（见 docs/splash.md）。
       所以这里只做真实的启动初始化，【不等动画】：界面在黑幕底下照样
       把会话和读数备好，揭幕那一刻就是可用的，而不是"刚亮起来还要再等"。
       以前那套 sleep(2500) 估时长已经删掉了 —— 用秒表猜动画什么时候演完
       本来就是错的，动画改一次就得跟着改一次。 */
    onMounted(async () => {
      await loadSessions();
      // 不 await：这三样慢一点没关系，别挡着界面出来。
      // 配置列表和参数表在对话页也要用——输入框里那个切换器显示模型名，
      // 下面挂着思考强度，两个都得先备好
      loadOverview();
      loadConfigs();
      loadSettings();
      if (sessionId.value) await openSession(sessionId.value, true);
    });

    /* ---------------- 下发 ---------------- */
    /* store 就是原来 setup 的返回值。组件里 return { ...store }，
       展开的是 ref 对象本身而不是它的值，所以模板里的 {{ turns }}、
       @click="send" 一个字都不用改 */
    // 文案字典。模板里按属性取词：{{ t.newChat }}
    const t = dict();

    const store = {
      turns, input, busy, sessionId, sessions,
      rail, railOpen, leftShut, viewer, dragging, overview,
      view, settings, activeGroup, draft, advanced, saving, saveMsg,
      leaveGuard,
      allGroups, isLocalGroup, activeGroupParams, activeGroupDesc,
      dirty, groupDirty, dirtyCount, editValue, onEdit, resetField,
      discardDraft, loadSettings, goSettings, goChat, goSchema, saveSettings, leaveView,

      // 模型配置
      providers, configs, activeId, currentModel, editor, formModels, formState,
      testState, pendingCfgDelete, fadingIds,
      loadConfigs, openNewConfig, openEditConfig, closeEditor, applyPreset,
      fetchFormModels, saveConfig, removeConfig, activateConfig, testConfig,
      modelOptions, modelState, loadModelOptions, switchModel,
      reasoningEffort, reasoningOptions, setReasoningEffort,

      // 关于
      appVersion: APP_VERSION, REPO_URL,
      lastElapsed, streamEl, currentTitle, allArtifacts, allTools,
      totalToolMs, maxToolMs, maxRoundMs, leftTab, roundsWithTools, stateCount, src,
      stateLabel, scrollToRound,

      send, ask, answerConfirm,
      openSession, newSession, removeSession, pendingDelete,
      download, previewFile, upload, onDrop, dragLeave,
      fileInput, triggerUpload, handleFileSelect,
      confirmKind, fileCount, doClearFiles, doClearSessions,
      toast, notify,
      autoGrow, toggleRail,

      // 从 utils 来，模板直接在用（v-html="md(...)" 等）
      md, escapeHtml, prettyJson, highlightSql, fmtVal, shortTime,
      clockTime, toolGist, thinkGist, confirmColumns, confirmTitle,

      // 文案。t 取词，fmt 填占位符
      t, fmt,
    };
    provide('store', store);
    return store;
  },
  template: `
<div class="app">

  <!-- 顶栏：应用级的那条带子。品牌 + 功能按钮，
       不管你打开哪个会话、切到哪一屏，上面都一样。
       「已就绪」不在这儿——它是「你要不要发这句话」的读数，
       归输入区（见 ChatView 的 .hint） -->
  <header class="rail">
    <div class="mark">${guixuMark()}</div>
    <div class="brand">归墟</div>
    <div class="brand-sub">数据处理 Agent</div>
    <div class="rail-sp"></div>
    <!-- 这个位置常驻，但按当前是哪一屏换身份：
         对话页它是产物栏的开关（产物栏只在对话页存在）；
         设置 / 数据字典页它是退出——那两屏没有产物栏可收，
         在同一个位置留一个按不动的开关，不如换成一扇能走的门 -->
    <button v-if="view === 'chat'" class="rail-icon"
            @click="toggleRail" title="显示或隐藏产物栏">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
        <path d="M9 1.5H4.5A1 1 0 0 0 3.5 2.5v11a1 1 0 0 0 1 1h7a1 1 0 0 0 1-1V5.5L9 1.5Z"/>
        <path d="M8.5 1.5v4h4"/>
      </svg>
    </button>
    <button v-else class="rail-icon" @click="leaveView" title="返回对话">
      <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6">
        <path d="M3.5 3.5l9 9M12.5 3.5l-9 9"/>
      </svg>
    </button>
  </header>

  <!-- 三栏。线在栏上，不在栏之间——所以左栏收起时线也跟着走。
       左栏和顶栏是常驻的：切到设置或数据字典时它们不走，
       因为那两屏是「工作区里换了内容」，不是「退出了工作台」 -->
  <div class="body">

    <aside class="side" :class="{hidden: leftShut}">
      <!-- 品牌搬到顶栏去了。左栏从「动作」开始 ——
           它管的是「有哪些会话」，不该再重复一遍「这是什么应用」 -->
      <div class="side-pad">
        <button class="btn solid" @click="newSession">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M8 3v10M3 8h10"/>
          </svg>
          新建会话
        </button>
      </div>

      <!-- 资产：Agent 能读到的东西。数据源是表，文档库是语料。
           两者同构：图标 + 名字 + 等宽计数，计数是最该被扫到的部分 -->
      <div class="assets">
        <div class="list-label"><span class="t-kicker-zh">资产</span></div>
        <button class="asset" :class="{on: view === 'schema'}" @click="goSchema">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3">
            <ellipse cx="8" cy="4" rx="4.8" ry="1.9"/>
            <path d="M3.2 4v8c0 1.05 2.15 1.9 4.8 1.9s4.8-.85 4.8-1.9V4"/>
            <path d="M3.2 8c0 1.05 2.15 1.9 4.8 1.9s4.8-.85 4.8-1.9"/>
          </svg>
          <span class="asset-n">数据源概览</span>
          <span class="asset-m">
            {{ src.tables != null ? src.tables + ' 表 · ' + (src.rows || 0).toLocaleString() + ' 行' : '—' }}
          </span>
        </button>
        <!-- 文档库还没做（阶段④·RAG）。这里不编一个读数出来——
             一个恒为「—」的计数是装饰，不是信息，而空态本该是待机 -->
        <button class="asset" disabled>
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3">
            <path d="M9 1.5H4.5A1 1 0 0 0 3.5 2.5v11a1 1 0 0 0 1 1h7a1 1 0 0 0 1-1V5.5L9 1.5Z"/>
            <path d="M8.5 1.5v4h4"/>
          </svg>
          <span class="asset-n">文档库概览</span>
          <span class="asset-m">—</span>
        </button>
      </div>

      <div class="list">
        <!-- 左栏永远是会话列表。轨迹不在这儿切 ——
             它属于会话内部，跟「列表里有哪些会话」是两回事。
             注意别用裸 <template> 包一层：Vue 只把【带指令】的 template 当片段，
             没有指令的会当原生元素保留，而原生 template 是 display:none ——
             内容会整块消失，而且不报错 -->
        <div class="list-label">
          <span class="t-kicker-zh">会话</span>
          <span class="t-meta">{{ sessions.length }}</span>
        </div>
        <div v-if="!sessions.length" class="empty-note">还没有历史会话</div>
        <button v-for="s in sessions" :key="s.session_id"
                class="row" :class="{on: s.session_id === sessionId}"
                @click="openSession(s.session_id)">
          <div class="row-t">{{ s.title }}</div>
          <div class="row-m">
            <span>{{ s.message_count }} 条</span>
            <span>{{ shortTime(s.updated_at) }}</span>
          </div>
          <span class="sess-del" :class="{confirming: pendingDelete === s.session_id}"
                @click.stop="removeSession(s.session_id)"
                :title="pendingDelete === s.session_id ? '再点一次即删除' : '删除会话'">
            <template v-if="pendingDelete === s.session_id">确认？</template>
            <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
                 stroke-linecap="round" stroke-linejoin="round">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </span>
        </button>
      </div>

      <div class="side-foot">
        <button class="foot-btn" :class="{on: view === 'settings'}" @click="goSettings">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.3">
            <path d="M8 10.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z"/>
            <path d="M3 6.5V4a1 1 0 0 1 1-1h2.5M13 6.5V4a1 1 0 0 0-1-1h-2.5M3 9.5V12a1 1 0 0 0 1 1h2.5M13 9.5V12a1 1 0 0 1-1 1h-2.5"/>
          </svg>
          数据源与设置
        </button>
      </div>
    </aside>

    <!-- 设置和数据字典【共用这个工作区】——它们换的是中栏，
         顶栏和左栏留在原地。原型的 v6 / v7 就是这么搭的：
         把「看数据字典」做成退出工作台，等于让用户看个表就得先丢开会话 -->
    <chat-view v-if="view === 'chat'"></chat-view>
    <settings-view v-else-if="view === 'settings'"></settings-view>
    <schema-view v-else-if="view === 'schema'"></schema-view>
  </div>
</div>

<div v-if="toast" class="toast" :class="toast.ok ? 'ok' : 'err'">
  <svg v-if="toast.ok" viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">
    <polyline points="20 6 9 17 4 12"></polyline>
  </svg>
  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor"
       stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
    <circle cx="12" cy="12" r="10"></circle>
    <line x1="12" y1="8" x2="12" y2="12"></line>
    <line x1="12" y1="16" x2="12.01" y2="16"></line>
  </svg>
  {{ toast.text }}
</div>
`,
}).mount('#app');
