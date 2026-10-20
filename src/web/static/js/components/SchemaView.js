/* 数据库概览。作为 v-else-if 与主界面互斥，是独立整页。

   这里能改的只有「中文映射」两处：表的中文名、字段的中文含义。
   字段名、类型、必填都是从库里现读的事实，不归字典管，所以一律只读。

   草稿与原件分开存：original 是服务端给的，draft 是编辑中的。
   两者一比就知道改了哪几处，也就能在离开前拦住用户。 */
import * as api from '../api.js';

/* 生 SQL 类型名对用户没有意义。`character varying` 只有一个意思：文本。
   带长度的（varchar(50) / numeric(10,2)）先剥掉括号再查，
   剥掉的精度不补回来——用户要判断的是「这列是数还是字」，不是它留了几位 */
const TYPE_CN = {
  'character varying': '文本', 'varchar': '文本', 'character': '文本',
  'char': '文本', 'text': '文本',
  'integer': '整数', 'int': '整数', 'int2': '整数', 'int4': '整数', 'int8': '整数',
  'smallint': '整数', 'bigint': '整数', 'serial': '整数', 'bigserial': '整数',
  'numeric': '小数', 'decimal': '小数', 'real': '小数', 'double precision': '小数',
  'float': '小数', 'float4': '小数', 'float8': '小数',
  'boolean': '布尔', 'bool': '布尔',
  'date': '日期',
  'timestamp': '时间', 'timestamp without time zone': '时间',
  'timestamp with time zone': '时间', 'timestamptz': '时间', 'time': '时间',
  'json': 'JSON', 'jsonb': 'JSON', 'uuid': 'ID', 'blob': '二进制', 'bytea': '二进制',
};

function typeCn(t) {
  const raw = String(t || '').trim();
  const k = raw.toLowerCase();
  return TYPE_CN[k] || TYPE_CN[k.replace(/\(.*\)$/, '').trim()] || raw || '—';
}

