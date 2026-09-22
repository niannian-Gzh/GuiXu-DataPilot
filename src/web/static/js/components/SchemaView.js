/* 数据库概览。作为 v-else-if 与主界面互斥，是独立整页。

   这里能改的只有「中文映射」两处：表的中文名、字段的中文含义。
   字段名、类型、必填都是从库里现读的事实，不归字典管，所以一律只读。

   草稿与原件分开存：original 是服务端给的，draft 是编辑中的。
   两者一比就知道改了哪几处，也就能在离开前拦住用户。 */
import * as api from '../api.js';

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

    // 未保存时不给刷新：刷新会整份重载，把编辑中的草稿冲掉
    function tryLeave() {
      if (dirtyCount.value) { leaving.value = true; return; }
      store.goChat();
    }

    Vue.onMounted(load);

    return {
      ...store, t, fmt,
      original, draft, openMap, loadError, saving, refreshing,
      editing, confirming, leaving, textareaEl,
      changes, dirtyCount,
      openEditor, confirmEditor, closeEditor,
      doSave, doRefresh, tryLeave, load,
    };
  },
  template: `
<div class="settings-page">
  <div class="glass" style="flex:1;min-height:0;display:flex;flex-direction:column">

    <div class="set-head">
      <button class="icon-btn" @click="tryLeave" title="返回对话">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
             stroke-linecap="round" stroke-linejoin="round">
          <polyline points="15 18 9 12 15 6"></polyline>
        </svg>
      </button>
      <h2>{{ t.schemaTitle }}</h2>
      <span class="count" v-if="dirtyCount">{{ fmt(t.unsavedCount, { n: dirtyCount }) }}</span>
      <span class="spacer"></span>
      <button class="btn" @click="doRefresh"
              :disabled="refreshing || dirtyCount"
              :title="dirtyCount ? '有未保存的修改，先保存或返回再刷新' : '扫库同步新表新字段'">
        {{ refreshing ? t.refreshing : t.refresh }}
      </button>
      <button class="btn primary" @click="confirming = true"
              :disabled="!dirtyCount || saving">
        {{ saving ? t.saving : t.save }}
      </button>
    </div>

    <div class="sch-body">
      <div class="sch-inner">

        <div class="set-hint sch-desc">{{ t.schemaDesc }}</div>

        <div v-if="loadError" class="sch-error">{{ loadError }}</div>

        <div v-for="tb in draft" :key="tb.name" class="sch-card">

          <div class="sch-card-head">
            <button class="sch-fold" :class="{closed: !openMap[tb.name]}"
                    @click="openMap[tb.name] = !openMap[tb.name]"
                    :title="openMap[tb.name] ? '收起' : '展开'">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
                   stroke-linecap="round" stroke-linejoin="round">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </button>

            <input class="set-input sch-table-label" v-model="tb.label"
                   :placeholder="t.unnamedTable">

            <span class="sch-table-meta">
              {{ tb.real_table }} {{ fmt(t.fieldsCount, { n: tb.fields.length }) }}
            </span>
          </div>

          <div class="sch-fields" v-show="openMap[tb.name]">
            <div class="sch-row sch-row-head">
              <span>{{ t.fieldName }}</span>
              <span>{{ t.fieldType }}</span>
              <span>{{ t.fieldConstraint }}</span>
              <span>{{ t.fieldLabel }}</span>
            </div>

            <div v-for="f in tb.fields" :key="f.name" class="sch-row">
              <span class="sch-fname">{{ f.name }}</span>
              <span class="sch-ftype">{{ f.type }}</span>
              <span>
                <em v-if="!f.nullable" class="sch-tag req">{{ t.required }}</em>
                <em v-else class="sch-tag opt">{{ t.nullable }}</em>
              </span>
              <!-- 不在这里放输入框：真实的"中文含义"是上百字的提示语
                   （比如 status_raw 那条取值说明），一行 input 只看得到开头，
                   还会把表格撑得高低不齐。点开面板写 -->
              <button class="sch-fvalue" :class="{empty: !f.label}"
                      :title="f.label || t.unlabeled"
                      @click="openEditor(tb, f)">
                {{ f.label || t.unlabeled }}
              </button>
            </div>
          </div>

        </div>

        <div v-if="!draft.length && !loadError" class="empty-note">
          这个数据源里还没有表
        </div>

      </div>
    </div>
  </div>

  <!-- 字段中文含义的编辑面板 -->
  <div v-if="editing" class="sch-mask" @click.self="closeEditor">
    <div class="sch-modal glass">
      <div class="sch-modal-head">
        <span class="sch-modal-name">{{ editing.fieldName }}</span>
        <span class="sch-modal-meta">
          {{ editing.tableLabel || editing.tableName }} · {{ editing.type }} ·
          {{ editing.nullable ? t.nullable : t.required }}
        </span>
      </div>
      <textarea ref="textareaEl" class="sch-textarea" v-model="editing.text"
                :placeholder="t.unlabeled"></textarea>
      <div class="set-hint sch-modal-hint">{{ t.labelHint }}</div>
      <div class="sch-modal-foot">
        <button class="btn" @click="closeEditor">{{ t.cancel }}</button>
        <button class="btn primary" @click="confirmEditor">{{ t.ok }}</button>
      </div>
    </div>
  </div>

  <!-- 保存前把改动逐条摆出来 -->
  <div v-if="confirming" class="sch-mask" @click.self="confirming = false">
    <div class="sch-modal glass">
      <div class="sch-modal-title">{{ t.confirmSaveTitle }}</div>
      <div class="sch-changes">
        <div v-for="c in changes" :key="c.name" class="sch-change-group">
          <div class="sch-change-table">{{ c.label || t.unnamedTable }}</div>
          <div v-for="(i, k) in c.items" :key="k" class="sch-change-row">
            <span class="sch-change-key">{{ i.kind === 'table' ? t.tableNameChange : i.name }}</span>
            <span class="sch-change-from" :title="i.from">{{ i.from || '（空）' }}</span>
            <span class="sch-change-arrow">→</span>
            <span class="sch-change-to" :title="i.to">{{ i.to || '（空）' }}</span>
          </div>
        </div>
      </div>
      <div class="sch-modal-foot">
        <button class="btn" @click="confirming = false">{{ t.cancel }}</button>
        <button class="btn primary" @click="doSave" :disabled="saving">
          {{ saving ? t.saving : t.confirmSave }}
        </button>
      </div>
    </div>
  </div>

  <!-- 带着未保存的改动走 -->
  <div v-if="leaving" class="sch-mask" @click.self="leaving = false">
    <div class="sch-modal glass sch-modal-sm">
      <div class="sch-modal-title">{{ t.confirmLeaveTitle }}</div>
      <div class="set-hint">{{ fmt(t.unsavedCount, { n: dirtyCount }) }}会丢掉</div>
      <div class="sch-modal-foot">
        <button class="btn" @click="leaving = false">{{ t.cancel }}</button>
        <button class="btn danger" @click="goChat">{{ t.confirmLeave }}</button>
      </div>
    </div>
  </div>
</div>
`,
};
