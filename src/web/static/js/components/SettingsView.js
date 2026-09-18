/* 设置页。作为 v-else 与主界面互斥，是独立整页 */
export default {
  name: 'SettingsView',
  setup() {
    // 共享 store 展开后仍是 ref 对象本身，响应性不丢，
    // 模板里的插值和事件绑定一个字都不用改
    return { ...Vue.inject('store') };
  },
  template: `
<!-- 根元素不带 v-else：与主界面的互斥关系由父模板的
     <settings-view v-else> 表达，组件内部再写一次会让编译器找不到配对的 v-if -->
<div class="settings-page">
  <div class="glass" style="flex:1;min-height:0;display:flex;flex-direction:column">

    <div class="set-head">
      <button class="icon-btn" @click="goChat" title="返回对话">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
             stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"></polyline>
        </svg>
      </button>
      <h2>{{ t.settings }}</h2>
      <span class="count" v-if="dirtyCount">{{ dirtyCount }} 项未保存</span>
      <span class="spacer"></span>
      <span class="set-msg" v-if="saveMsg" :class="saveMsg.ok ? 'ok' : 'err'">
        {{ saveMsg.text }}
      </span>
      <button class="btn" v-if="dirtyCount" @click="discardDraft">{{ t.discardChanges }}</button>
      <button class="btn primary" @click="saveSettings"
              :disabled="!dirtyCount || saving">
        {{ saving ? '保存中…' : '保存' }}
      </button>
    </div>

    <div class="set-body">
      <nav class="set-nav">
        <button v-for="g in allGroups" :key="g.id"
                :class="{on: activeGroup === g.id}" @click="activeGroup = g.id">
          {{ g.name }}
          <b v-if="groupDirty(g.id)">{{ groupDirty(g.id) }}</b>
        </button>

        <label class="set-adv" :class="{on: advanced}">
          <input type="checkbox" v-model="advanced">
          高级模式
        </label>
      </nav>

      <div class="set-form">
        <div class="set-form-inner">

          <!-- 模型：供应商卡片 + 采样参数 -->
          <template v-if="activeGroup === 'model'">
            <div class="set-group-title">模型供应商</div>

            <div class="prov-list">
              <div v-for="p in providers" :key="p.id"
                   class="prov-card" :class="{open: selectedProvider === p.id,
                                              cur: currentProvider === p.id}">
                <button class="prov-head" @click="pickProvider(p.id)">
                  <span class="prov-name">{{ p.name }}</span>
                  <span class="prov-tag" v-if="currentProvider === p.id">使用中</span>
                  <span class="prov-spacer"></span>
                  <span class="prov-state" :class="p.configured ? 'ok' : ''">
                    {{ p.configured ? '已配置' : '未配置' }}
                  </span>
                  <svg class="caret" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                       stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="9 18 15 12 9 6"></polyline>
                  </svg>
                </button>

                <div class="prov-body" v-if="selectedProvider === p.id">
                  <div class="prov-url">{{ p.base_url }}</div>
                  <div class="prov-note" v-if="p.note">{{ p.note }}</div>

                  <!-- Key。已配置时只显示占位圆点，真值从不进前端 -->
                  <label class="prov-label">API Key</label>
                  <div class="prov-key">
                    <input type="password" class="set-input"
                           :placeholder="p.configured ? '••••••••（已保存，留空表示不修改）' : '粘贴 Key'"
                           :value="keyDraft[p.id] || ''"
                           @input="keyDraft[p.id] = $event.target.value"
                           @keydown.enter="saveKey(p.id)">
                    <button class="btn" @click="saveKey(p.id)">保存</button>
                  </div>

                  <label class="prov-label">
                    模型
                    <button class="prov-fetch" @click="loadModels(p.id)"
                            :disabled="modelState[p.id] && modelState[p.id].loading">
                      {{ modelState[p.id] && modelState[p.id].loading ? '获取中…' : '获取模型' }}
                    </button>
                  </label>

                  <!-- 拉到了就下拉选，没有（或本地部署）就手填。
                       预设那几个名字只是离线兜底，不代表这家现在真的有 -->
                  <template v-if="(modelOptions[p.id] || []).length">
                    <select class="set-input" v-model="modelDraft[p.id]">
                      <option value="">（默认 {{ (modelOptions[p.id] || [])[0] }}）</option>
                      <option v-for="m in modelOptions[p.id]" :key="m" :value="m">{{ m }}</option>
                    </select>
                  </template>
                  <template v-else>
                    <input class="set-input" v-model="modelDraft[p.id]"
                           placeholder="本地部署请填写模型名，如 llama3">
                  </template>

                  <div class="prov-fetchmsg" v-if="modelState[p.id] && modelState[p.id].message"
                       :class="modelState[p.id].fetched ? 'ok' : 'err'">
                    {{ modelState[p.id].message }}
                  </div>

                  <div class="prov-acts">
                    <button class="btn" @click="runTest(p.id)"
                            :disabled="testState[p.id] && testState[p.id].running">
                      {{ testState[p.id] && testState[p.id].running ? '测试中…' : '连接测试' }}
                    </button>
                    <button class="btn primary" @click="useProvider(p.id)"
                            :disabled="currentProvider === p.id && !modelDraft[p.id]">
                      {{ currentProvider === p.id ? '应用模型' : '切换到此供应商' }}
                    </button>
                  </div>

                  <!-- 测试结果留在卡片上：用户要照着错误信息改地址或换 key，
                       飘两秒就没的 toast 等于没说 -->
                  <div class="prov-result" v-if="testState[p.id] && !testState[p.id].running
                                                  && testState[p.id].ok !== null"
                       :class="testState[p.id].ok ? 'ok' : 'err'">
                    <span>{{ testState[p.id].ok ? '✓' : '✗' }}</span>
                    {{ testState[p.id].message }}
                  </div>
                </div>
              </div>
            </div>

            <!-- 采样参数跟供应商走，放同一组 -->
            <div class="set-group-title" style="margin-top:22px">采样</div>
            <div v-for="p in activeGroupParams" :key="p.key" class="set-field">
              <div class="set-field-top">
                <span class="name">{{ p.label }}</span>
                <span class="mark" v-if="dirty(p.key)">未保存</span>
                <span class="spacer"></span>
                <button class="reset" v-if="!p.is_default || dirty(p.key)"
                        @click="resetField(p)">{{ t.resetDefault }}</button>
              </div>
              <input class="set-input"
                     :type="p.type === 'number' ? 'number' : 'text'"
                     :value="editValue(p)" @input="onEdit(p, $event.target.value)">
              <div class="set-hint">{{ p.hint }}</div>
            </div>
          </template>

          <!-- 外观（前端本地，不走后端） -->
          <template v-else-if="activeGroup === 'appearance'">
            <div class="set-group-title">{{ t.appearance }}</div>
            <div class="set-field">
              <div class="set-field-top"><span class="name">{{ t.theme }}</span></div>
              <div class="seg">
                <button :class="{on: theme === 'dark'}"  @click="setTheme('dark')">{{ t.dark }}</button>
                <button :class="{on: theme === 'light'}" @click="setTheme('light')">{{ t.light }}</button>
              </div>
              <div class="set-hint" style="margin-top:8px">
                深色底压得低，罗盘的辉光和扫描弧才跳得出来
              </div>
            </div>
          </template>

          <!-- 布局 -->
          <template v-else-if="activeGroup === 'layout'">
            <div class="set-group-title">布局</div>

            <div class="set-field">
              <div class="set-field-top"><span class="name">产物栏</span></div>
              <div class="seg">
                <button :class="{on: railOpen}"  @click="!railOpen && toggleRail()">展开</button>
                <button :class="{on: !railOpen}" @click="railOpen && toggleRail()">收起</button>
              </div>
              <div class="set-hint" style="margin-top:8px">
                右侧的产物列表。收起后中栏会自动撑满
              </div>
            </div>

            <div class="set-field">
              <div class="set-field-top"><span class="name">会话栏</span></div>
              <div class="seg">
                <button :class="{on: !leftShut}" @click="leftShut = false">展开</button>
                <button :class="{on: leftShut}"  @click="leftShut = true">收起</button>
              </div>
              <div class="set-hint" style="margin-top:8px">
                左侧的会话与轨迹列表
              </div>
            </div>
          </template>

          <!-- 后端参数组（交互偏好 / 高级） -->
          <template v-else-if="activeGroup === 'prefs' || activeGroup === 'advanced'">
            <div class="set-group-title">{{ activeGroupDesc }}</div>
            <div class="set-hint" v-if="activeGroup === 'advanced'" style="margin:-6px 0 14px">
              这些参数会改变 Agent 的实际行为，改之前请先看每项的后果说明
            </div>

            <div v-for="p in activeGroupParams" :key="p.key" class="set-field">
              <div class="set-field-top">
                <span class="name">{{ p.label }}</span>
                <span class="mark" v-if="dirty(p.key)">未保存</span>
                <!-- 密码类的「值」是掩码，跟默认值比必然不等，
                     别据此报「已改」，也别给它「恢复默认」——那是清空 key -->
                <span class="mark" v-else-if="!p.is_default && p.type !== 'password'"
                      style="background:rgba(134,142,156,0.16);color:var(--fg-dim)">已改</span>
                <span class="spacer"></span>
                <button class="reset"
                        v-if="p.type !== 'password' && (!p.is_default || dirty(p.key))"
                        @click="resetField(p)">{{ t.resetDefault }}</button>
              </div>

              <!-- 高级项默认锁着，当前值照常可见 -->
              <div v-if="p.level === 'advanced' && !advanced" class="set-locked">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                  <rect x="3" y="11" width="18" height="11" rx="2"></rect>
                  <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
                </svg>
                {{ p.value }}
              </div>

              <input v-else class="set-input"
                     :type="p.type === 'password' ? 'password'
                            : (p.type === 'number' ? 'number' : 'text')"
                     :value="editValue(p)"
                     :placeholder="p.type === 'password' ? (p.value || '未设置') : ''"
                     @input="onEdit(p, $event.target.value)">

              <div class="set-hint">{{ p.hint }}</div>

              <div class="set-risk" v-if="p.risk && advanced">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                     stroke-linecap="round" stroke-linejoin="round">
                  <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                  <line x1="12" y1="9" x2="12" y2="13"></line>
                  <line x1="12" y1="17" x2="12.01" y2="17"></line>
                </svg>
                <span>{{ p.risk }}</span>
              </div>
            </div>
          </template>

          <!-- 数据 -->
          <template v-else-if="activeGroup === 'data'">
            <div class="set-group-title">数据</div>

            <div class="set-field">
              <div class="set-field-top"><span class="name">{{ t.exportFiles }}</span></div>
              <div class="set-hint">
                data/exports 与 data/reports 下的全部文件
                <span v-if="fileCount !== null"> · 共 <b>{{ fileCount }}</b> 个</span>
              </div>

              <div v-if="confirmKind === 'files'" class="confirm-inline">
                <span class="warn">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                       stroke-linecap="round" stroke-linejoin="round">
                    <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                    <line x1="12" y1="9" x2="12" y2="13"></line>
                    <line x1="12" y1="17" x2="12.01" y2="17"></line>
                  </svg>
                  <span>将永久删除 <b>{{ fileCount ?? '全部' }}</b> 个文件，不可撤销</span>
                </span>
                <button class="btn" @click="confirmKind = null">{{ t.cancel }}</button>
                <button class="btn danger" @click="doClearFiles">{{ t.confirmDelete }}</button>
              </div>

              <button v-else class="btn danger" style="margin-top:9px"
                      @click="confirmKind = 'files'">{{ t.clearAllFiles }}</button>
            </div>

            <div class="set-field">
              <div class="set-field-top"><span class="name">{{ t.historySessions }}</span></div>
              <div class="set-hint">
                logs/sessions 下的全部会话记录
                <span v-if="sessions.length"> · 共 <b>{{ sessions.length }}</b> 个</span>
              </div>

              <div v-if="confirmKind === 'sessions'" class="confirm-inline">
                <span class="warn">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                       stroke-linecap="round" stroke-linejoin="round">
                    <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"></path>
                    <line x1="12" y1="9" x2="12" y2="13"></line>
                    <line x1="12" y1="17" x2="12.01" y2="17"></line>
                  </svg>
                  <span>将永久删除 <b>{{ sessions.length }}</b> 个会话，含全部对话记录</span>
                </span>
                <button class="btn" @click="confirmKind = null">{{ t.cancel }}</button>
                <button class="btn danger" @click="doClearSessions">{{ t.confirmDelete }}</button>
              </div>

              <button v-else class="btn danger" style="margin-top:9px"
                      @click="confirmKind = 'sessions'">{{ t.deleteAllSessions }}</button>
            </div>

            <div class="set-hint" style="margin-top:18px">
              这两项都是不可撤销的。清空后文件与对话记录不会进回收站
              —— 回收站管的是数据库里的项目记录，不是这里。
            </div>
          </template>

          <!-- 关于 -->
          <template v-else>
            <div class="set-group-title">关于</div>

            <div class="set-field">
              <div class="set-field-top"><span class="name">DataPilot</span></div>
              <div class="set-hint">数据处理 Agent · {{ appVersion }}</div>
            </div>

            <div class="set-field">
              <div class="set-field-top"><span class="name">项目地址</span></div>
              <div class="set-hint">
                <a :href="REPO_URL" target="_blank" rel="noopener"
                   style="color:var(--acc-lift)">{{ REPO_URL }}</a>
              </div>
            </div>

            <div class="set-group-title" style="margin-top:22px">运行信息</div>
            <dl style="margin:0">
              <div class="info-row" v-for="(v, k) in settings.info" :key="k">
                <dt>{{ k }}</dt>
                <dd>{{ v === null ? '—' : v }}</dd>
              </div>
            </dl>
            <div class="set-hint" style="margin-top:14px">
              这些不是偏好设置。数据库路径改错会让 DuckDB 静默新建一个空库，
              看起来像数据全丢了——所以只给看不给改。
            </div>
          </template>

        </div>
      </div>
    </div>
  </div>
</div>
`,
};
