/* 中栏：会话头、轨迹页、对话流、输入区。
   这是最大的一块，承载工具卡片、思考气泡、产物卡片、确认卡片 */
export default {
  name: 'ChatView',
  setup() {
    // 共享 store 展开后仍是 ref 对象本身，响应性不丢，
    // 模板里的插值和事件绑定一个字都不用改
    return { ...Vue.inject('store') };
  },
  template: `
  <main class="col glass" style="overflow:hidden">
    <div class="chat-head">
      <button v-if="leftShut" class="icon-btn" @click="leftShut = false" title="展开左侧栏">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
             stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 18 15 12 9 6"></polyline>
        </svg>
      </button>
      <div class="chat-title">
        {{ leftTab === 'trace' ? '执行轨迹' : currentTitle }}
      </div>
      <!-- 只在右栏收起时出现。展开后右栏自己头部就有收起入口，
           这里再留一个「收起右栏」是两个按钮干同一件事 -->
      <button v-if="leftTab === 'sessions' && !railOpen" class="btn"
              @click="toggleRail" title="展开右侧栏（产物）">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="3" width="18" height="18" rx="2"></rect>
          <line x1="15" y1="3" x2="15" y2="21"></line>
        </svg>
        {{ t.artifacts }}
      </button>
    </div>

    <!-- ---------- 轨迹页：独立视图，占满中栏 ---------- -->
    <div v-if="leftTab === 'trace'" class="trace-page">
      <div class="trace-page-inner">

        <div v-if="!allTools.length" class="empty-note" style="padding:60px 0">
          本次会话还没有工具调用<br>
          <span style="font-size:11px">{{ t.traceEmpty }}</span>
        </div>

        <template v-else>
          <dl class="trace-summary">
            <div><dt>总步数</dt><dd>{{ allTools.length }}</dd></div>
            <div><dt>工具耗时</dt><dd>{{ (totalToolMs / 1000).toFixed(1) }}s</dd></div>
            <div><dt>成功</dt><dd style="color:var(--ok)">{{ stateCount.ok }}</dd></div>
            <div><dt>失败 / 拒绝</dt>
              <dd :style="{color: (stateCount.err + stateCount.warn) ? 'var(--err)' : null}">
                {{ stateCount.err + stateCount.warn }}
              </dd>
            </div>
          </dl>

          <div v-for="r in roundsWithTools" :key="r.roundIndex"
               class="trace-round" :id="'round-' + r.roundIndex">
            <div class="trace-round-head">
              <span class="no">第 {{ r.roundIndex + 1 }} 轮</span>
              <span class="q">{{ r.question }}</span>
              <span class="m">{{ r.tools.length }} 步 · {{ (r.totalMs / 1000).toFixed(1) }}s</span>
            </div>

            <div v-for="(t, ti) in r.tools" :key="ti" class="trace-step" :class="t.state">
              <div class="step-head" @click="t.open = !t.open">
                <span class="step-name">{{ t.name }}</span>
                <span class="step-arg">{{ toolGist(t) }}</span>
                <span class="step-ms">{{ t.ms != null ? t.ms + 'ms' : '—' }}</span>
                <span class="step-state" :class="t.state">{{ stateLabel(t.state) }}</span>
              </div>

              <div class="step-bar" v-if="t.ms != null">
                <i :style="{ width: Math.max(2, (t.ms / maxToolMs) * 100) + '%' }"
                   :class="t.state"></i>
              </div>

              <div class="step-body" v-if="t.open">
                <dl class="kv" v-if="t.args && Object.keys(t.args).length">
                  <template v-for="(v, k) in t.args" :key="k">
                    <dt>{{ k }}</dt>
                    <dd>{{ fmtVal(v) }}</dd>
                  </template>
                </dl>
                <div class="sql" v-if="t.parsed && t.parsed.sql"
                     v-html="highlightSql(t.parsed.sql)"></div>
                <div class="rawbox" v-if="t.parsed">{{ prettyJson(t.parsed) }}</div>
                <div class="rawbox" v-else-if="t.raw">{{ t.raw }}</div>
                <div class="set-hint" v-else>{{ t.noToolOutput }}</div>
              </div>
            </div>
          </div>
        </template>

      </div>
    </div>

    <!-- ---------- 对话视图 ---------- -->
    <template v-else>
    <div class="chat-body">
    <div class="stream" ref="streamEl">
      <div class="stream-inner">

        <!-- 欢迎屏 -->
        <div v-if="!turns.length && !busy" class="hello">
          <div class="hello-mark">
            <svg viewBox="0 0 48 48" fill="none">
              <defs>
                <linearGradient id="hm-lit" gradientUnits="userSpaceOnUse" x1="24" y1="4" x2="24" y2="44">
                  <stop offset="0" stop-color="var(--rose-hi)"/>
                  <stop offset="0.5" stop-color="var(--rose-mid)"/>
                  <stop offset="1" stop-color="var(--rose-mid)" stop-opacity=".62"/>
                </linearGradient>
                <linearGradient id="hm-shade" gradientUnits="userSpaceOnUse" x1="24" y1="4" x2="24" y2="44">
                  <stop offset="0" stop-color="var(--rose-mid)"/>
                  <stop offset="0.5" stop-color="var(--rose-lo)"/>
                  <stop offset="1" stop-color="var(--rose-lo)" stop-opacity=".48"/>
                </linearGradient>
                <linearGradient id="hm-tick" gradientUnits="userSpaceOnUse" x1="24" y1="4" x2="24" y2="44">
                  <stop offset="0" stop-color="var(--mark)" stop-opacity=".72"/>
                  <stop offset="1" stop-color="var(--mark)" stop-opacity=".3"/>
                </linearGradient>
                <linearGradient id="hm-ring" gradientUnits="userSpaceOnUse" x1="24" y1="4" x2="24" y2="44">
                  <stop offset="0" stop-color="var(--mark)" style="stop-opacity:var(--ring-hi)"/>
                  <stop offset="0.5" stop-color="var(--mark)" style="stop-opacity:var(--ring-mid)"/>
                  <stop offset="1" stop-color="var(--mark)" style="stop-opacity:var(--ring-lo)"/>
                </linearGradient>
                <!-- 扫掠尾迹：透明起、亮收，头部才是光点 -->
                <linearGradient id="hm-arc" gradientUnits="userSpaceOnUse"
                                x1="24" y1="3" x2="38.85" y2="9.15">
                  <stop offset="0" stop-color="var(--rose-mid)" stop-opacity="0"/>
                  <stop offset="0.55" stop-color="var(--rose-mid)" stop-opacity=".45"/>
                  <stop offset="1" stop-color="var(--rose-hi)" stop-opacity=".95"/>
                </linearGradient>
                <radialGradient id="hm-core">
                  <stop offset="0" stop-color="var(--rose-core-hi)"/>
                  <stop offset="0.45" stop-color="var(--rose-core)"/>
                  <stop offset="1" stop-color="var(--rose-core)" stop-opacity=".22"/>
                </radialGradient>
                <radialGradient id="hm-halo">
                  <stop offset="0" stop-color="var(--rose-hi)" style="stop-opacity:var(--rose-halo)"/>
                  <stop offset="0.55" stop-color="var(--rose-hi)" style="stop-opacity:calc(var(--rose-halo) * .38)"/>
                  <stop offset="1" stop-color="var(--rose-hi)" stop-opacity="0"/>
                </radialGradient>
                <filter id="hm-glow" x="-300%" y="-300%" width="700%" height="700%">
                  <feGaussianBlur stdDeviation="1.4"/>
                </filter>
                <filter id="hm-spark" x="-400%" y="-400%" width="900%" height="900%">
                  <feGaussianBlur stdDeviation="0.45"/>
                </filter>
              </defs>

              <circle cx="24" cy="24" r="23.5" fill="url(#hm-halo)"/>

              <!-- 12 个方位各一条径向细线，0/90/180/270 为主刻度 -->
              <g class="hm-ticks" stroke="url(#hm-tick)">
                <line x1="24" y1="4.1" x2="24" y2="0.8" stroke-width="1.22" transform="rotate(0 24 24)"/>
                <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".74" transform="rotate(30 24 24)"/>
                <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".74" transform="rotate(60 24 24)"/>
                <line x1="24" y1="4.1" x2="24" y2="0.8" stroke-width="1.22" transform="rotate(90 24 24)"/>
                <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".74" transform="rotate(120 24 24)"/>
                <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".74" transform="rotate(150 24 24)"/>
                <line x1="24" y1="4.1" x2="24" y2="0.8" stroke-width="1.22" transform="rotate(180 24 24)"/>
                <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".74" transform="rotate(210 24 24)"/>
                <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".74" transform="rotate(240 24 24)"/>
                <line x1="24" y1="4.1" x2="24" y2="0.8" stroke-width="1.22" transform="rotate(270 24 24)"/>
                <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".74" transform="rotate(300 24 24)"/>
                <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".74" transform="rotate(330 24 24)"/>
              </g>
              <circle class="hm-ring" cx="24" cy="24" r="14"
                      stroke="url(#hm-ring)" stroke-width=".8"></circle>

              <g class="hm-rose">
                <path d="M24 5 L24 19.5 L19.5 24 Z"  fill="url(#hm-lit)"/>
                <path d="M24 5 L28.5 24 L24 19.5 Z"  fill="url(#hm-shade)"/>
                <path d="M24 43 L24 28.5 L19.5 24 Z" fill="url(#hm-lit)"   opacity=".88"/>
                <path d="M24 43 L28.5 24 L24 28.5 Z" fill="url(#hm-shade)" opacity=".88"/>
                <path d="M43 24 L24 19.5 L28.5 24 Z" fill="url(#hm-lit)"   opacity=".94"/>
                <path d="M43 24 L28.5 24 L24 28.5 Z" fill="url(#hm-shade)" opacity=".94"/>
                <path d="M5 24 L24 19.5 L19.5 24 Z"  fill="url(#hm-lit)"   opacity=".94"/>
                <path d="M5 24 L19.5 24 L24 28.5 Z"  fill="url(#hm-shade)" opacity=".94"/>

                <circle cx="24" cy="24" r="3.4" fill="var(--rose-hi)"
                        style="opacity:var(--rose-core-glow)" filter="url(#hm-glow)"></circle>
                <circle cx="24" cy="24" r="2.5" fill="url(#hm-core)"></circle>
                <circle cx="24" cy="6.9" r="1.15" fill="var(--rose-spark)"
                        opacity=".95" filter="url(#hm-spark)"></circle>
              </g>

              <!-- 扫描弧：盘面静止，只有这道光在转。罗盘转起来「指向」就没了意义，
                   扫掠才是「工具正在工作」的表达。
                   巡航半径从 19 提到 21——19 正好是芒尖尖端的位置，光点会撞上去 -->
              <g class="hm-sweep">
                <circle class="hm-sweep-glow" cx="38.85" cy="9.15" r="3.4"
                        fill="var(--rose-hi)" opacity=".26"></circle>
                <path class="hm-sweep-arc" d="M24 3 A21 21 0 0 1 38.85 9.15"
                      stroke="url(#hm-arc)" stroke-width="1.9"
                      stroke-linecap="round" fill="none"></path>
                <circle class="hm-sweep-dot" cx="38.85" cy="9.15" r="1.6"
                        fill="var(--rose-mid)"></circle>
                <circle class="hm-sweep-dot" cx="38.85" cy="9.15" r=".7"
                        fill="var(--rose-hi)"></circle>
              </g>
            </svg>
          </div>
          <h2>{{ t.welcomeTitle }}</h2>
          <p>{{ t.welcomeSubtitle }}</p>
          <div class="hello-chips">
            <button class="chip" v-for="q in samples" :key="q" @click="ask(q)">{{ q }}</button>
          </div>
        </div>

        <!-- 对话轮次 -->
        <div v-for="(t, ti) in turns" :key="ti" class="turn">
          <div class="turn-user" v-if="t.question">
            <div class="bubble">{{ t.question }}</div>
          </div>

          <div class="turn-bot" style="margin-top:12px">
            <div class="avatar">
              <!-- 21px 下刻度环会糊成一团，这里去掉环，只留芒星、航迹弧和落点 -->
              <svg viewBox="0 0 48 48" fill="none">
                <defs>
                  <linearGradient id="av-lit" gradientUnits="userSpaceOnUse" x1="24" y1="4" x2="24" y2="44">
                    <stop offset="0" stop-color="var(--rose-hi)"/>
                    <stop offset="0.5" stop-color="var(--rose-mid)"/>
                    <stop offset="1" stop-color="var(--rose-mid)" stop-opacity=".62"/>
                  </linearGradient>
                  <linearGradient id="av-shade" gradientUnits="userSpaceOnUse" x1="24" y1="4" x2="24" y2="44">
                    <stop offset="0" stop-color="var(--rose-mid)"/>
                    <stop offset="0.5" stop-color="var(--rose-lo)"/>
                    <stop offset="1" stop-color="var(--rose-lo)" stop-opacity=".48"/>
                  </linearGradient>
                  <linearGradient id="av-arc" gradientUnits="userSpaceOnUse"
                                  x1="9.28" y1="32.5" x2="35.6" y2="11.6">
                    <stop offset="0" stop-color="var(--rose-mid)" stop-opacity="0"/>
                    <stop offset="0.55" stop-color="var(--rose-mid)" stop-opacity=".38"/>
                    <stop offset="1" stop-color="var(--rose-mid)" stop-opacity=".8"/>
                  </linearGradient>
                  <radialGradient id="av-core">
                    <stop offset="0" stop-color="var(--rose-core-hi)"/>
                    <stop offset="0.45" stop-color="var(--rose-core)"/>
                    <stop offset="1" stop-color="var(--rose-core)" stop-opacity=".22"/>
                  </radialGradient>
                  <filter id="av-glow" x="-300%" y="-300%" width="700%" height="700%">
                    <feGaussianBlur stdDeviation="1.4"/>
                  </filter>
                </defs>

                <path d="M24 5 L24 19.5 L19.5 24 Z"  fill="url(#av-lit)"/>
                <path d="M24 5 L28.5 24 L24 19.5 Z"  fill="url(#av-shade)"/>
                <path d="M24 43 L24 28.5 L19.5 24 Z" fill="url(#av-lit)"   opacity=".88"/>
                <path d="M24 43 L28.5 24 L24 28.5 Z" fill="url(#av-shade)" opacity=".88"/>
                <path d="M43 24 L24 19.5 L28.5 24 Z" fill="url(#av-lit)"   opacity=".94"/>
                <path d="M43 24 L28.5 24 L24 28.5 Z" fill="url(#av-shade)" opacity=".94"/>
                <path d="M5 24 L24 19.5 L19.5 24 Z"  fill="url(#av-lit)"   opacity=".94"/>
                <path d="M5 24 L19.5 24 L24 28.5 Z"  fill="url(#av-shade)" opacity=".94"/>

                <!-- 弧比大尺寸粗：2.4 到 21px 上只剩一个像素 -->
                <path d="M9.28 32.5 A17 17 0 0 1 35.6 11.6" stroke="url(#av-arc)"
                      stroke-width="2.4" stroke-linecap="round" fill="none"/>
                <circle cx="35.6" cy="11.6" r="2" fill="var(--rose-mid)"></circle>
                <circle cx="35.6" cy="11.6" r=".9" fill="var(--rose-hi)"></circle>

                <circle cx="24" cy="24" r="3.2" fill="var(--rose-hi)"
                        style="opacity:var(--rose-core-glow)" filter="url(#av-glow)"></circle>
                <circle cx="24" cy="24" r="2.4" fill="url(#av-core)"></circle>
              </svg>
            </div>
            <div class="turn-body">

              <!-- 阶段提示 -->
              <div v-if="t.stage" class="stage" :class="{run: busy}">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                  <path d="M21 12a9 9 0 1 1-6.22-8.56"></path>
                </svg>
                {{ t.stage }}
              </div>

              <!-- 思考与工具共用一条时间线。
                   它们本来就是先后发生的，按 SSE 到达顺序排就够了，
                   不必再按轮次重组——重组反而要处理历史会话缺 round 的情况 -->
              <template v-for="(tool, i) in t.tools" :key="i">

              <!-- 思考气泡（模型的思维链） -->
              <div v-if="tool.kind === 'think'" class="think"
                   :class="{open: tool.open}">
                <button class="think-head" @click="tool.open = !tool.open">
                  <svg class="caret" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                       stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="9 18 15 12 9 6"></polyline>
                  </svg>
                  <span class="think-label">{{ tool.round ? '思考 · 第 ' + tool.round + ' 轮' : '思考' }}</span>
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
                  <span class="tool-name">{{ tool.name }}</span>
                  <span class="tool-gist">{{ toolGist(tool) }}</span>
                  <span class="tool-time" v-if="tool.ms != null">{{ tool.ms }}ms</span>
                  <span class="tool-dot" :class="tool.state">
                    <svg v-if="tool.state === 'ok'" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="3.4" stroke-linecap="round"
                         stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>
                    <svg v-else-if="tool.state === 'err'" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="3.4" stroke-linecap="round"
                         stroke-linejoin="round">
                      <line x1="18" y1="6" x2="6" y2="18"></line>
                      <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                    <svg v-else-if="tool.state === 'warn'" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="3" stroke-linecap="round"
                         stroke-linejoin="round">
                      <line x1="12" y1="8" x2="12" y2="13"></line>
                      <line x1="12" y1="17" x2="12.01" y2="17"></line>
                    </svg>
                    <svg v-else-if="tool.state === 'wait'" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="3" stroke-linecap="round"
                         stroke-linejoin="round">
                      <line x1="9" y1="7" x2="9" y2="17"></line>
                      <line x1="15" y1="7" x2="15" y2="17"></line>
                    </svg>
                    <svg v-else-if="tool.state === 'cancel'" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="3.2" stroke-linecap="round"
                         stroke-linejoin="round">
                      <line x1="7" y1="12" x2="17" y2="12"></line>
                    </svg>
                  </span>
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

              <!-- 确认卡片 -->
              <div v-if="t.confirm" class="confirm" :class="{resolved: t.confirm.resolved}">
                <div class="confirm-head">
                  <span class="dot">
                    <svg v-if="!t.confirm.resolved" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="2.4" stroke-linecap="round"
                         stroke-linejoin="round">
                      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                      <line x1="12" y1="9" x2="12" y2="13"></line>
                      <line x1="12" y1="17" x2="12.01" y2="17"></line>
                    </svg>
                    <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor"
                         stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
                      <polyline points="20 6 9 17 4 12"></polyline>
                    </svg>
                  </span>
                  {{ confirmTitle(t.confirm) }}
                  <span class="tag">{{ t.confirm.scope }}</span>
                </div>

                <div class="confirm-body">
                  <!-- 候选清单 -->
                  <div class="cands" v-if="t.confirm.rows && t.confirm.rows.length">
                    <table>
                      <thead>
                        <tr><th v-for="c in confirmColumns(t.confirm)" :key="c">{{ c }}</th></tr>
                      </thead>
                      <tbody>
                        <tr v-for="(r, ri) in t.confirm.rows" :key="ri">
                          <td v-for="c in confirmColumns(t.confirm)" :key="c">{{ r[c] ?? '—' }}</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>

                  <!-- 改写对照 -->
                  <div v-if="t.confirm.diffs && t.confirm.diffs.length" style="margin-top:10px">
                    <div class="diff-row" v-for="(d, di) in t.confirm.diffs" :key="di">
                      <div class="diff-field">{{ d.field }}</div>
                      <div class="diff-vals">
                        <span class="diff-from">{{ d.from ?? '空' }}</span>
                        <span class="diff-arrow">→</span>
                        <span class="diff-to">{{ d.to }}</span>
                      </div>
                    </div>
                  </div>

                  <div class="confirm-note" v-if="t.confirm.note">{{ t.confirm.note }}</div>

                  <div class="confirm-actions" v-if="!t.confirm.resolved">
                    <button class="btn" @click="answerConfirm(ti, '取消')"
                            :disabled="busy">{{ t.cancel }}</button>
                    <button class="btn" :class="t.confirm.danger ? 'danger' : 'primary'"
                            @click="answerConfirm(ti, t.confirm.verb)"
                            :disabled="busy">
                      {{ t.confirm.verb }}
                    </button>
                  </div>
                </div>

                <div class="confirm-verdict" v-if="t.confirm.resolved">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
                       stroke-linecap="round" stroke-linejoin="round"
                       style="width:13px;height:13px">
                    <polyline points="20 6 9 17 4 12"></polyline>
                  </svg>
                  {{ t.confirm.verdict }}
                </div>
              </div>

              <!-- 产物卡片 -->
              <div v-for="(a, ai) in t.artifacts" :key="'a' + ai" class="artifact">
                <div class="artifact-icon" :class="a.kind">
                  <svg v-if="a.kind === 'xlsx'" viewBox="0 0 24 24" fill="none"
                       stroke="currentColor" stroke-width="2" stroke-linecap="round"
                       stroke-linejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                    <line x1="9" y1="13" x2="15" y2="13"></line>
                    <line x1="9" y1="17" x2="15" y2="17"></line>
                  </svg>
                  <svg v-else viewBox="0 0 24 24" fill="none" stroke="currentColor"
                       stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                    <polyline points="14 2 14 8 20 8"></polyline>
                    <path d="M9 15h6"></path>
                    <path d="M9 18h3"></path>
                  </svg>
                </div>
                <div class="artifact-meta">
                  <div class="artifact-name">{{ a.name }}</div>
                  <div class="artifact-sub">
                    <span v-if="a.rows != null">{{ a.rows }} 条记录</span>
                    <span v-if="a.rows != null"> · </span>
                    <span>{{ a.label }}</span>
                  </div>
                </div>
                <div class="artifact-acts">
                  <button class="btn" @click="previewFile(a)">{{ t.preview }}</button>
                  <button class="btn" @click="download(a.path, a.name)">下载</button>
                </div>
              </div>

              <!-- 回答（确认卡片的结论已在卡片里，不再重复一遍） -->
              <div class="prose" v-if="t.answer && !(t.confirm && t.confirm.resolved)"
                   v-html="md(t.answer)"></div>

              <!-- 等待中 -->
              <div v-if="ti === turns.length - 1 && busy && !t.answer" class="thinking">
                <i></i><i></i><i></i>
              </div>
            </div>
          </div>
        </div>

      </div>
    </div>

    <!-- 预览：在对话区里分屏，不弹浮层。
         核对表格时往往正需要看着旁边的对话，浮层会把它盖掉 -->
    <aside class="split-view" v-if="viewer">
      <div class="split-head">
        <span class="split-name">{{ viewer.name }}</span>
        <button class="btn" @click="download(viewer.path, viewer.name)">下载</button>
        <button class="icon-btn" @click="viewer = null" title="关闭预览">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
               stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <div class="split-body">
        <template v-if="viewer.kind === 'xlsx'">
          <table class="split-table">
            <thead>
              <tr><th v-for="c in viewer.columns" :key="c">{{ c }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="(row, i) in viewer.rows" :key="i">
                <td v-for="(cell, j) in row" :key="j">{{ cell }}</td>
              </tr>
            </tbody>
          </table>
          <div class="split-note" v-if="viewer.total > viewer.rows.length">
            显示前 {{ viewer.rows.length }} 行，共 {{ viewer.total }} 行
          </div>
        </template>

        <iframe v-else-if="viewer.kind === 'pdf'" class="split-frame" :src="viewer.url"></iframe>

        <div v-else class="split-note" style="margin:auto;text-align:center;line-height:2">
          这种格式没法在这里预览<br>
          <button class="btn" style="margin-top:6px"
                  @click="download(viewer.path, viewer.name)">{{ t.downloadView }}</button>
        </div>
      </div>
    </aside>
    </div>

    <div class="composer">
      <div class="composer-inner" :class="{drop: dragging}"
           @dragover.prevent="dragging = true"
           @dragleave="dragLeave"
           @drop.prevent="onDrop">
        <div class="composer-row">
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
          <button class="send" @click="send" :disabled="busy || !input.trim()">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 2 11 13"></path>
              <path d="M22 2 15 22 11 13 2 9z"></path>
            </svg>
          </button>
        </div>
        <div class="composer-foot">
          <span><kbd>Enter</kbd> 发送 · <kbd>Shift</kbd>+<kbd>Enter</kbd> 换行</span>
          <span class="spacer"></span>
          <span v-if="lastElapsed != null">上轮 {{ lastElapsed }}ms</span>
        </div>
      </div>
    </div>
    </template>
  </main>
`,
};
