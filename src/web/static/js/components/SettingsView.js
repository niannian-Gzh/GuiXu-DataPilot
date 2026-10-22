/* 设置页。和 ChatView、SchemaView 一样是工作区里的一个视图——
   顶栏和左栏留在原地，它只换中栏。

   结构照 docs/proto/workbench.html 的 v7：一条一条的 .set-row，
   左边是「这是什么 + 为什么」，右边是控件。原型那份里没有配置卡片，
   因为我们比它多一件事——同时存几套模型配置。卡片就按 .set-row
   的语言重画，不另起一套 */
import * as api from '../api.js';

export default {
  name: 'SettingsView',
  setup() {
    const store = Vue.inject('store');
    const t = store.t;
    const fmt = store.fmt;

    // 编辑页的连接测试。和卡片列表的 testState 分开：
    // 那边按配置 id 存结果，这边是"未保存的表单值"，没有 id
    const editorTest = Vue.ref({ running: false, ok: null, message: '' });
    const fadingTest = Vue.ref(false);     // 绿字是否正在消散
    let okTimer = null;                    // 两个计时器接力，共用这一个槽

    /* 手动检查更新。只有点按钮才发请求；启动流程不碰 GitHub。 */
    const updateState = Vue.ref({
      running: false, hasUpdate: false, url: '', message: '',
    });

    async function checkUpdate() {
      if (updateState.value.running) return;
      updateState.value = {
        running: true, hasUpdate: false, url: '', message: t.updateChecking,
      };
      const r = await api.checkUpdate();
      if (!r || !r.ok) {
        updateState.value = {
          running: false, hasUpdate: false, url: '',
          message: (r && r.message) || t.updateFailed,
        };
        return;
      }
      const latest = String(r.latest || '').replace(/^v/i, '');
      const current = String(r.current || '').replace(/^v/i, '');
      updateState.value = {
        running: false,
        hasUpdate: !!r.has_update,
        url: r.url || '',
        message: r.has_update
          ? fmt(t.updateFound, { v: 'v' + latest })
          : fmt(t.updateLatest, { v: 'v' + current }),
      };
    }

    function clearEditorTest() {
      if (okTimer) { clearTimeout(okTimer); okTimer = null; }
      fadingTest.value = false;
      if (editorTest.value.message || editorTest.value.running) {
        editorTest.value = { running: false, ok: null, message: '' };
      }
    }

    async function testEditor() {
      const e = store.editor.value;
      if (!e) return;
      if (okTimer) { clearTimeout(okTimer); okTimer = null; }
      editorTest.value = { running: true, ok: null, message: '' };
      try {
        const res = await fetch('/settings/test', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            base_url: e.base_url,
            model: e.model,
            key: e.key || null,
            provider: e.provider,
          }),
        });
        const data = await res.json();
        editorTest.value = { running: false, ok: !!data.ok, message: data.message || '' };
        // 成功则 4.5 秒后消散，0.55 秒动画结束后再清数据——总约 5 秒。
        // 失败保留：用户要照着错误信息改地址或换 key
        if (data.ok) {
          okTimer = setTimeout(() => {
            okTimer = null;
            fadingTest.value = true;
            okTimer = setTimeout(() => {
              editorTest.value = { running: false, ok: null, message: '' };
              fadingTest.value = false;
              okTimer = null;
            }, 560);
          }, 4500);
        }
      } catch (err) {
        editorTest.value = { running: false, ok: false, message: String(err) };
      }
    }

    // 表单任意关键字段一改，上一次的测试结果就失效
    Vue.watch(
      () => {
        const e = store.editor.value;
        if (!e) return null;
        return [e.base_url, e.key, e.model];
      },
      () => clearEditorTest()
    );

    // 关闭编辑页时也清一次
    Vue.watch(
      () => store.editor.value,
      (v) => { if (!v) clearEditorTest(); }
    );

    /* 供应商改成下拉之后，change 事件给的是 id 字符串，
       而 applyPreset 要的是整条预设。在这里补一步。 */
    const onPresetChange = (id) => {
      const p = store.providers.value.find((x) => x.id === id);
      if (p) store.applyPreset(p);
    };

    return {
      ...store, t, fmt,
      editorTest, testEditor, fadingTest, onPresetChange,
      updateState, checkUpdate,
    };
  },
  template: `
<main class="stage">

  <!-- ===================== 编辑一条配置 =====================
       它盖住的是【工作区】，不是整个应用：左栏还亮着，
       「有哪些会话」这一层没被动过 -->
  <template v-if="editor">
    <div class="stage-head">
      <div class="stage-bar">
        <button class="rail-icon" @click="closeEditor" title="返回设置">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M10 3 5 8l5 5"/>
          </svg>
        </button>
        <span class="stage-title">{{ editor.id ? '编辑配置' : '添加新配置' }}</span>
        <div class="stage-meta">
          <span class="t-meta" v-if="editor.has_key">已有密钥</span>
        </div>
        <button class="btn" @click="closeEditor">取消</button>
        <button class="btn solid" @click="saveConfig">保存</button>
      </div>
    </div>

    <div class="settings">

      <section class="set-group">
        <h3 class="set-h">这条配置</h3>

        <div class="set-row">
          <div class="set-l">
            <div class="set-label">名称</div>
            <div class="set-hint">只出现在这个界面上，用来区分几套配置</div>
          </div>
          <div class="set-f">
            <div class="set-input">
              <input v-model="editor.name" placeholder="例如：DeepSeek 生产">
            </div>
          </div>
        </div>

        <div class="set-row">
          <div class="set-l">
            <div class="set-label">备注</div>
            <div class="set-hint">可选。比如「每月额度用完就切这条」</div>
          </div>
          <div class="set-f">
            <div class="set-input">
              <input v-model="editor.note" placeholder="可选">
            </div>
          </div>
        </div>
      </section>

      <section class="set-group">
        <h3 class="set-h">接入</h3>

        <div class="set-row">
          <div class="set-l">
            <div class="set-label">供应商</div>
            <div class="set-hint">选一个会填上它的接口地址；地址仍然可以手改</div>
          </div>
          <div class="set-f">
            <div class="set-input">
              <select :value="editor.provider"
                      @change="onPresetChange($event.target.value)">
                <option v-for="p in providers" :key="p.id" :value="p.id">{{ p.name }}</option>
              </select>
              <svg class="chev" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5">
                <path d="M2.5 4.5 6 8l3.5-3.5"/>
              </svg>
            </div>
          </div>
        </div>

        <div class="set-row">
          <div class="set-l">
            <div class="set-label">接口地址</div>
            <div class="set-hint">OpenAI 兼容接口的根地址，不带 /chat/completions</div>
          </div>
          <div class="set-f">
            <div class="set-input">
              <input v-model="editor.base_url" placeholder="https://your-api-endpoint.com">
            </div>
          </div>
        </div>

        <div class="set-row">
          <div class="set-l">
            <div class="set-label">API 密钥</div>
            <div class="set-hint">
              存在 secrets.json，不进版本库。这是本项目唯一的外传凭据——
              数据源在本地
            </div>
          </div>
          <div class="set-f">
            <div class="set-input">
              <input type="password" v-model="editor.key"
                     :placeholder="editor.has_key ? '••••••••（留空表示不修改）' : '粘贴 Key'">
            </div>
          </div>
        </div>

        <div class="set-row">
          <div class="set-l">
            <div class="set-label">模型</div>
            <div class="set-hint">
              先从上游拉一份，点一下就填上；本地部署就直接手填
            </div>
            <div class="model-chips" v-if="formModels.length">
              <button v-for="m in formModels" :key="m"
                      class="model-chip" :class="{on: editor.model === m}"
                      @click="editor.model = m">{{ m }}</button>
            </div>
            <div class="prov-result" v-if="formState.fetch"
                 :class="formState.fetch.ok ? 'ok' : 'err'">
              {{ formState.fetch.message }}
            </div>
          </div>
          <div class="set-f col">
            <button class="btn" @click="fetchFormModels" :disabled="formState.fetching">
              {{ formState.fetching ? '获取中…' : '获取模型' }}
            </button>
            <div class="set-input">
              <input v-model="editor.model" placeholder="模型名">
            </div>
          </div>
        </div>

        <div class="set-row">
          <div class="set-l">
            <div class="set-label">连接状态</div>
            <!-- 测过就把结果留在这儿。错误信息往往很长，用户要照着它改 -->
            <div class="set-hint" v-if="editorTest.message">
              <span class="prov-result" :class="[editorTest.ok ? 'ok' : 'err',
                                                 {vanish: fadingTest}]">
                {{ editorTest.message }}
              </span>
            </div>
            <div class="set-hint" v-else>
              还没测过。保存前测一下，能省掉一次「用起来才发现 key 不对」
            </div>
          </div>
          <div class="set-f">
            <button class="btn" @click="testEditor" :disabled="editorTest.running">
              {{ editorTest.running ? '测试中…' : '测试连接' }}
            </button>
          </div>
        </div>
      </section>

    </div>
  </template>

  <!-- ===================== 设置列表 ===================== -->
  <template v-else>
    <div class="stage-head">
      <div class="stage-bar">
        <!-- 顶栏没了，返回对话的入口挪到这儿 -->
        <button class="rail-icon" @click="goChat" title="返回对话">
          <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M10 3 5 8l5 5"/>
          </svg>
        </button>
        <span class="stage-title">{{ t.settings }}</span>
        <div class="stage-meta">
          <span class="t-meta" v-if="dirtyCount">{{ dirtyCount }} 项未保存</span>
          <span class="t-meta" v-else-if="saveMsg" :style="{color: saveMsg.ok ? 'var(--ok)' : 'var(--err)'}">
            {{ saveMsg.text }}
          </span>
        </div>
        <button class="btn" v-if="dirtyCount" @click="discardDraft">{{ t.discardChanges }}</button>
        <button class="btn solid" @click="saveSettings" :disabled="!dirtyCount || saving">
          {{ saving ? '保存中…' : '保存' }}
        </button>
      </div>

      <!-- 分组导航做成一排小胶囊，和「对话 / 轨迹」同一套动作——
         它也是「看这一面的哪一块」，只是层级更浅 -->
      <div class="vtabs">
        <button v-for="g in allGroups" :key="g.id"
                :class="{on: activeGroup === g.id}" @click="activeGroup = g.id">
          {{ g.name }}<span class="n" v-if="groupDirty(g.id)">{{ groupDirty(g.id) }}</span>
        </button>
        <span style="flex:1"></span>
        <button class="t-adv" :class="{on: advanced}" @click="advanced = !advanced">
          {{ advanced ? '开发者模式已开' : '开发者模式' }}
        </button>
      </div>
    </div>

    <div class="settings">

      <!-- ---------- 模型 ---------- -->
      <template v-if="activeGroup === 'model'">
        <section class="set-group">
          <h3 class="set-h">模型配置</h3>

          <div class="set-row" v-if="!configs.length">
            <div class="set-l">
              <div class="set-hint">还没有配置。加一条才能开始对话。</div>
            </div>
          </div>

          <div v-for="c in configs" :key="c.id" class="set-row">
            <div class="set-l">
              <div class="set-label">
                {{ c.name }}
                <span class="tag ok" v-if="activeId === c.id">生效中</span>
                <span class="tag wait" v-if="!c.has_key">未配密钥</span>
              </div>
              <div class="set-hint">
                <span class="mono">{{ c.model || '（未填模型）' }}</span>
                · <span class="mono">{{ c.base_url }}</span>
                <template v-if="c.note"><br>{{ c.note }}</template>
              </div>

              <div class="prov-result" v-if="testState[c.id] && !testState[c.id].running
                                            && testState[c.id].ok !== null"
                   :class="[testState[c.id].ok ? 'ok' : 'err', {vanish: fadingIds[c.id]}]">
                {{ testState[c.id].message }}
              </div>
            </div>

            <div class="set-f wrap">
              <button class="btn" @click="openEditConfig(c)">编辑</button>
              <button class="btn" v-if="activeId !== c.id"
                      @click="activateConfig(c.id)">切换生效</button>
              <button class="btn" @click="testConfig(c.id)"
                      :disabled="testState[c.id] && testState[c.id].running">
                {{ testState[c.id] && testState[c.id].running ? '测试中…' : '测试连接' }}
              </button>
              <button class="btn danger" @click="removeConfig(c.id)">
                {{ pendingCfgDelete === c.id ? '确认删除？' : '删除' }}
              </button>
            </div>
          </div>

          <button class="btn" @click="openNewConfig"
                  style="width:auto;padding:9px 18px;margin-top:14px">
            <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M8 3v10M3 8h10"/>
            </svg>
            添加新配置
          </button>
        </section>

        <!-- 采样是应用级偏好，所有配置共享，所以不放进卡片 -->
        <section class="set-group">
          <h3 class="set-h">采样</h3>

          <div class="set-row" v-for="p in activeGroupParams" :key="p.key">
            <div class="set-l">
              <div class="set-label">
                {{ p.label }}
                <span class="tag wait" v-if="dirty(p.key)">未保存</span>
              </div>
              <div class="set-hint">{{ p.hint }}</div>
            </div>
            <div class="set-f">
              <div class="set-input" style="width:180px">
                <input :type="p.type === 'number' ? 'number' : 'text'"
                       :value="editValue(p)" @input="onEdit(p, $event.target.value)">
                <button class="reset" v-if="!p.is_default || dirty(p.key)"
                        @click="resetField(p)" :title="t.resetDefault">恢复默认</button>
              </div>
            </div>
          </div>
        </section>
      </template>

      <!-- ---------- 布局 ---------- -->
      <section class="set-group" v-else-if="activeGroup === 'layout'">
        <h3 class="set-h">布局</h3>

        <div class="set-row">
          <div class="set-l">
            <div class="set-label">产物栏</div>
            <div class="set-hint">工作区右侧的产物列表。收起后中栏会自动撑满</div>
          </div>
          <div class="set-f">
            <div class="seg">
              <button :class="{on: railOpen}"  @click="!railOpen && toggleRail()">展开</button>
              <button :class="{on: !railOpen}" @click="railOpen && toggleRail()">收起</button>
            </div>
          </div>
        </div>

        <div class="set-row">
          <div class="set-l">
            <div class="set-label">会话栏</div>
            <div class="set-hint">左侧的资产读数与会话列表</div>
          </div>
          <div class="set-f">
            <div class="seg">
              <button :class="{on: !leftShut}" @click="leftShut = false">展开</button>
              <button :class="{on: leftShut}"  @click="leftShut = true">收起</button>
            </div>
          </div>
        </div>
      </section>

      <!-- ---------- 参数表驱动的几组 ---------- -->
      <section class="set-group"
               v-else-if="['display','keep','upload','developer'].includes(activeGroup)">
        <h3 class="set-h">{{ activeGroupDesc }}</h3>

        <div class="set-row" v-for="p in activeGroupParams" :key="p.key">
          <div class="set-l">
            <div class="set-label">
              {{ p.label }}
              <span class="tag wait" v-if="dirty(p.key)">未保存</span>
              <!-- 密码类的「值」是掩码，跟默认值比必然不等，
                   别据此报「已改」，也别给它「恢复默认」——那是清空 key -->
              <span class="tag" v-else-if="!p.is_default && p.type !== 'password'">已改</span>
            </div>
            <div class="set-hint">{{ p.hint }}</div>

            <div class="set-risk" v-if="p.risk">
              <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
                <path d="M8 1.8 1.5 13h13L8 1.8Z"/>
                <path d="M8 6v3M8 11.4h.01"/>
              </svg>
              <span>{{ p.risk }}</span>
            </div>
          </div>

          <div class="set-f">
            <div class="set-input"
                 :style="{width: (p.min != null || p.max != null) ? '230px' : '270px'}">
              <!-- 取值是封闭集合的参数用下拉，别让用户手打——
                   拼错一个值不报错，只是被静默忽略 -->
              <select v-if="p.type === 'select'"
                      :value="editValue(p)"
                      @change="onEdit(p, $event.target.value)">
                <option v-for="o in p.options" :key="o.value" :value="o.value">
                  {{ o.label }}
                </option>
              </select>
              <input v-else
                     :type="p.type === 'password' ? 'password'
                            : (p.type === 'number' ? 'number' : 'text')"
                     :value="editValue(p)"
                     :placeholder="p.type === 'password' ? (p.value || '未设置') : ''"
                     @input="onEdit(p, $event.target.value)">
              <!-- 范围写在框里，不写在说明里 —— 它是这个框的约束，属于框本身。
                   只给一个边界时另一边留空，别编一个出来 -->
              <span class="set-range"
                    v-if="p.type === 'number' && (p.min != null || p.max != null)">
                {{ p.min != null ? p.min : '' }} – {{ p.max != null ? p.max : '' }}
              </span>
              <button class="reset" v-if="p.type !== 'password' && (!p.is_default || dirty(p.key))"
                      @click="resetField(p)" :title="t.resetDefault">恢复默认</button>
            </div>
          </div>
        </div>
      </section>

      <!-- ---------- 数据 ---------- -->

      <!-- ---------- 关于 ---------- -->
      <template v-else>
        <section class="set-group">
          <h3 class="set-h">关于</h3>

          <div class="set-row">
            <div class="set-l">
              <div class="set-label">归墟 · GUIXU</div>
              <div class="set-hint">数据处理 Agent · {{ appVersion }}</div>
            </div>
            <div class="set-f">
              <a class="btn" :href="REPO_URL" target="_blank" rel="noopener">项目地址</a>
            </div>
          </div>

          <div class="set-row">
            <div class="set-l">
              <div class="set-label">{{ t.updateTitle }}</div>
              <div class="set-hint">
                {{ t.updateHint }}
                <template v-if="updateState.message"> · {{ updateState.message }}</template>
              </div>
            </div>
            <div class="set-f wrap">
              <a v-if="updateState.hasUpdate && updateState.url"
                 class="btn solid" :href="updateState.url" target="_blank" rel="noopener">
                {{ t.updateOpen }}
              </a>
              <button class="btn" :disabled="updateState.running" @click="checkUpdate">
                {{ updateState.running ? t.updateChecking : t.updateCheck }}
              </button>
            </div>
          </div>
        </section>

        <section class="set-group">
          <h3 class="set-h">运行信息</h3>

          <div class="set-row" v-for="(v, k) in settings.info" :key="k">
            <div class="set-l">
              <div class="set-label">{{ k }}</div>
            </div>
            <div class="set-f wide">
              <div class="set-input readonly">
                <input :value="v === null ? '—' : v" readonly>
              </div>
            </div>
          </div>

          <div class="set-row">
            <div class="set-l">
              <div class="set-hint">
                这些不是偏好设置。数据库路径指向一个文件，
                改了等于换一个库——所以只给看不给改
              </div>
            </div>
          </div>
        </section>
      </template>

      <!-- 数据保留：保留期参数在上面渲染，这里接手「手动清空」。
           它不在 v-else-if 链里——keep 组已经被参数区接住了 -->
      <section class="set-group" v-if="activeGroup === 'keep'">
        <h3 class="set-h">手动清理</h3>

        <div class="set-row">
          <div class="set-l">
            <div class="set-label">{{ t.exportFiles }}</div>
            <div class="set-hint">
              data/exports 与 data/reports 下的全部文件
              <span v-if="fileCount !== null"> · 共 <b>{{ fileCount }}</b> 个</span>
            </div>
          </div>
          <div class="set-f wrap" v-if="confirmKind !== 'files'">
            <button class="btn danger" @click="confirmKind = 'files'">{{ t.clearAllFiles }}</button>
          </div>
        </div>

        <div class="set-row" v-if="confirmKind === 'files'">
          <div class="set-l">
            <div class="confirm-inline">
              <span class="warn">
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
                  <path d="M8 1.8 1.5 13h13L8 1.8Z"/>
                  <path d="M8 6v3M8 11.4h.01"/>
                </svg>
                将永久删除 <b>{{ fileCount ?? '全部' }}</b> 个文件，不可撤销
              </span>
              <button class="btn" @click="confirmKind = null">{{ t.cancel }}</button>
              <button class="btn danger" @click="doClearFiles">{{ t.confirmDelete }}</button>
            </div>
          </div>
        </div>

        <div class="set-row">
          <div class="set-l">
            <div class="set-label">{{ t.historySessions }}</div>
            <div class="set-hint">
              logs/sessions 下的全部会话记录
              <span v-if="sessions.length"> · 共 <b>{{ sessions.length }}</b> 个</span>
            </div>
          </div>
          <div class="set-f wrap" v-if="confirmKind !== 'sessions'">
            <button class="btn danger" @click="confirmKind = 'sessions'">{{ t.deleteAllSessions }}</button>
          </div>
        </div>

        <div class="set-row" v-if="confirmKind === 'sessions'">
          <div class="set-l">
            <div class="confirm-inline">
              <span class="warn">
                <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.4">
                  <path d="M8 1.8 1.5 13h13L8 1.8Z"/>
                  <path d="M8 6v3M8 11.4h.01"/>
                </svg>
                将永久删除 <b>{{ sessions.length }}</b> 个会话，含全部对话记录
              </span>
              <button class="btn" @click="confirmKind = null">{{ t.cancel }}</button>
              <button class="btn danger" @click="doClearSessions">{{ t.confirmDelete }}</button>
            </div>
          </div>
        </div>

        <div class="set-row">
          <div class="set-l">
            <div class="set-hint">
              上面两项都不可撤销，清空后不进回收站
              —— 回收站管的是数据库里的记录，不是这里。
            </div>
          </div>
        </div>
      </section>

    </div>
  </template>
</main>
`,
};
