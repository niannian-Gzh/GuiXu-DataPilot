/* 恢复页：垃圾桶 + 版本历史。

   两件事本质上是同一件事的两面——都是"回到过去"：一个捞回删掉的行，
   一个把表退回某个时间点。所以放同一页，两个 tab。

   **这一页不经过模型。** 它是人在页面上直接翻、直接点，和对话是两条路；
   写操作在服务端复用对话里同一批执行端（审计、事务、回滚前的快照都在那儿）。 */
import * as api from '../api.js';
import { shortTime } from '../utils.js';

export default {
  name: 'RecoverView',
  setup() {
    const store = Vue.inject('store');
    const t = store.t;
    const fmt = store.fmt;

    const deleted = Vue.ref([]);
    const snaps = Vue.ref([]);
    const loadError = Vue.ref('');
    const openMap = Vue.ref({});   // 表组的展开状态
    const tab = Vue.ref('trash');
    const q = Vue.ref('');
    const busy = Vue.ref(false);
    const preview = Vue.ref(null);  // { columns, rows, total, shown, group, snapshot }
    const rolling = Vue.ref(null);  // 待确认的回滚

    async function load() {
      const [d, s] = await Promise.all([api.getDeletedRows(), api.getSnapshots()]);
      if (d == null || s == null) {
        loadError.value = t.recoverLoadFail;
        return;
      }
      loadError.value = '';
      deleted.value = d;
      snaps.value = s;
      // 默认全展开；用户已经收起来的保持收起，别在恢复一行之后又全弹开
      const open = { ...openMap.value };
      for (const g of [...d, ...s]) {
        if (open[g.name] === undefined) open[g.name] = true;
      }
      openMap.value = open;
    }
    Vue.onMounted(load);

    const switchTab = (name) => {
      tab.value = name;
      q.value = '';
    };

    const deletedCount = Vue.computed(() =>
      deleted.value.reduce((n, g) => n + g.count, 0));
    const snapCount = Vue.computed(() =>
      snaps.value.reduce((n, g) => n + g.snapshots.length, 0));

    const norm = (v) => String(v == null ? '' : v).toLowerCase();

    const filteredDeleted = Vue.computed(() => {
      const k = q.value.trim().toLowerCase();
      if (!k) return deleted.value;
      return deleted.value.map((g) => {
        if (norm(g.name).includes(k) || norm(g.label).includes(k)) return g;
        const rows = g.rows.filter((r) => r.some((c) => norm(c).includes(k)));
        return { ...g, rows, count: rows.length };
      }).filter((g) => g.count > 0);
    });

    const filteredSnaps = Vue.computed(() => {
      const k = q.value.trim().toLowerCase();
      if (!k) return snaps.value;
      return snaps.value.map((g) => {
        if (norm(g.name).includes(k) || norm(g.label).includes(k)) return g;
        const items = g.snapshots.filter((s) =>
          norm(s.at).includes(k) || norm(s.kind_label).includes(k)
          || norm(s.rows).includes(k));
        return { ...g, snapshots: items };
      }).filter((g) => g.snapshots.length > 0);
    });

    // 快照时间是 ISO（带 T），弹窗里给人看换成空格
    const fullTime = (s) => String(s || '').replace('T', ' ');

    const restoreRow = async (g, row) => {
      if (busy.value || g.pk_index == null) return;
      busy.value = true;
      try {
        const r = await api.restoreRows(g.name, [row[g.pk_index]]);
        if (!r.ok) {
          store.notify(r.error || r.message || t.recoverLoadFail, false);
          return;
        }
        store.notify(fmt(t.recoverRestored, { n: r.affected }));
        await load();
        store.loadOverview();
      } finally {
        busy.value = false;
      }
    };

    const openPreview = async (g, s) => {
      const p = await api.getSnapshotPreview(s.id);
      if (!p) {
        store.notify(t.recoverLoadFail, false);
        return;
      }
      preview.value = { ...p, group: g, snapshot: s };
    };

    // 预览里点回滚也走这里：先收起预览，再弹确认
    const askRollback = (g, s) => {
      preview.value = null;
      rolling.value = { ...s, table: g.name, gone: !g.exists };
    };

    const confirmRollback = async () => {
      if (!rolling.value || busy.value) return;
      busy.value = true;
      try {
        const r = await api.rollbackSnapshot(rolling.value.id);
        if (!r.ok) {
          store.notify(r.error || r.message || t.recoverLoadFail, false);
          return;
        }
        store.notify(fmt(t.recoverRolledBack, { at: fullTime(rolling.value.at) }));
        rolling.value = null;
        await load();
        store.loadOverview();
      } finally {
        busy.value = false;
      }
    };

    return {
      ...store, t, fmt, shortTime, fullTime,
      deleted, snaps, loadError, openMap, tab, q, busy, preview, rolling,
      deletedCount, snapCount, filteredDeleted, filteredSnaps,
      switchTab, restoreRow, openPreview, askRollback, confirmRollback,
    };
  },
  template: `
<main class="stage">

  <div class="stage-head">
    <div class="stage-bar">
      <!-- 返回对话的入口和数据字典页一致 -->
      <button class="rail-icon" @click="goChat" title="返回对话">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6">
          <path d="M10 3 5 8l5 5"/>
        </svg>
      </button>
      <span class="stage-title">{{ t.recoverTitle }}</span>
      <div class="stage-meta">
        <span class="t-meta">{{ fmt(t.recoverDeletedCount, { n: deletedCount }) }}</span>
        <span class="t-meta">{{ fmt(t.recoverSnapCount, { n: snapCount }) }}</span>
      </div>
    </div>

    <!-- 两个 tab 就是两种"回到过去"的方式 -->
    <div class="vtabs">
      <button :class="{on: tab === 'trash'}" @click="switchTab('trash')">
        {{ t.recoverTrash }}
      </button>
      <button :class="{on: tab === 'versions'}" @click="switchTab('versions')">
        {{ t.recoverVersions }}
      </button>
    </div>
  </div>

  <div class="recover">
    <div v-if="loadError" class="empty-note">{{ loadError }}</div>

    <div class="rec-search">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
           stroke-linecap="round" stroke-linejoin="round">
        <circle cx="11" cy="11" r="7"></circle>
        <path d="m20 20-3.5-3.5"></path>
      </svg>
      <input v-model="q"
             :placeholder="tab === 'trash' ? t.recoverSearchTrash : t.recoverSearchVersions">
    </div>

    <!-- ---------- 垃圾桶 ---------- -->
    <template v-if="tab === 'trash'">
      <div v-if="!filteredDeleted.length" class="empty-note">
        {{ q ? '没有匹配的记录' : t.recoverEmptyTrash }}
      </div>

      <div v-for="g in filteredDeleted" :key="'d' + g.name" class="tbl">
        <div class="tbl-head">
          <button class="tbl-fold" :class="{closed: !openMap[g.name]}"
                  @click="openMap[g.name] = !openMap[g.name]"
                  :title="openMap[g.name] ? '收起' : '展开'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
                 stroke-linecap="round" stroke-linejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </button>
          <span class="tbl-nm">{{ g.name }}</span>
          <span class="tbl-cn" v-if="g.label">{{ g.label }}</span>
          <span class="tbl-meta">{{ fmt(t.recoverDeletedCount, { n: g.count }) }}</span>
        </div>

        <div class="rec-scroll" v-show="openMap[g.name]">
          <table>
            <thead>
              <tr>
                <th v-for="col in g.columns" :key="col">{{ col }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(r, ri) in g.rows" :key="ri">
                <td v-for="(v, ci) in r" :key="ci"
                    :class="{urgent: ci === g.columns.length - 1 && v != null && v <= 2}">
                  {{ v ?? '—' }}
                </td>
                <td class="rec-act">
                  <button class="btn" :disabled="busy || g.pk_index == null"
                          :title="g.pk_index == null ? t.recoverNoPk : t.recoverRestore"
                          @click="restoreRow(g, r)">{{ t.recoverRestore }}</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </template>

    <!-- ---------- 版本历史 ---------- -->
    <template v-else>
      <div v-if="!filteredSnaps.length" class="empty-note">
        {{ q ? '没有匹配的快照' : t.recoverEmptyVersions }}
      </div>

      <div v-for="g in filteredSnaps" :key="'s' + g.name" class="tbl">
        <div class="tbl-head">
          <button class="tbl-fold" :class="{closed: !openMap[g.name]}"
                  @click="openMap[g.name] = !openMap[g.name]"
                  :title="openMap[g.name] ? '收起' : '展开'">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
                 stroke-linecap="round" stroke-linejoin="round">
              <polyline points="6 9 12 15 18 9"></polyline>
            </svg>
          </button>
          <span class="tbl-nm">{{ g.name }}</span>
          <span class="tbl-cn" v-if="g.label">{{ g.label }}</span>
          <!-- 快照留着、表已经删了：这张快照存在的意义就是把表变回来 -->
          <span class="rec-gone" v-if="!g.exists">{{ t.recoverTableGone }}</span>
          <span class="tbl-meta">{{ fmt(t.recoverSnapCount, { n: g.snapshots.length }) }}</span>
        </div>

        <div class="rec-snaps" v-show="openMap[g.name]">
          <div class="rec-snap" v-for="s in g.snapshots" :key="s.id">
            <span class="rec-at">{{ shortTime(s.at) }}</span>
            <span class="rec-kind">{{ s.kind_label }}</span>
            <span class="rec-rows">{{ fmt(t.recoverRowCount, { n: s.rows }) }}</span>
            <button class="btn" @click="openPreview(g, s)">{{ t.recoverPreview }}</button>
            <button class="btn danger" @click="askRollback(g, s)">{{ t.recoverRollback }}</button>
          </div>
        </div>
      </div>
    </template>
  </div>

  <!-- ---------- 快照预览 ---------- -->
  <div v-if="preview" class="modal-mask" @click.self="preview = null">
    <div class="modal">
      <div class="modal-head">
        <span class="modal-title">
          {{ t.recoverPreview }} · {{ preview.group.name }} · {{ preview.snapshot.kind_label }}
          · {{ fullTime(preview.snapshot.at) }}
        </span>
        <button class="modal-x" @click="preview = null">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
               stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>

      <div class="modal-body rec-preview">
        <table>
          <thead>
            <tr><th v-for="col in preview.columns" :key="col">{{ col }}</th></tr>
          </thead>
          <tbody>
            <tr v-for="(r, ri) in preview.rows" :key="ri">
              <td v-for="(v, ci) in r" :key="ci">{{ v ?? '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <div class="modal-foot">
        <span class="rec-shown" v-if="preview.shown < preview.total">
          {{ fmt(t.recoverShown, { n: preview.shown, total: preview.total }) }}
        </span>
        <button class="btn"
                @click="askRollback(preview.group, preview.snapshot)">{{ t.recoverRollback }}</button>
        <button class="btn solid" @click="preview = null">{{ t.recoverClose }}</button>
      </div>
    </div>
  </div>

  <!-- ---------- 回滚确认 ---------- -->
  <div v-if="rolling" class="modal-mask" @click.self="rolling = null">
    <div class="modal rec-modal-sm">
      <div class="modal-head">
        <span class="modal-title">{{ t.recoverRollbackTitle }}</span>
      </div>

      <div class="modal-body rec-confirm">
        <div class="rec-line">
          <span>{{ t.recoverFieldTable }}</span><b>{{ rolling.table }}</b>
        </div>
        <div class="rec-line">
          <span>{{ t.recoverFieldTime }}</span><b>{{ fullTime(rolling.at) }}</b>
        </div>
        <div class="rec-line">
          <span>{{ t.recoverFieldKind }}</span><b>{{ rolling.kind_label }}</b>
        </div>
        <div class="rec-line">
          <span>{{ t.recoverFieldRows }}</span><b>{{ rolling.rows }}</b>
        </div>
        <p class="rec-warn" v-if="rolling.gone">{{ t.recoverRebuild }}</p>
        <p class="rec-warn">{{ t.recoverRollbackWarn }}</p>
      </div>

      <div class="modal-foot">
        <button class="btn" @click="rolling = null" :disabled="busy">{{ t.cancel }}</button>
        <button class="btn danger" @click="confirmRollback" :disabled="busy">
          {{ t.recoverConfirmRollback }}
        </button>
      </div>
    </div>
  </div>
</main>
`,
};
