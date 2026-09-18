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
  <!-- 编辑页：盖住整个设置页的独立视图。
       不用弹窗是因为字段多，弹窗里滚动别扭；而且填地址时往往要回头
       看一眼列表里别的配置是怎么填的 -->
  <div v-if="editor" class="glass" style="flex:1;min-height:0;display:flex;flex-direction:column">
    <div class="set-head">
      <button class="icon-btn" @click="closeEditor" title="返回列表">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
             stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"></polyline>
        </svg>
      </button>
      <h2>{{ editor.id ? '编辑配置' : '添加新配置' }}</h2>
      <span class="spacer"></span>
      <button class="btn" @click="closeEditor">取消</button>
      <button class="btn primary" @click="saveConfig">保存</button>
    </div>

    <div class="set-body">
      <div class="set-form" style="flex:1">
        <div class="set-form-inner">

          <div class="cfg-row">
            <div class="cfg-col">
              <label class="prov-label">名称</label>
              <input class="set-input" v-model="editor.name" placeholder="例如：DeepSeek 生产">
            </div>
            <div class="cfg-col">
              <label class="prov-label">备注</label>
              <input class="set-input" v-model="editor.note" placeholder="可选">
            </div>
          </div>

          <label class="prov-label">供应商预设</label>
          <div class="preset-grid">
            <button v-for="p in providers" :key="p.id"
                    class="preset" :class="{on: editor.provider === p.id}"
                    @click="applyPreset(p)">{{ p.name }}</button>
          </div>
          <div class="set-hint" style="margin-top:6px">
            点一个会填上它的接口地址；地址仍可手改
          </div>

          <label class="prov-label">API Key</label>
          <input type="password" class="set-input" v-model="editor.key"
                 :placeholder="editor.has_key
                   ? '••••••••（已保存，留空表示不修改）'
                   : '粘贴 Key'">
          <div class="set-hint" style="margin-top:5px">
            存在 secrets.json（不进版本库），按配置分别保存
          </div>

          <label class="prov-label">请求地址</label>
          <input class="set-input" v-model="editor.base_url"
                 placeholder="https://your-api-endpoint.com">

          <label class="prov-label">
            模型
            <button class="prov-fetch" @click="fetchFormModels"
                    :disabled="formState.fetching">
              {{ formState.fetching ? '获取中…' : '获取模型' }}
            </button>
          </label>
          <!-- 用 datalist 而不是 select：拉回来的列表可能不全，
               用户得能自己填一个不在候选里的模型名 -->
          <input class="set-input" v-model="editor.model" list="cfg-models"
                 placeholder="模型名，本地部署请自己填">
          <datalist id="cfg-models">
            <option v-for="m in formModels" :key="m" :value="m"></option>
          </datalist>

          <div class="prov-fetchmsg" v-if="formState.fetch"
               :class="formState.fetch.ok ? 'ok' : 'err'">
            {{ formState.fetch.message }}
          </div>

          <div class="cfg-foot">
            <button class="btn" @click="testConfig(editor.id)" :disabled="!editor.id">
              连接测试
            </button>
            <span class="set-hint" v-if="!editor.id">保存后才能测试</span>
            <span class="prov-result" v-else-if="testState[editor.id] && !testState[editor.id].running"
                  :class="testState[editor.id].ok ? 'ok' : 'err'" style="margin:0">
              {{ testState[editor.id].message }}
            </span>
          </div>

        </div>
      </div>
    </div>
  </div>

  <div v-else class="glass" style="flex:1;min-height:0;display:flex;flex-direction:column">

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

          <!-- 模型：配置卡片列表 + 采样参数 -->
          <template v-if="activeGroup === 'model'">
            <div class="set-group-title">模型配置</div>

            <div v-if="!configs.length" class="set-hint" style="margin-bottom:14px">
              还没有配置。加一条才能开始对话。
            </div>

            <div v-for="c in configs" :key="c.id" class="cfg-card"
                 :class="{on: activeId === c.id}">
              <button class="cfg-main" @click="openEditConfig(c)">
                <div class="cfg-name">
                  {{ c.name }}
                  <span class="prov-tag" v-if="activeId === c.id">● 生效中</span>
                  <span class="prov-tag warn" v-if="!c.has_key">未配 Key</span>
                </div>
                <div class="cfg-model">{{ c.model || '（未填模型）' }}</div>
                <div class="cfg-url">{{ c.base_url }}</div>
                <div class="cfg-note" v-if="c.note">{{ c.note }}</div>
              </button>

              <div class="cfg-acts">
                <button class="btn" v-if="activeId !== c.id"
                        @click="activateConfig(c.id)">切换生效</button>
                <button class="btn" @click="testConfig(c.id)"
                        :disabled="testState[c.id] && testState[c.id].running">
                  {{ testState[c.id] && testState[c.id].running ? '测试中…' : '连接测试' }}
                </button>
                <button class="btn danger" @click="removeConfig(c.id)">
                  {{ pendingCfgDelete === c.id ? '确认删除？' : '删除' }}
                </button>
              </div>

              <div class="prov-result" v-if="testState[c.id] && !testState[c.id].running
                                              && testState[c.id].ok !== null"
                   :class="testState[c.id].ok ? 'ok' : 'err'">
                {{ testState[c.id].message }}
              </div>
            </div>

            <button class="cfg-add" @click="openNewConfig">＋ 添加新配置</button>

            <!-- 采样是应用级偏好，所有配置共享，所以不放进卡片 -->
            <div class="set-group-title" style="margin-top:22px">采样</div>
            <div class="set-hint" style="margin:-6px 0 14px">
              这几项对所有配置生效，不跟着卡片走
            </div>
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
