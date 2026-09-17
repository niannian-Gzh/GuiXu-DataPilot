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

          <!-- 外观（前端本地，不走后端） -->
          <template v-if="activeGroup === 'appearance'">
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

          <!-- 后端参数组 -->
          <template v-else-if="activeGroupParams.length">
            <div class="set-group-title">{{ activeGroupDesc }}</div>

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

          <!-- 只读信息 -->
          <template v-else-if="activeGroup === 'info'">
            <div class="set-group-title">{{ t.readonlyInfo }}</div>
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

          <!-- 维护 -->
          <template v-else>
            <div class="set-group-title">{{ t.maintain }}</div>

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

        </div>
      </div>
    </div>
  </div>
</div>
`,
};