export default {
  name: 'SchemaView',
  setup() {
    const store = Vue.inject('store');
    const t = store.t;
    const fmt = store.fmt;

    const original = Vue.ref([]);   // 服务端原样，不参与编辑
    const draft = Vue.ref([]);      // 编辑中的副本
    const openMap = Vue.ref({});    // 表的展开状态，按表名存
    const loadError = Vue.ref('');
    const saving = Vue.ref(false);
    const refreshing = Vue.ref(false);

    // 三个弹层：改一个字段 / 保存前确认 / 带走未保存改动
    const editing = Vue.ref(null);     // { tableName, fieldName, text, type, nullable }
    const confirming = Vue.ref(false);
    const leaving = Vue.ref(false);
    const textareaEl = Vue.ref(null);

    const clone = (tables) =>
      tables.map((x) => ({ ...x, fields: x.fields.map((f) => ({ ...f })) }));

    async function load() {
      const r = await api.getSchema();
      if (!r.ok) { loadError.value = r.message; return; }
      loadError.value = '';
      original.value = clone(r.tables || []);
      draft.value = clone(r.tables || []);

      // 表少就全展开；多了先折起来，否则一屏全是字段行，表与表之间
      // 完全看不出分界
      const expand = draft.value.length <= 4;
      const m = {};
      for (const x of draft.value) m[x.name] = expand;
      openMap.value = m;
    }

    /* 改了哪几处。表名算一处，每个改动的字段各算一处——
       计数和清单都从这一个来源出，不会两处对不上 */
    const changes = Vue.computed(() => {
      const out = [];
      for (const tb of draft.value) {
        const o = original.value.find((x) => x.name === tb.name);
        if (!o) continue;

        const items = [];
        if (tb.label !== o.label) {
          items.push({ kind: 'table', from: o.label, to: tb.label });
        }
        for (const f of tb.fields) {
          const of = o.fields.find((x) => x.name === f.name);
          if (of && f.label !== of.label) {
            items.push({ kind: 'field', name: f.name, from: of.label, to: f.label });
          }
        }
        if (items.length) out.push({ name: tb.name, label: tb.label, items });
      }
      return out;
    });

    const dirtyCount = Vue.computed(() =>
      changes.value.reduce((n, c) => n + c.items.length, 0));

    const closeEditor = () => { editing.value = null; };

    function openEditor(table, field) {
      editing.value = {
        tableName: table.name,
        tableLabel: table.label,
        fieldName: field.name,
        type: field.type,
        nullable: field.nullable,
        text: field.label,
      };
    }

    function confirmEditor() {
      const tb = draft.value.find((x) => x.name === editing.value.tableName);
      const f = tb && tb.fields.find((x) => x.name === editing.value.fieldName);
      if (f) f.label = editing.value.text;
      editing.value = null;
    }

    // 弹出即聚焦并把光标放到末尾：这个框十有八九是要接着改，
    // 不是要重打一遍
    Vue.watch(editing, async (v) => {
      if (!v) return;
      await Vue.nextTick();
      const el = textareaEl.value;
      if (el) { el.focus(); el.setSelectionRange(el.value.length, el.value.length); }
    });

    async function doSave() {
      if (!dirtyCount.value || saving.value) return;
      saving.value = true;
      try {
        // 逐表 PUT。后端是逐字段合并，所以只发改动的部分
        for (const c of changes.value) {
          const body = {};
          for (const i of c.items) {
            if (i.kind === 'table') {
              body.label = i.to;
            } else {
              if (!body.fields) body.fields = {};
              body.fields[i.name] = i.to;
            }
          }
          const r = await api.updateSchema(c.name, body);
          if (!r.ok) {
            store.notify('保存失败：' + r.message, false);
            return;                     // 停在确认框上，让用户能重试
          }
        }
        original.value = clone(draft.value);
        confirming.value = false;
        store.notify(t.saved);
      } finally {
        saving.value = false;
      }
    }

    async function doRefresh() {
      if (refreshing.value) return;
      refreshing.value = true;
      try {
        const r = await api.refreshSchema();
        if (!r.ok) { store.notify('刷新失败：' + r.message, false); return; }

        const c = r.changes || {};
        const parts = [];
        if (c.added_tables && c.added_tables.length) {
          parts.push(fmt(t.refreshAddedTables, { n: c.added_tables.length }));
        }
        if (c.added_fields && c.added_fields.length) {
          parts.push(fmt(t.refreshAddedFields, { n: c.added_fields.length }));
        }
        // 移除也要报。它是真删——连同那个字段上写好的中文含义一起没了
        if (c.removed_fields && c.removed_fields.length) {
          parts.push(fmt(t.refreshRemovedFields, { n: c.removed_fields.length }));
        }

        await load();
        store.notify(parts.length ? parts.join('，') : t.refreshNoChange);
      } finally {
        refreshing.value = false;
      }
    }

    /* ── 未保存就离开 ──────────────────────────────────────────
       左栏和顶栏是常驻的，所以「离开这一页」的入口在 shell 那边，
       不在这个组件里。由它注册一个拦截器（见 main.js 的 leaveGuard），
       shell 上每个会切走视图的动作都先过一遍这里。
       proceed 是那个动作本身，问过之后再执行它 */
    let pendingLeave = null;

    function tryLeave(proceed) {
      if (dirtyCount.value) { pendingLeave = proceed; leaving.value = true; }
      else proceed();
    }

    function leaveNow() {
      const p = pendingLeave;
      pendingLeave = null;
      leaving.value = false;
      // 先撤掉拦截，否则这次离开会被自己再拦一道
      store.leaveGuard.value = null;
      if (p) p();
    }

    // 未保存时不给刷新：刷新会整份重载，把编辑中的草稿冲掉
    Vue.onMounted(() => {
      load();
      store.leaveGuard.value = tryLeave;
    });
    Vue.onUnmounted(() => {
      store.leaveGuard.value = null;
      pendingLeave = null;
    });

    return {
      ...store, t, fmt, typeCn,
      original, draft, openMap, loadError, saving, refreshing,
      editing, confirming, leaving, textareaEl,
      changes, dirtyCount,
      openEditor, confirmEditor, closeEditor,
      doSave, doRefresh, leaveNow, load,
    };
  },
  template: `
<main class="stage">
  <div class="stage-head">
    <div class="stage-bar">
      <span class="stage-title">{{ t.schemaTitle }}</span>
      <div class="stage-meta">
        <span class="t-meta">{{ draft.length }} 张表</span>
        <span class="t-meta" v-if="dirtyCount">{{ fmt(t.unsavedCount, { n: dirtyCount }) }}</span>
      </div>
      <button class="btn" @click="doRefresh"
              :disabled="refreshing || dirtyCount"
              :title="dirtyCount ? '有未保存的修改，先保存或返回再刷新' : '扫库同步新表新字段'">
        {{ refreshing ? t.refreshing : t.refresh }}
      </button>
      <button class="btn solid" @click="confirming = true"
              :disabled="!dirtyCount || saving">
        {{ saving ? t.saving : t.save }}
      </button>
    </div>
  </div>

  <!-- 一张表 = 一个块。块头是「这张表是什么」，下面是它的全部字段。
       不做左右分栏：工作区本来就窄，而「数据字典」这个词的意思就是
       「把所有表的所有字段摊开」，摊开就够了 -->
  <div class="schema">
    <div v-if="loadError" class="empty-note">{{ loadError }}</div>

    <div v-for="tb in draft" :key="tb.name" class="tbl">
      <div class="tbl-head">
        <button class="tbl-fold" :class="{closed: !openMap[tb.name]}"
                @click="openMap[tb.name] = !openMap[tb.name]"
                :title="openMap[tb.name] ? '收起' : '展开'">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
               stroke-linecap="round" stroke-linejoin="round">
            <polyline points="6 9 12 15 18 9"></polyline>
          </svg>
        </button>

        <span class="tbl-nm">{{ tb.real_table }}</span>

        <!-- 表的中文名就地改。它短，为它开一个面板太重 -->
        <input class="tbl-cn" v-model="tb.label"
               :size="Math.max(4, (tb.label || '').length * 2)"
               :placeholder="t.unnamedTable">

        <span class="tbl-meta">
          {{ fmt(t.fieldsCount, { n: tb.fields.length }) }}
        </span>
      </div>

      <table v-show="openMap[tb.name]">
        <thead>
          <tr>
            <th>{{ t.fieldName }}</th>
            <th>{{ t.fieldType }}</th>
            <th>{{ t.fieldConstraint }}</th>
            <th>{{ t.fieldLabel }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="f in tb.fields" :key="f.name">
            <td>{{ f.name }}</td>
            <td class="num" :title="f.type">{{ typeCn(f.type) }}</td>
            <td>
              <span class="tag" :class="f.nullable ? 'opt' : 'req'">
                {{ f.nullable ? t.nullable : t.required }}
              </span>
            </td>
            <!-- 不就地放输入框：真实的「中文含义」是上百字的提示语
                 （比如「状态」那列的取值说明），一行 input 只看得到开头，
                 还会把表格撑得高低不齐。点开面板写 -->
            <td class="cnm" :class="{empty: !f.label}">
              <button class="cnm-btn" :title="f.label || t.unlabeled"
                      @click="openEditor(tb, f)">
                {{ f.label || t.unlabeled }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="!draft.length && !loadError" class="empty-note">
      这个数据源里还没有表
    </div>
  </div>

  <!-- 字段中文含义的编辑面板 -->
  <div v-if="editing" class="modal-mask" @click.self="closeEditor">
    <div class="modal" style="max-width:560px">
      <div class="modal-head">
        <span class="modal-title">{{ editing.fieldName }}</span>
        <span class="t-meta">
          {{ editing.tableLabel || editing.tableName }} · {{ editing.type }} ·
          {{ editing.nullable ? t.nullable : t.required }}
        </span>
        <button class="modal-x" @click="closeEditor" title="关闭">
          <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M3 3l6 6M9 3l-6 6"/>
          </svg>
        </button>
      </div>
      <div class="modal-body" style="padding:14px 16px">
        <textarea ref="textareaEl" class="cnm-area" v-model="editing.text"
                  :placeholder="t.unlabeled"></textarea>
        <div class="set-hint" style="margin-top:8px">{{ t.labelHint }}</div>
      </div>
      <div class="modal-foot">
        <button class="btn" @click="closeEditor">{{ t.cancel }}</button>
        <button class="btn solid" @click="confirmEditor">{{ t.ok }}</button>
      </div>
    </div>
  </div>

  <!-- 保存前把改动逐条摆出来。用的是确认卡那套 .diff-row，
       因为它说的就是同一件事：哪一项从什么变成了什么 -->
  <div v-if="confirming" class="modal-mask" @click.self="confirming = false">
    <div class="modal" style="max-width:560px">
      <div class="modal-head">
        <span class="modal-title">{{ t.confirmSaveTitle }}</span>
        <button class="modal-x" @click="confirming = false" title="关闭">
          <svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.6">
            <path d="M3 3l6 6M9 3l-6 6"/>
          </svg>
        </button>
      </div>
      <div class="modal-body" style="padding:14px 16px">
        <div v-for="c in changes" :key="c.name" style="margin-bottom:16px">
          <div class="set-h">{{ c.label || t.unnamedTable }}</div>
          <div v-for="(i, k) in c.items" :key="k" class="diff-row">
            <span class="diff-field">{{ i.kind === 'table' ? t.tableNameChange : i.name }}</span>
            <span class="diff-vals">
              <span class="diff-from">{{ i.from || '（空）' }}</span>
              <span class="diff-arrow">→</span>
              <span class="diff-to">{{ i.to || '（空）' }}</span>
            </span>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn" @click="confirming = false">{{ t.cancel }}</button>
        <button class="btn solid" @click="doSave" :disabled="saving">
          {{ saving ? t.saving : t.confirmSave }}
        </button>
      </div>
    </div>
  </div>

  <!-- 带着未保存的改动走 -->
  <div v-if="leaving" class="modal-mask" @click.self="leaving = false">
    <div class="modal" style="max-width:420px">
      <div class="modal-head">
        <span class="modal-title">{{ t.confirmLeaveTitle }}</span>
      </div>
      <div class="modal-body" style="padding:14px 16px">
        <div class="set-hint">{{ fmt(t.unsavedCount, { n: dirtyCount }) }}会丢掉</div>
      </div>
      <div class="modal-foot">
        <button class="btn" @click="leaving = false">{{ t.cancel }}</button>
        <button class="btn danger" @click="leaveNow">{{ t.confirmLeave }}</button>
      </div>
    </div>
  </div>
</main>
`,
};
