import {
  FIELD_LABELS, SQL_WORDS,
  escapeHtml, strongify, md, safeParse, prettyJson, highlightSql,
  fmtVal, shortTime, toolGist, makeThinkNode, thinkGist,
  confirmColumns, confirmTitle, candidateRows, buildConfirm,
} from './utils.js';
import * as api from './api.js';
import { dict, fmt } from './i18n.js';
import BootSplash from './components/Splash.js';
import ChatView from './components/ChatView.js';
import FilesPanel from './components/FilesPanel.js';
import SettingsView from './components/SettingsView.js';

/* 应用入口。

   状态不再散在 setup 的返回值里，而是集中成一个 store 通过 provide 下发，
   各组件 inject 后展开——展开的是 ref 对象本身，响应性不丢。

   这样拆，是因为原来的 22 个 ref 横跨左中右三栏，按 props/emit 逐级传
   要重新分配归属、逐层转发，改动面大且没有任何功能收益。 */

const { createApp, ref, computed, watch, onMounted, nextTick, provide } = Vue;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

createApp({
  components: { BootSplash, ChatView, FilesPanel, SettingsView },
  setup() {
    /* ---------------- 状态 ---------------- */
    const turns = ref([]);
    const input = ref('');
    const busy = ref(false);
    const sessionId = ref(localStorage.getItem('dp_session') || '');
    const sessions = ref([]);
    const rail = ref('artifacts');
    // 默认展开，三栏结构一眼可见；用户收起过才记住收起
    const railOpen = ref(localStorage.getItem('dp_rail') !== '0');
    const leftShut = ref(false);
    const theme = ref(localStorage.getItem('dp_theme') || 'dark');
    const viewer = ref(null);

    /* ---------------- 设置 ---------------- */
    const view = ref('chat');              // 'chat' | 'settings'
    const settings = ref({ groups: [], params: [], info: {} });
    const activeGroup = ref('model');
    const leftTab = ref('sessions');        // 'sessions' | 'trace'
    const draft = ref({});                 // 只存改过的项：key -> 新值
    const advanced = ref(localStorage.getItem('dp_advanced') === '1');
    const saving = ref(false);
    const saveMsg = ref(null);

    /* 设置页的导航。settings_spec 里那 4 组是按「后端模块」分的，
       这里是按「用户想改什么」分的——两套划分本来就不是一回事，
       硬凑成一套只会让某一方别扭，所以在前端做一次映射 */
    const NAV_GROUPS = [
      { id: 'model',      name: '模型' },
      { id: 'appearance', name: '外观' },
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

    // 领域无关的引导语，从查 → 改 → 导出 → 检查 → 报告，由简到繁
    const samples = [
      '这张表里有多少条记录',
      '把某条记录的状态改一下',
      '把所有数据导出成 Excel',
      '看看数据有没有问题',
      '给我一份本周报告',
    ];

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
          };
        })
        .filter((r) => r.tools.length));

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
      ['appearance', 'layout', 'data', 'about'].includes(activeGroup.value));

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

    watch(advanced, (v) => localStorage.setItem('dp_advanced', v ? '1' : '0'));

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

    const goSettings = async () => {
      draft.value = {};
      saveMsg.value = null;
      confirmKind.value = null;
      view.value = 'settings';
      await Promise.all([loadSettings(), loadCounts(), loadProviders()]);
    };

    const goChat = () => {
      draft.value = {};
      view.value = 'chat';
    };

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

    /* ---------------- 供应商 ---------------- */
    // 关于页的常量。前端是纯静态文件，读不到 pyproject.toml，
    // 所以版本号在这儿手写一份——改版本时记得两边一起改
    const APP_VERSION = 'v0.1.0';
    const REPO_URL = 'https://github.com/niannian-Gzh/datapilot';

    const providers = ref([]);
    const currentProvider = ref('');    // config.yaml 里正在用的那家
    const selectedProvider = ref('');   // 设置页里点开的那张卡片
    /* 用户刚输入的 key，只活在内存里：保存成功后立刻清掉，
       不落 localStorage——那是明文，浏览器一堆扩展都读得到 */
    const keyDraft = ref({});
    const testState = ref({});          // id -> {running, ok, message}
    const modelDraft = ref({});         // id -> 用户在模型下拉里选的值
    const modelOptions = ref({});       // id -> 下拉里的候选模型
    const modelState = ref({});         // id -> {loading, message, fetched}

    const loadProviders = async () => {
      const data = await api.getProviders();
      if (!data) return;
      providers.value = data.providers || [];
      currentProvider.value = (data.current || {}).provider || '';
      // 第一次进来时，默认展开正在用的那张卡片
      if (!selectedProvider.value) selectedProvider.value = currentProvider.value;
      // 下拉的初始项用预设，用户点了「获取模型」再换成接口返回的真实列表
      for (const p of providers.value) {
        if (!modelOptions.value[p.id]) modelOptions.value[p.id] = p.models || [];
        // 必须显式给空串：v-model 是 undefined 时 select 找不到匹配的 option，
        // 会显示成空白，看着像「这家没有模型可选」
        if (modelDraft.value[p.id] === undefined) modelDraft.value[p.id] = '';
      }
    };

    /** 拉该供应商真实可用的模型，替换掉预设那份。
     *
     *  预设只是离线兜底：各家换代太频繁，写在代码里的名字迟早过期，
     *  而能连上时接口说的才算数。
     */
    const loadModels = async (id) => {
      modelState.value[id] = { loading: true, message: '', fetched: false };
      const r = await api.fetchModels(id);
      if (r.ok) {
        modelOptions.value[id] = r.models;
        await loadProviders();   // 让下面的下拉立即用上新列表
        modelState.value[id] = { loading: false, message: r.message, fetched: true };
      } else {
        modelState.value[id] = { loading: false, message: r.message, fetched: false };
      }
    };

    const providerName = (id) => {
      const p = providers.value.find((x) => x.id === id);
      return p ? p.name : id;
    };

    const pickProvider = (id) => {
      // 再点一次收起，省一个额外的关闭按钮
      selectedProvider.value = selectedProvider.value === id ? '' : id;
      if (selectedProvider.value === id) modelDraft.value[id] = '';
    };

    const useProvider = async (id) => {
      const model = (modelDraft.value[id] || '').trim();
      const r = await api.selectProvider(id, model || null);
      if (!r.ok) { notify(r.message, false); return; }
      await loadProviders();
      notify('已切换到 ' + providerName(id));
    };

    const saveKey = async (id) => {
      const key = (keyDraft.value[id] || '').trim();
      if (!key) { notify('请先填入 Key', false); return; }
      const r = await api.saveKey(id, key);
      if (!r.ok) { notify(r.message, false); return; }
      keyDraft.value[id] = '';
      await loadProviders();
      notify('Key 已保存');
    };

    const runTest = async (id) => {
      testState.value[id] = { running: true, ok: null, message: '' };
      const r = await api.testProvider(id);
      // 失败原因留在卡片上而不是弹 toast：用户要照着它改地址或换 key，
      // 飘两秒就没了等于没说
      testState.value[id] = { running: false, ok: !!r.ok, message: r.message || '' };
    };


    /* ---------------- 数据加载 ---------------- */
    const loadSessions = async () => {
      sessions.value = await api.getSessions();
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
          localStorage.setItem('dp_session', ev.session_id);
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

      turns.value.push({ question: q, tools: [], artifacts: [], answer: '', stage: '' });

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
      turn.confirm.resolved = true;
      turn.confirm.cancelled = cancelled;
      turn.confirm.verdict = cancelled ? '已取消，未执行任何操作' : '正在执行…';

      // 取消掉的那个工具不会再有结果回来，别让它永远停在「待确认」
      if (cancelled) {
        turn.tools.forEach((t) => { if (t.state === 'wait') t.state = 'cancel'; });
      }

      await runStream(text, turn);

      // 卡片里直接给结论，answer 就不再单独渲染了
      turn.confirm.verdict = turn.answer || (cancelled ? '已取消，未执行任何操作' : '已执行');
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

    const setTheme = (t) => {
      theme.value = t;
      localStorage.setItem('dp_theme', t);
      document.documentElement.setAttribute('data-theme', t);
    };

    const toggleRail = () => {
      railOpen.value = !railOpen.value;
      localStorage.setItem('dp_rail', railOpen.value ? '1' : '0');
    };

    /* ---------------- 会话 ---------------- */
    /* 回看历史会话时，把当时走过的工具一并还原。
       否则「导出了 Excel」这类会话打开后，右栏产物是空的——
       数据一直在 dp_tools 里，只是以前没收 */
    const messagesToTurns = (messages) => {
      const out = [];
      let cur = null;
      for (const m of messages) {
        if (m.role === 'user') {
          cur = { question: m.content, tools: [], artifacts: [], answer: '', stage: '' };
          out.push(cur);
        } else if (m.role === 'assistant' && cur) {
          cur.answer = m.content;

          // 思考链和工具是两条独立记录，各自带轮次，合起来按轮次排。
          // 直接全堆在前面的话，回放出来的顺序会和实时看到的不一样
          const timeline = [
            ...(m.dp_reasonings || []).map((r) => ({ kind: 'think', round: r.round, src: r })),
            ...(m.dp_tools || []).map((t) => ({ kind: 'tool', round: t.round, src: t })),
          ];
          // sort 在现代 JS 里是稳定的，同轮次内 think 排在 tool 之前
          timeline.sort((a, b) => (a.round ?? 0) - (b.round ?? 0));

          for (const item of timeline) {
            if (item.kind === 'think') {
              cur.tools.push(makeThinkNode(item.round, item.src.text));
              continue;
            }
            const t = item.src;
            const tool = {
              callId: '',
              name: t.name,
              args: t.args || {},
              state: t.security ? 'warn' : (t.ok ? 'ok' : 'err'),
              open: false,
              ms: t.ms,
              raw: t.raw || '',
              parsed: safeParse(t.raw),
            };
            cur.tools.push(tool);
            collectArtifact(cur, tool);
          }
        }
      }
      return out;
    };

    const openSession = async (id, silent) => {
      if (busy.value) return;
      try {
        const data = await api.loadSession(id);
        if (!data) {
          if (!silent) notify('这个会话已经不在了', false);
          return;
        }
        sessionId.value = id;
        localStorage.setItem('dp_session', id);
        turns.value = messagesToTurns(data.messages || []);
        await scrollDown();
      } catch (e) {
        if (!silent) notify('读取会话失败：' + e.message, false);
      }
    };

    const newSession = () => {
      if (busy.value) return;
      sessionId.value = '';
      localStorage.removeItem('dp_session');
      turns.value = [];
      viewer.value = null;
    };

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
      if (id === sessionId.value) newSession();
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

        turns.value.push({
          question: '上传文件：' + file.name,
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

    /* ---------------- 开机动画 ---------------- */
    const countUp = (el, target, duration, pad) => {
      const start = performance.now();
      const step = (now) => {
        const p = Math.min((now - start) / duration, 1);
        const eased = 1 - Math.pow(1 - p, 3);
        const v = Math.round(target * eased);
        el.textContent = pad ? String(v).padStart(pad, '0') : String(v);
        if (p < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    };

    /* 开机动画的三格改报日期。
       这不是随手换的填充物：DataPilot 要处理「上周」「本月」这类相对时间，
       agent 的 SYSTEM_PROMPT 里也带着当前日期。开机时把时间基准亮出来，
       是在告诉用户这台机器按哪一天算 */
    const renderBootStats = () => {
      const host = document.getElementById('bootStats');
      if (!host) return;

      const now = new Date();
      const cells = [
        { n: now.getFullYear(), label: '年', pad: 0 },
        { n: now.getMonth() + 1, label: '月', pad: 2 },
        { n: now.getDate(),       label: '日', pad: 2 },
      ];

      /* 三格依次滚入。窗口跟航迹弧旋转、北方亮起严格同起同止：
         900ms 起，最后一格收在 2400ms（900 + 2×280 + 940）。
         改这三个数必须同步改 tip-stay 和 sleep 的下限 */
      const START = 900, STEP = 280, DURATION = 940;

      host.innerHTML = cells.map((c, i) =>
        '<div class="boot-stat" style="animation-delay:' +
        ((START + i * STEP) / 1000) + 's">' +
        '<b>' + (c.pad ? '00' : '0') + '</b><span>' + c.label + '</span></div>'
      ).join('');

      const nums = host.querySelectorAll('.boot-stat b');
      cells.forEach((c, i) => {
        setTimeout(() => countUp(nums[i], c.n, DURATION, c.pad), START + i * STEP);
      });
    };

    const boot = async () => {
      const skip = document.documentElement.getAttribute('data-boot') === 'skip';
      const bar = document.getElementById('bootBar');
      const started = Date.now();

      // 动画期间做真实初始化，不是白等
      if (!skip && bar) bar.style.width = '34%';
      renderBootStats();

      await loadSessions();

      if (!skip && bar) bar.style.width = '100%';

      if (skip) return;

      // 最短展示时长。2.40s 是三方共同收尾的那一刻——
      // 航迹弧转完一圈半停下、日期末格滚完、北方指针亮起。
      // 多留 100ms 让「锁定」这个瞬间被看到，再开始淡出
      await sleep(Math.max(0, 2500 - (Date.now() - started)));

      // 用隐藏而不是 remove()：DOM 留着，调试动画时好复现
      const el = document.getElementById('boot');
      if (el) {
        el.classList.add('done');
        setTimeout(() => { el.style.display = 'none'; }, 820);
      }
      sessionStorage.setItem('dp_booted', '1');
    };

    /* ---------------- 挂载 ---------------- */
    onMounted(async () => {
      await boot();
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
      rail, railOpen, leftShut, theme, viewer, dragging,
      view, settings, activeGroup, draft, advanced, saving, saveMsg,
      allGroups, isLocalGroup, activeGroupParams, activeGroupDesc,
      dirty, groupDirty, dirtyCount, editValue, onEdit, resetField,
      discardDraft, loadSettings, goSettings, goChat, saveSettings,

      // 供应商
      providers, currentProvider, selectedProvider, keyDraft, testState, modelDraft,
      modelOptions, modelState, loadModels,
      providerName, pickProvider, useProvider, saveKey, runTest,

      // 关于
      appVersion: APP_VERSION, REPO_URL,
      lastElapsed, streamEl, samples, currentTitle, allArtifacts, allTools,
      totalToolMs, maxToolMs, leftTab, roundsWithTools, stateCount,
      stateLabel, scrollToRound,

      send, ask, answerConfirm,
      openSession, newSession, removeSession, pendingDelete,
      download, previewFile, upload, onDrop, dragLeave,
      fileInput, triggerUpload, handleFileSelect,
      confirmKind, fileCount, doClearFiles, doClearSessions,
      toast, notify,
      autoGrow, setTheme, toggleRail,

      // 从 utils 来，模板直接在用（v-html="md(...)" 等）
      md, escapeHtml, prettyJson, highlightSql, fmtVal, shortTime,
      toolGist, thinkGist, confirmColumns, confirmTitle,

      // 文案。t 取词，fmt 填占位符
      t, fmt,
    };
    provide('store', store);
    return store;
  },
  template: `
<boot-splash></boot-splash>

<div class="shell" v-if="view === 'chat'"
     :class="{'right-open': railOpen, 'left-shut': leftShut}">

  <aside class="col glass" :class="{hidden: leftShut}">
    <div class="brand">
      <div class="brand-mark">
        <svg viewBox="0 0 48 48" fill="none">
          <circle cx="24" cy="24" r="20.5" stroke="currentColor" stroke-width="2.6"
                  stroke-dasharray="1.6 9.13" opacity=".45" transform="rotate(-90 24 24)"></circle>
          <circle cx="24" cy="24" r="15.5" stroke="currentColor" stroke-width=".8" opacity=".14"></circle>
          <path d="M24 5 28.5 24 24 19.5 19.5 24Z" fill="currentColor"></path>
          <path d="M24 43 28.5 24 24 28.5 19.5 24Z" fill="currentColor" opacity=".28"></path>
          <path d="M5 24 24 19.5 19.5 24 24 28.5Z" fill="currentColor" opacity=".5"></path>
          <path d="M43 24 24 19.5 28.5 24 24 28.5Z" fill="currentColor" opacity=".5"></path>
          <path d="M9.2 32.5A17 17 0 0 1 36.4 10.6" stroke="currentColor" stroke-width="1.7"
                stroke-linecap="round" fill="none" opacity=".6"></path>
          <circle cx="36.6" cy="10.4" r="2.6" fill="currentColor"></circle>
          <circle cx="24" cy="24" r="2.2" fill="currentColor"></circle>
        </svg>
      </div>
      <div style="flex:1;min-width:0">
        <div class="brand-name">DataPilot</div>
        <div class="brand-tag">数据处理 Agent</div>
      </div>
    </div>

    <!-- 主视图切换：会话 / 轨迹 -->
    <div class="side-tabs">
      <button :class="{on: leftTab === 'sessions'}" @click="leftTab = 'sessions'">会话</button>
      <button :class="{on: leftTab === 'trace'}" @click="leftTab = 'trace'">
        轨迹{{ allTools.length ? ' · ' + allTools.length : '' }}
      </button>
    </div>

    <button class="new-chat" @click="newSession">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
           stroke-linecap="round" stroke-linejoin="round">
        <line x1="12" y1="5" x2="12" y2="19"></line>
        <line x1="5" y1="12" x2="19" y2="12"></line>
      </svg>
      新对话
    </button>

    <div class="side-scroll">
      <!-- 轨迹模式：按轮次导航 -->
      <template v-if="leftTab === 'trace'">
        <div class="side-label">
          <span>本会话轮次</span>
          <span style="font-family:var(--mono)">{{ roundsWithTools.length }}</span>
        </div>
        <div v-if="!roundsWithTools.length" class="empty-note">
          还没有工具调用<br>
          <span style="font-size:10.5px">执行过程只属于当前这次对话</span>
        </div>
        <button v-for="(r, i) in roundsWithTools" :key="i" class="round-nav"
                @click="scrollToRound(r.roundIndex)">
          <div class="q">{{ r.question }}</div>
          <div class="m">{{ r.tools.length }} 步 · {{ (r.totalMs / 1000).toFixed(1) }}s</div>
        </button>
      </template>

      <!-- 会话模式：会话列表 -->
      <template v-else>
      <div class="side-label">
        <span>会话</span>
        <span style="font-family:var(--mono)">{{ sessions.length }}</span>
      </div>
      <div v-if="!sessions.length" class="empty-note">还没有历史会话</div>
      <button v-for="s in sessions" :key="s.session_id"
              class="sess" :class="{on: s.session_id === sessionId}"
              @click="openSession(s.session_id)">
        <div class="sess-title">{{ s.title }}</div>
        <div class="sess-meta">
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
      </template>
    </div>

    <div style="padding:9px 12px;border-top:1px solid var(--edge-soft);display:flex;gap:6px">
      <button class="btn ghost" @click="goSettings" style="flex:1;justify-content:center">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round">
          <circle cx="12" cy="12" r="3"></circle>
          <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path>
        </svg>
        设置
      </button>
      <button class="icon-btn" @click="leftShut = true" title="收起侧栏">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
             stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"></polyline>
        </svg>
      </button>
    </div>
  </aside>

  <!-- 中栏：会话头 + 轨迹页 + 对话流 + 输入区 -->
  <chat-view></chat-view>

  <!-- 右栏：本次会话的产物 -->
  <files-panel></files-panel>
</div>

<settings-view v-else></settings-view>

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
