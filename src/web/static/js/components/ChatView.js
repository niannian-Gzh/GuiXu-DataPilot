/* 工作区：会话头、对话流、轨迹页、输入区、产物栏、预览弹窗。
   这是最大的一块，承载工具行、思考链、产物卡、确认卡。

   DOM 结构和类名一律照 docs/proto/workbench.html —— 那边的样式是
   整体搬进 css/app.css 的，这边要是自己另起一套名字，两边就对不上了 */
import { guixuMark } from '../mark.js';
/* 产物栏现在是工作区【内部】的一列，所以由 ChatView 渲染它。
   components 是局部注册 —— main.js 里注册过不算数，
   这个模板里要用就得在这儿再注册一次（不然它会被当成未知标签，渲染成空） */
import FilesPanel from './FilesPanel.js';

export default {
  name: 'ChatView',
  components: { FilesPanel },
  setup() {
    // 共享 store 展开后仍是 ref 对象本身，响应性不丢，
    // 模板里的插值和事件绑定一个字都不用改
    const store = Vue.inject('store');
    // 字典另起别名 i18n：对话流用的是 v-for="(t, ti) in turns"，
    // 循环内的 t 是 turn 对象，会把 store 里的字典 t 遮住——
    // 循环里那些本该取词的地方就取成了 turn 上不存在的字段，
    // 按钮有框无字（取消、预览、无输出提示都栽在这上面）
    const t = store.t;

    /* 时间基准。用本地日期，不用 toISOString——
       那个是 UTC，东八区晚上八点后会显示成第二天 */
    const d = new Date();
    const today = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-`
                + String(d.getDate()).padStart(2, '0');

    /* 空态那三条快捷语。
       它们不是提示文案——点了会【直接发出去】，所以按"一句话"的标准要求：

       ① 自足。第一句前面没有前文，所以「这些表」「那么那张表」这种回指
          会让 agent 反问"你指哪张"。用户点的是"帮你开口"的按钮，
          收到的却是一句反问，那这个按钮比不给还差。
       ② 是真人会说的第一句。所以不能把答案写进问题里
          （「这 2 张表各有多少行」是在展示数据，不是在给他一个开口的方式）。
       ③ 三条递进：容器有多大 → 近期有什么动静 → 能出什么活。
          前两条"看"，第三条"做"——它顺带把摸底也做了，agent 要写日报
          就得先搞清楚有哪些表、各有哪些字段。

       第二条为什么不是"每张表各有多少条数据"：那是一次性的元信息，
          用户看完就知道了，不会再问第二遍。而"最近有什么变动"是有时效的，
          每天打开问一次都成立——快捷语该是后一种

       所以它们不跟着数据源生成。带表名字段名的句子对第二个用户就不成立了，
       而这三句换个数据源照样自足、照样是真话 */
    const tries = [
      '我们有几张表？',
      '最近有什么数据变动了？',
      '帮我写一篇今天的日报',
    ];

    /* 模型切换器（输入框里那个）。展开态原型没画，所以这一小块是补的：
       贴着按钮上沿浮出来的小面板，用弹窗那套令牌，但不加遮罩——
       换个模型不该把整个工作区压暗一次。

       点别处收起：靠一个 document 上的监听，而不是遮罩层。
       遮罩层为了「点外面能关」这一件事，要往页面上盖一张全屏的东西，
       代价比收益大 */
    const pickOpen = Vue.ref(false);
    const pickWrap = Vue.ref(null);

    /* 模型清单是问上游要的，所以懒加载：没展开过就不请求 */
    const openPick = () => {
      pickOpen.value = !pickOpen.value;
      if (pickOpen.value && !store.modelOptions.value.length) store.loadModelOptions();
    };

    const pickModel = async (name) => {
      pickOpen.value = false;
      await store.switchModel(name);
    };

    const onDocClick = (e) => {
      if (!pickOpen.value) return;
      const el = pickWrap.value;
      if (el && !el.contains(e.target)) pickOpen.value = false;
    };

    Vue.onMounted(() => document.addEventListener('click', onDocClick));
    Vue.onUnmounted(() => document.removeEventListener('click', onDocClick));

    /* 当前未解决的中断。中断是串行的——中断了就停，所以任意时刻
       最多一个未解决；但**一轮里可以有好几张**（答完一个又中断一次）。
       从 turns 派生，不另存一份状态：另存就要在新建会话、刷新、续跑
       三处都记得同步，迟早漏一处 */
    const activeConfirm = Vue.computed(() => {
      const list = store.turns.value;
      for (let i = list.length - 1; i >= 0; i--) {
        const cards = list[i].confirms || [];
        for (let j = 0; j < cards.length; j++) {
          if (!cards[j].resolved) return { ti: i, ci: j, confirm: cards[j] };
        }
      }
      return null;
    });

    /* 已解决的确认卡可以点开回看当初的候选 / 差异（design 交互层 §二）。
       ask 没有可展开的东西——问题和答案都已经在卡上了 */
    const toggleConfirm = (c) => {
      if (c.kind === 'confirm') c.open = !c.open;
    };

    // ask 和手打确认都要输入框；普通确认卡片只要两个按钮
    const needsInput = (c) => c.kind === 'ask' || c.confirm_mode === 'typed';
    const inputHint = (c) => (c.kind === 'ask'
      ? '或者，直接说……'
      : `请输入「${c.confirm_hint}」`);

    const submitFree = (box) => {
      const v = (box.confirm.free_input || '').trim();
      if (v) store.answerConfirm(box.ti, box.ci, v);
    };

    return {
      ...store, i18n: t, today, tries, pickOpen, pickWrap, openPick, pickModel,
      activeConfirm, needsInput, inputHint, submitFree, toggleConfirm,
    };
  },
  template: `
<main class="stage">

  <!-- 工作区头分两层：上面是「这是哪个会话」，一条线，下面是「看它的哪一面」。
       线是这两层之间唯一的分隔手段 —— 它得在，因为上下说的是两件事。

       空态没有头：不放标题、不放分隔线、不放切换。
       「新会话」这三个字是废话，用户点进来当然知道这是新会话。
       而且空态还不到「切哪一面」的时候——两个视图都是空的 -->
  <div class="stage-head" v-if="turns.length">
    <div class="stage-bar">
      <button v-if="leftShut" class="rail-icon" @click="leftShut = false" title="展开左侧栏">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
          <path d="M10 3 5 8l5 5"/>
        </svg>
      </button>
      <span class="stage-title">{{ currentTitle }}</span>
      <div class="stage-meta">
        <span class="t-meta">第 {{ turns.length }} 轮</span>
        <span class="t-meta" v-if="lastElapsed != null">上轮 {{ lastElapsed }}ms</span>
      </div>
    </div>

    <!-- 对话 / 轨迹 / 产物：三个都是【这一个会话】的面，长相不区分。
         「产物」不是页签，它开合右栏——但用户看的是「这一面」，不是机制。
         见 docs/design-language.md 5.6 -->
    <div class="vtabs">
      <button :class="{on: leftTab === 'sessions'}"
              @click="leftTab = 'sessions'">对话</button>
      <button :class="{on: leftTab === 'trace'}"
              @click="leftTab = 'trace'">轨迹</button>
      <button :class="{on: railOpen}" @click="toggleRail">产物</button>
    </div>
  </div>

  <!-- ---------- 轨迹页 ----------
       它回答的是「刚才那几分钟，它到底干了什么、卡在哪」。
       骨架仿 DeepSeek Harness：指标 → 时间轴 → 分组流 → 详情。
       砍掉了它那套 Payload / Schema / JSON —— 那是给工程师 debug 的，
       我们的用户是拖 Excel 进来问问题的人 -->
  <div v-if="leftTab === 'trace'" class="trace">

    <div v-if="!allTools.length" class="empty-note" style="padding:60px 0">
      本次会话还没有工具调用<br>
      <span style="font-size:11px">{{ i18n.traceEmpty }}</span>
    </div>

    <template v-else>
      <!-- ① 指标条：它回答「这次一共费了多少」 -->
      <div class="trace-stats">
        <div class="stat">
          <span class="stat-k">对话轮次</span>
          <span class="stat-v">{{ roundsWithTools.length }}</span>
        </div>
        <div class="stat">
          <span class="stat-k">工具调用</span>
          <span class="stat-v">{{ allTools.length }}</span>
        </div>
        <div class="stat">
          <span class="stat-k">工具总耗时</span>
          <span class="stat-v">{{ (totalToolMs / 1000).toFixed(1) }}<span class="stat-u">秒</span></span>
        </div>
        <div class="stat">
          <span class="stat-k">最慢一步</span>
          <span class="stat-v">{{ maxToolMs }}<span class="stat-u">毫秒</span></span>
        </div>
      </div>

      <!-- ② 时间轴：一条 = 一轮，色块长度 = 那一步的耗时。
           所有轮共用同一个比例尺（maxRoundMs），所以第 1 轮比第 3 轮长
           是真的长——按各轮自己归一化的话每轮都会被拉满，就白画了 -->
      <div class="gantt">
        <div v-for="r in roundsWithTools" :key="r.roundIndex"
             class="gantt-row" :class="{run: r.running}">
          <span class="gantt-no">第 {{ r.roundIndex + 1 }} 轮</span>
          <div class="gantt-track">
            <i v-for="(t, ti) in r.tools" :key="ti"
               :style="{ width: Math.max(1.5, (t.ms || 0) / maxRoundMs * 100) + '%' }"
               :class="t.state"></i>
          </div>
          <span class="gantt-ms">{{ (r.totalMs / 1000).toFixed(1) }}s</span>
        </div>
      </div>

      <!-- ③ 分组流：一轮一组，一组里是「Agent 做的每一件事」 -->
      <div v-for="r in roundsWithTools" :key="r.roundIndex"
           class="round" :id="'round-' + r.roundIndex">
        <div class="round-head">
          <span class="round-no">第 {{ r.roundIndex + 1 }} 轮</span>
          <span class="round-q">{{ r.question }}</span>
          <span class="round-at">{{ (r.totalMs / 1000).toFixed(1) }}s · {{ r.tools.length }} 步</span>
        </div>

        <template v-for="(t, ti) in r.tools" :key="ti">
          <button class="step" :class="[t.state, {open: t.open}]"
                  @click="t.open = !t.open">
            <span class="step-nm">{{ t.name }}</span>
            <span class="step-arg">{{ toolGist(t) }}</span>
            <span class="step-ms">{{ t.ms != null ? t.ms + 'ms' : '—' }}</span>
            <span class="step-badge" :class="t.state">{{ stateLabel(t.state) }}</span>
          </button>

          <!-- 就地展开，不做侧滑面板 —— 点开的东西就该在点的地方长出来 -->
          <div class="step-detail" v-if="t.open">
            <dl class="kv" v-if="t.args && Object.keys(t.args).length">
              <template v-for="(v, k) in t.args" :key="k">
                <dt>{{ k }}</dt>
                <dd>{{ fmtVal(v) }}</dd>
              </template>
            </dl>

            <template v-if="t.parsed && t.parsed.sql">
              <div class="detail-k">执行语句</div>
              <pre v-html="highlightSql(t.parsed.sql)"></pre>
            </template>

            <div class="detail-k" v-if="t.parsed">结果</div>
            <pre v-if="t.parsed">{{ prettyJson(t.parsed) }}</pre>
            <pre v-else-if="t.raw">{{ t.raw }}</pre>
            <div class="detail-rows" v-else>{{ i18n.noToolOutput }}</div>
          </div>
        </template>
      </div>
    </template>
  </div>

  <!-- ---------- 空态 ----------
       一块待机的暗面：标记、一句话、三个例子，别的都不要。
       这里没有读数表——「数据源 / 模型 / 时间」那三行是仪表盘的做法，
       用户点进来是想问一句话，不是想读一份体检报告 -->
  <div v-else-if="!turns.length && !busy" class="void">
    <!-- 标记和文字块是【并列】的两块，不是父子：
         两者都相对 .void 定位，标记钉在正中心、文字从中心往下排。
         把标记放进 .void-in 里的话，那个绝对定位的块就成了它的包含块，
         标记会跟着文字跑 -->
    <div class="void-mark">${guixuMark()}</div>

    <div class="void-in">
      <div class="void-h">{{ i18n.welcomeTitle }}</div>
      <div class="void-s">{{ i18n.welcomeSubtitle }}</div>

      <div class="void-try">
        <div class="void-rule"></div>
        <button v-for="(q, i) in tries" :key="i" class="try" @click="ask(q)">{{ q }}</button>
      </div>
    </div>
  </div>

  <!-- ---------- 对话流 ---------- -->
  <div v-else class="stream" ref="streamEl">
    <div class="thread">
      <div v-for="(t, ti) in turns" :key="ti">

        <!-- 你说的话 -->
        <div class="turn op" v-if="t.question">
          <div class="turn-head">
            <span class="turn-who">你</span>
            <span class="turn-rule"></span>
            <span class="turn-at">{{ clockTime(t.askedAt) }}</span>
          </div>
          <div class="turn-text">{{ t.question }}</div>
        </div>

        <!-- 归墟那一侧。它有小头像——「谁在说话」一眼可辨，
             比读一个标签快得多 -->
        <div class="turn ag has-av">
          <div class="turn-av">${guixuMark()}</div>
          <div class="turn-head">
            <span class="turn-who">归墟</span>
            <span class="turn-rule"></span>
            <span class="turn-at">{{ clockTime(t.answeredAt) }}</span>
          </div>

          <!-- 阶段提示。「正在理解你的问题…」不是对话内容，是过程读数 -->
          <div v-if="t.stage" class="turn-stage" :class="{run: busy}">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round">
              <path d="M21 12a9 9 0 1 1-6.22-8.56"></path>
            </svg>
            {{ t.stage }}
          </div>

          <!-- 思考与工具共用一条时间线。
               它们本来就是先后发生的，按 SSE 到达顺序排就够了，
               不必再按轮次重组——重组反而要处理历史会话缺 round 的情况 -->
          <div class="tools" v-if="t.tools.length">
            <template v-for="(tool, i) in t.tools" :key="i">

              <!-- 思考链。语气比工具更轻——它是「过程」，不是「动作」 -->
              <div v-if="tool.kind === 'think'" class="think" :class="{open: tool.open}">
                <button class="think-head" @click="tool.open = !tool.open">
                  <svg class="caret" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                       stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="9 18 15 12 9 6"></polyline>
                  </svg>
                  <span class="think-label">
                    {{ tool.round ? '思考 · 第 ' + tool.round + ' 轮' : '思考' }}
                  </span>
                  <span class="think-gist">{{ thinkGist(tool.text) }}</span>
                </button>
                <div class="think-body" v-if="tool.open">{{ tool.text }}</div>
              </div>

              <!-- 工具调用 -->
              <div v-else class="tool" :class="{open: tool.open}">
                <button class="tool-head" @click="tool.open = !tool.open">
                  <svg class="caret" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                       stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="9 18 15 12 9 6"></polyline>
                  </svg>
                  <span class="nm">{{ tool.name }}</span>
                  <span class="arg">{{ toolGist(tool) }}</span>
                  <span class="ms" v-if="tool.ms != null">{{ tool.ms }}ms</span>
                  <span class="st" :class="tool.state">{{ stateLabel(tool.state) }}</span>
                </button>

                <div class="tool-body" v-if="tool.open">
                  <dl class="kv" v-if="tool.args && Object.keys(tool.args).length">
                    <template v-for="(v, k) in tool.args" :key="k">
                      <dt>{{ k }}</dt>
                      <dd>{{ fmtVal(v) }}</dd>
                    </template>
                  </dl>

                  <div class="sql" v-if="tool.parsed && tool.parsed.sql"
                       v-html="highlightSql(tool.parsed.sql)"></div>

                  <div class="rawbox" v-if="tool.parsed">{{ prettyJson(tool.parsed) }}</div>
                  <div class="rawbox" v-else-if="tool.raw">{{ tool.raw }}</div>
                </div>
              </div>

            </template>
          </div>

          <!-- 已解决的中断在对话流里留一行缩略——它是"发生过什么"的记录。
               一轮里可以有好几张（先问口径、再确认删除），所以是一串。
               **未解决的不在这儿**：所有要你回应的东西都在底部弹窗，
               位置固定，不用在对话流里找（design 交互层 §二） -->
          <template v-for="(c, ci) in t.confirms" :key="'c' + ci">
            <div v-if="c.resolved" class="confirm resolved"
                 :class="{cancelled: c.cancelled}">
              <div class="confirm-head" :class="{foldable: c.kind === 'confirm'}"
                   @click="toggleConfirm(c)">
                <span class="dot">
                  <svg v-if="c.cancelled" viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" stroke-width="3.2" stroke-linecap="round"
                       stroke-linejoin="round">
                    <line x1="7" y1="12" x2="17" y2="12"></line>
                  </svg>
                  <svg v-else viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" stroke-width="3" stroke-linecap="round"
                       stroke-linejoin="round">
                    <polyline points="20 6 9 17 4 12"></polyline>
                  </svg>
                </span>
                {{ confirmTitle(c) }}
                <span class="tag" v-if="c.scope">{{ c.scope }}</span>
                <!-- 确认类可以点开回看候选 / 差异；ask 没有可展开的东西 -->
                <svg v-if="c.kind === 'confirm'" class="fold" :class="{open: c.open}"
                     viewBox="0 0 16 16" fill="none" stroke="currentColor"
                     stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
                  <path d="m4 6 4 4 4-4"></path>
                </svg>
              </div>

              <!-- ask：标题只说"已回答"，问的是什么在这儿 -->
              <div class="confirm-question" v-if="c.kind === 'ask'">{{ c.question }}</div>

              <!-- 只有 ask 需要这一行：答案在这儿。
                   确认卡片的终态 head 已经说完了，再来一行"已执行"是重复。
                   跳过的 ask 也不画：head 已经写着"已跳过"，没有答案可补 -->
              <div class="confirm-verdict" v-if="c.kind === 'ask' && !c.cancelled">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
                     stroke-linecap="round" stroke-linejoin="round">
                  <polyline points="20 6 9 17 4 12"></polyline>
                </svg>
                {{ c.verdict }}
              </div>

              <!-- 展开：当初要动的是哪几条、字段怎么改 -->
              <div class="confirm-body" v-if="c.kind === 'confirm' && c.open">
                <div class="cands" v-if="c.rows && c.rows.length">
                  <table>
                    <thead>
                      <tr><th v-for="col in confirmColumns(c)" :key="col">{{ col }}</th></tr>
                    </thead>
                    <tbody>
                      <tr v-for="(r, ri) in c.rows" :key="ri">
                        <td v-for="col in confirmColumns(c)" :key="col">{{ r[col] ?? '—' }}</td>
                      </tr>
                    </tbody>
                  </table>
                </div>

                <div v-if="c.diffs && c.diffs.length">
                  <div class="diff-row" v-for="(d, di) in c.diffs" :key="di">
                    <div class="diff-field">{{ d.field }}</div>
                    <div class="diff-vals">
                      <span class="diff-from">{{ d.from ?? '空' }}</span>
                      <span class="diff-arrow">→</span>
                      <span class="diff-to">{{ d.to }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <!-- 产物卡。和右栏的 .art 是同一件事的两个粒度：
               那边是清单，这边是「这一轮产出了它」 -->
          <div v-for="(a, ai) in t.artifacts" :key="'a' + ai" class="artifact">
            <div class="artifact-icon" :class="a.kind">
              <svg v-if="a.kind === 'xlsx'" viewBox="0 0 16 16" fill="none"
                   stroke="currentColor" stroke-width="1.4">
                <rect x="2.2" y="3" width="11.6" height="10" rx="1.6"/>
                <path d="M2.2 6.6h11.6M6.6 6.6V13"/>
              </svg>
              <svg v-else viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
                <rect x="2.2" y="3" width="11.6" height="10" rx="1.6"/>
                <path d="M4.6 6.5h6.8M4.6 8.6h6.8M4.6 10.7h4"/>
              </svg>
            </div>
            <div class="artifact-meta">
              <div class="artifact-name">{{ a.name }}</div>
              <div class="artifact-sub">
                <span v-if="a.rows != null">{{ a.rows }} 条记录 · </span>{{ a.label }}
              </div>
            </div>
            <div class="artifact-acts">
              <button class="btn" @click="previewFile(a)">{{ i18n.preview }}</button>
              <button class="btn" @click="download(a.path, a.name)">下载</button>
            </div>
          </div>

          <!-- 回答（确认卡的结论已在卡片里，不再重复一遍） -->
          <!-- 续跑后模型的回答也是正文，照常渲染。
               卡片那头只留一行终态，两者不重复 -->
          <div class="prose" v-if="t.answer" v-html="md(t.answer)"></div>

          <!-- 这一轮被中断：不是回答，是一条状态提示 -->
          <div class="turn-notice" v-if="t.notice">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
                 stroke-linecap="round" stroke-linejoin="round">
              <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
              <line x1="12" y1="9" x2="12" y2="13"></line>
              <line x1="12" y1="17" x2="12.01" y2="17"></line>
            </svg>
            {{ t.notice }}
          </div>

          <!-- 等待中 -->
          <div v-if="ti === turns.length - 1 && busy && !t.answer && !t.notice" class="thinking">
            <i></i><i></i><i></i>
          </div>
        </div>

      </div>
    </div>
  </div>

  <!-- 产物栏：工作区内部的一列，不是并排的第三栏。
       它列的是「这次对话产出了什么」，和「有哪些会话」不是同一层级。

       只在【有过对话】的时候出现：空态还没有"这次对话"，
       摆一个 0 加一句"还没有产出文件"，是在回答一个还没被问的问题。
       它走了之后，空态那块才是真的待机——一整片暗面，别的什么都没有 -->
  <files-panel v-if="turns.length"></files-panel>

  <!-- 预览：浮在工作区上的弹窗。遮罩只盖工作区——左栏还亮着、还能点，
       看一个产出不该把整个应用锁住。见 docs/design-language.md 5.6 -->
  <div class="modal-mask" v-if="viewer" @click.self="viewer = null">
    <div class="modal">
      <div class="modal-head">
        <span class="modal-title">{{ viewer.name }}</span>
        <button class="modal-x" @click="viewer = null" title="关闭预览">
          <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M3 3l6 6M9 3l-6 6"/>
          </svg>
        </button>
      </div>

      <div class="modal-body">
        <table v-if="viewer.kind === 'xlsx'">
          <thead>
            <tr>
              <th>#</th>
              <th v-for="c in viewer.columns" :key="c">{{ c }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in viewer.rows" :key="i">
              <td class="num">{{ i + 1 }}</td>
              <td v-for="(cell, j) in row" :key="j">{{ cell }}</td>
            </tr>
          </tbody>
        </table>

        <iframe v-else-if="viewer.kind === 'pdf'" class="modal-frame" :src="viewer.url"></iframe>

        <div v-else class="modal-note">
          这种格式没法在这里预览，下载后用系统程序打开
        </div>
      </div>

      <div class="modal-note" v-if="viewer.kind === 'xlsx' && viewer.total > viewer.rows.length">
        显示前 {{ viewer.rows.length }} 行，共 {{ viewer.total }} 行
      </div>

      <div class="modal-foot">
        <button class="btn" @click="download(viewer.path, viewer.name)">下载</button>
        <button class="btn solid" @click="viewer = null">关闭</button>
      </div>
    </div>
  </div>

  <!-- 底部弹窗：所有未解决的中断都在这里 —— ask_user 的问题、确认卡片的候选。
       两种长相，同一个容器（design 交互层 §二）。

       它占的是 composer 的位置，不是浮在上面：中断时输入区收起，
       屏幕上只有一个能打字的地方，用户不用判断"该在哪个框里回答" -->
  <div class="ask-dock" v-if="activeConfirm">
    <div class="ask-panel" :class="{danger: activeConfirm.confirm.danger}">
      <div class="confirm-head">
        <span class="dot">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
               stroke-linecap="round" stroke-linejoin="round">
            <path d="M12 3a9 9 0 1 0 9 9"/>
            <path d="M12 8v4"/>
            <circle cx="12" cy="16" r=".8" fill="currentColor" stroke="none"/>
          </svg>
        </span>
        {{ confirmTitle(activeConfirm.confirm) }}
        <span class="tag" v-if="activeConfirm.confirm.scope">{{ activeConfirm.confirm.scope }}</span>
      </div>

      <div class="confirm-body">
        <!-- ask：问题本身 -->
        <div class="ask-question" v-if="activeConfirm.confirm.kind === 'ask'">
          {{ activeConfirm.confirm.question }}
        </div>

        <!-- ask：可选方向。点了直接当回答发出去 -->
        <div class="ask-options"
             v-if="activeConfirm.confirm.kind === 'ask' && activeConfirm.confirm.options.length">
          <button v-for="(o, oi) in activeConfirm.confirm.options" :key="oi"
                  class="ask-opt" :disabled="busy"
                  @click="answerConfirm(activeConfirm.ti, activeConfirm.ci, o)">{{ o }}</button>
        </div>

        <!-- 确认卡片：候选清单 -->
        <div class="cands" v-if="activeConfirm.confirm.rows && activeConfirm.confirm.rows.length">
          <table>
            <thead>
              <tr><th v-for="c in confirmColumns(activeConfirm.confirm)" :key="c">{{ c }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="(r, ri) in activeConfirm.confirm.rows" :key="ri">
                <td v-for="c in confirmColumns(activeConfirm.confirm)" :key="c">{{ r[c] ?? '—' }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 确认卡片：改写对照 -->
        <div v-if="activeConfirm.confirm.diffs && activeConfirm.confirm.diffs.length">
          <div class="diff-row" v-for="(d, di) in activeConfirm.confirm.diffs" :key="di">
            <div class="diff-field">{{ d.field }}</div>
            <div class="diff-vals">
              <span class="diff-from">{{ d.from ?? '空' }}</span>
              <span class="diff-arrow">→</span>
              <span class="diff-to">{{ d.to }}</span>
            </div>
          </div>
        </div>

        <div class="confirm-note" v-if="activeConfirm.confirm.note">{{ activeConfirm.confirm.note }}</div>

        <!-- 自由输入：ask 用它回答，手打确认用它敲「删除 166 条」 -->
        <input v-if="needsInput(activeConfirm.confirm)"
               class="typed-confirm ask-input"
               v-model="activeConfirm.confirm.free_input"
               :placeholder="inputHint(activeConfirm.confirm)"
               :disabled="busy"
               @keydown.enter.prevent="submitFree(activeConfirm)">

        <div class="confirm-actions">
          <button class="btn" @click="answerConfirm(activeConfirm.ti, activeConfirm.ci, '取消')"
                  :disabled="busy">{{ i18n.cancel }}</button>

          <!-- ask：自由输入 → 发送 -->
          <button v-if="activeConfirm.confirm.kind === 'ask'"
                  class="btn solid"
                  :disabled="busy || !activeConfirm.confirm.free_input.trim()"
                  @click="submitFree(activeConfirm)">发送</button>

          <!-- 手打确认 -->
          <button v-else-if="activeConfirm.confirm.confirm_mode === 'typed'"
                  class="btn" :class="activeConfirm.confirm.danger ? 'danger' : 'solid'"
                  :disabled="busy || !activeConfirm.confirm.free_input.trim()"
                  @click="submitFree(activeConfirm)">执行</button>

          <!-- 普通确认 -->
          <button v-else class="btn"
                  :class="activeConfirm.confirm.danger ? 'danger' : 'solid'"
                  :disabled="busy"
                  @click="answerConfirm(activeConfirm.ti, activeConfirm.ci, activeConfirm.confirm.confirm_hint)">
            {{ activeConfirm.confirm.verb }}
          </button>
        </div>
      </div>
    </div>
  </div>

  <!-- 中断时收起输入区：屏幕上只有一个能打字的地方 -->
  <div class="composer" v-if="!activeConfirm">
    <div class="composer-in">
      <!-- 拖进来就传。整块输入框都是落点，不另设一个「拖到这里」的虚线框——
           那个框本身就是一块多余的图形 -->
      <div class="field" :class="{drop: dragging}"
           @dragover.prevent="dragging = true"
           @dragleave="dragLeave"
           @drop.prevent="onDrop">
        <button class="upload-btn" @click="triggerUpload" :disabled="busy"
                title="上传 Excel 文件">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <path d="M21.44 11.05l-9.19 9.19a6 6 0 0 1-8.49-8.49l9.19-9.19a4 4 0 0 1 5.66 5.66l-9.2 9.19a2 2 0 0 1-2.83-2.83l8.49-8.48"></path>
          </svg>
        </button>
        <input type="file" ref="fileInput" accept=".xlsx,.xls"
               style="display:none" @change="handleFileSelect">

        <textarea ref="inputEl" v-model="input" rows="1"
                  :disabled="busy"
                  :placeholder="busy ? '正在处理…' : '问点什么，或把 Excel 拖进来'"
                  @keydown.enter.exact.prevent="send"
                  @input="autoGrow"></textarea>

        <!-- 换模型和调思考强度都是「这次对话怎么干活」这个决定了才做的动作，
             所以它们在输入框里，不在顶栏——顶栏是「这个应用是什么状态」 -->
        <div class="model-pick-wrap" ref="pickWrap" v-if="configs.length">
          <button class="model-pick" @click="openPick"
                  :title="'当前模型：' + (currentModel || '未选')">
            <span class="mp-name">{{ currentModel || '未选模型' }}</span>
            <svg class="chev" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M2.5 4.5 6 8l3.5-3.5"/>
            </svg>
          </button>

          <div class="pick-menu" v-if="pickOpen">
            <!-- 模型：问上游要的完整清单，不是配置里存的那一个 -->
            <div class="pm-label t-kicker-zh">模型</div>
            <div class="pm-list">
              <div v-if="modelState.loading" class="pm-note">正在向上游取清单…</div>
              <div v-else-if="modelState.message" class="pm-note">{{ modelState.message }}</div>
              <button v-for="m in modelOptions" :key="m"
                      :class="{on: m === currentModel}"
                      @click="pickModel(m)">{{ m }}</button>
            </div>

            <div class="pm-rule"></div>

            <!-- 思考强度：应用级参数，所有配置共享，所以不跟上面那组走 -->
            <div class="pm-label t-kicker-zh">思考强度</div>
            <div class="seg pm-seg">
              <button v-for="o in reasoningOptions" :key="o.value"
                      :class="{on: o.value === reasoningEffort}"
                      @click="setReasoningEffort(o.value)">{{ o.label }}</button>
            </div>
          </div>
        </div>

        <button class="send" @click="send" :disabled="busy || !input.trim()">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M2.5 8h11M9 3.5 13.5 8 9 12.5"/>
          </svg>
        </button>
      </div>

      <!-- 「已就绪」在这儿，不在顶栏：顶栏是「这个应用的状态」，
           而连得上连不上和「你要不要发这句话」直接相关，属于输入区。
           它跟强调色走，不跟信号色——本地应用连不上模型就进不了工作台，
           这个点永远亮着，不承载任何会变的信息。既然不会变，它就是装饰 -->
      <div class="hint">
        <span>Enter 发送</span>
        <span>Shift + Enter 换行</span>
        <span class="hint-live">● 已就绪</span>
      </div>
    </div>
  </div>

</main>
`,
};
