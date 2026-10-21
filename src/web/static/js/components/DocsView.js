/* 文档库页：文档、回收站、上传、删除、恢复、重建索引、检索测试、原文预览。

   **这一页不经过模型。** 和恢复页一样，是人在页面上直接翻、直接点；
   模型那边只有 `search_documents` 一个动作，走的是同一个 service.search。

   删除是软删：进回收站，保留期内可恢复；检索和列表立即过滤掉。
   保留期到了由启动清理物理删除（切片 + 原文件）。 */
import * as api from '../api.js';
import { shortTime } from '../utils.js';

const SIZE_UNITS = ['B', 'KB', 'MB', 'GB'];

function sizeText(n) {
  let v = Number(n) || 0;
  let i = 0;
  while (v >= 1024 && i < SIZE_UNITS.length - 1) {
    v /= 1024;
    i += 1;
  }
  return (i === 0 ? v : v.toFixed(1)) + ' ' + SIZE_UNITS[i];
}

const KIND_LABEL = { pdf: 'PDF', docx: 'Word', text: '文本' };

export default {
  name: 'DocsView',
  setup() {
    const store = Vue.inject('store');
    const t = store.t;
    const fmt = store.fmt;

    const docs = Vue.ref([]);
    const deleted = Vue.ref([]);
    const counts = Vue.ref({ docs: 0, chunks: 0, deleted: 0 });
    const loadError = Vue.ref('');
    const uploading = Vue.ref(false);
    const busy = Vue.ref(false);
    const dragging = Vue.ref(false);
    const fileInput = Vue.ref(null);
    const tab = Vue.ref('library');

    const q = Vue.ref('');
    const results = Vue.ref([]);
    const searched = Vue.ref(false);
    const searching = Vue.ref(false);

    const pendingDelete = Vue.ref(null);
    const preview = Vue.ref(null);

    async function load() {
      const data = await api.getDocuments();
      if (data == null) {
        loadError.value = t.docsLoadFail;
        return;
      }
      loadError.value = '';
      docs.value = data.documents || [];
      deleted.value = data.deleted || [];
      counts.value = data.counts || { docs: 0, chunks: 0, deleted: 0 };
    }
    Vue.onMounted(load);

    const triggerUpload = () => fileInput.value && fileInput.value.click();

    async function upload(file) {
      if (!file || uploading.value) return;
      uploading.value = true;
      try {
        const data = await api.uploadDocument(file);
        store.notify(fmt(t.docsUploaded, { name: data.name, n: data.chunks }));
        await load();
        store.loadOverview();          // 左栏「N 份 · M 块」跟着变
      } catch (e) {
        store.notify(e.message || t.docsLoadFail, false);
      } finally {
        uploading.value = false;
      }
    }

    const onSelect = async (e) => {
      const file = e.target.files && e.target.files[0];
      e.target.value = '';             // 同一个文件连选两次也要能触发
      await upload(file);
    };

    const onDrop = async (e) => {
      dragging.value = false;
      const file = e.dataTransfer && e.dataTransfer.files[0];
      await upload(file);
    };

    async function rebuild() {
      if (busy.value) return;
      busy.value = true;
      try {
        const r = await api.rebuildDocuments();
        if (!r.ok) {
          store.notify(r.message || t.docsLoadFail, false);
          return;
        }
        store.notify(fmt(t.docsRebuilt, { n: r.chunks, ms: r.ms }));
      } finally {
        busy.value = false;
      }
    }

    async function confirmDelete() {
      if (!pendingDelete.value || busy.value) return;
      busy.value = true;
      try {
        const r = await api.deleteDocument(pendingDelete.value.id);
        if (!r.ok) {
          store.notify(r.message || t.docsLoadFail, false);
          return;
        }
        const name = pendingDelete.value.name;
        pendingDelete.value = null;
        store.notify(fmt(t.docsDeleted, { name }));
        await load();
        store.loadOverview();
      } finally {
        busy.value = false;
      }
    }

    async function restore(d) {
      if (busy.value) return;
      busy.value = true;
      try {
        const r = await api.restoreDocument(d.id);
        if (!r.ok) {
          store.notify(r.message || t.docsLoadFail, false);
          return;
        }
        store.notify(fmt(t.docsRestored, { name: d.name }));
        await load();
        store.loadOverview();
      } finally {
        busy.value = false;
      }
    }

    async function openPreview(d) {
      const data = await api.getDocument(d.id);
      if (!data || !data.ok) {
        store.notify(t.docsLoadFail, false);
        return;
      }
      preview.value = data;
    }

    async function search() {
      const query = q.value.trim();
      if (!query || searching.value) return;
      searching.value = true;
      try {
        const r = await api.searchDocuments(query);
        if (!r.ok) {
          store.notify(r.message || t.docsLoadFail, false);
          return;
        }
        results.value = r.results || [];
        searched.value = true;
      } finally {
        searching.value = false;
      }
    }

    const isMarkdown = (name) => String(name || '').toLowerCase().endsWith('.md');

    return {
      ...store, t, fmt, shortTime, sizeText, KIND_LABEL, isMarkdown,
      docs, deleted, counts, loadError, uploading, busy, dragging, fileInput,
      tab, q, results, searched, searching, pendingDelete, preview,
      triggerUpload, onSelect, onDrop, rebuild, confirmDelete, restore,
      openPreview, search,
    };
  },
  template: `
<main class="stage">

  <div class="stage-head">
    <div class="stage-bar">
      <button class="rail-icon" @click="goChat" title="返回对话">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6">
          <path d="M10 3 5 8l5 5"/>
        </svg>
      </button>
      <span class="stage-title">{{ t.docsTitle }}</span>
      <div class="stage-meta">
        <span class="t-meta">{{ fmt(t.docsCount, { n: counts.docs, m: counts.chunks }) }}</span>
        <span class="t-meta" v-if="counts.deleted">
          {{ fmt(t.docsTrashCount, { n: counts.deleted }) }}
        </span>
      </div>
    </div>

    <div class="vtabs">
      <button :class="{on: tab === 'library'}" @click="tab = 'library'">
        {{ t.docsTabLibrary }}
      </button>
      <button :class="{on: tab === 'trash'}" @click="tab = 'trash'">
        {{ t.docsTabTrash }}
      </button>
    </div>
  </div>

  <div class="recover docs">
    <div v-if="loadError" class="empty-note">{{ loadError }}</div>

    <!-- ---------- 文档库 ---------- -->
    <template v-if="tab === 'library'">
      <div class="doc-actions">
        <button class="btn solid" :disabled="uploading" @click="triggerUpload">
          {{ uploading ? t.docsUploading : t.docsUpload }}
        </button>
        <button class="btn" :disabled="busy" @click="rebuild">{{ t.docsRebuild }}</button>
        <input ref="fileInput" type="file" class="doc-file"
               accept=".pdf,.docx,.txt,.md" @change="onSelect">
      </div>

      <div class="doc-drop" :class="{dragging}"
           @dragover.prevent="dragging = true"
           @dragleave.prevent="dragging = false"
           @drop.prevent="onDrop">
        {{ t.docsDrop }}
      </div>

      <div v-if="!docs.length" class="empty-note">
        {{ t.docsEmpty }}<br>
        <span style="font-size:10.5px">{{ t.docsEmptyHint }}</span>
      </div>

      <div v-for="d in docs" :key="d.id" class="doc-row">
        <span class="doc-kind" :class="d.kind">{{ KIND_LABEL[d.kind] || d.kind }}</span>
        <span class="doc-nm" :title="d.name">{{ d.name }}</span>
        <span class="doc-meta">
          {{ fmt(t.docsChunks, { n: d.chunks }) }} · {{ sizeText(d.size) }} · {{ shortTime(d.added_at) }}
        </span>
        <button class="btn" @click="openPreview(d)">{{ t.docsPreview }}</button>
        <button class="btn danger" @click="pendingDelete = d">{{ t.docsDelete }}</button>
      </div>

      <!-- 检索测试：上传完资料，立刻确认"它真的搜得到" -->
      <div class="doc-search">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round">
          <circle cx="11" cy="11" r="7"></circle>
          <path d="m20 20-3.5-3.5"></path>
        </svg>
        <input v-model="q" :placeholder="t.docsSearchPlaceholder" @keydown.enter="search">
        <button class="btn" :disabled="searching" @click="search">{{ t.docsSearch }}</button>
      </div>

      <template v-if="searched">
        <div v-if="!results.length" class="empty-note">{{ t.docsSearchEmpty }}</div>
        <div v-for="r in results" :key="r.chunk_id" class="doc-hit">
          <div class="doc-hit-head">
            <b>{{ r.doc }}</b>
            <span class="doc-score">{{ r.score }}</span>
          </div>
          <p>{{ r.text }}</p>
        </div>
      </template>
    </template>

    <!-- ---------- 回收站 ---------- -->
    <template v-else>
      <div v-if="!deleted.length" class="empty-note">{{ t.docsTrashEmpty }}</div>
      <div v-for="d in deleted" :key="d.id" class="doc-row">
        <span class="doc-kind" :class="d.kind">{{ KIND_LABEL[d.kind] || d.kind }}</span>
        <span class="doc-nm" :title="d.name">{{ d.name }}</span>
        <span class="doc-meta">
          {{ fmt(t.docsChunks, { n: d.chunks }) }}
          · {{ fmt(t.docsDeletedAt, { at: shortTime(d.deleted_at) }) }}
          <template v-if="d.days_left != null">
            · {{ fmt(t.docsDaysLeft, { n: d.days_left }) }}
          </template>
        </span>
        <button class="btn" :disabled="busy" @click="restore(d)">{{ t.docsRestore }}</button>
      </div>
    </template>
  </div>

  <!-- 删除确认：软删，保留期内可恢复 -->
  <div v-if="pendingDelete" class="modal-mask" @click.self="pendingDelete = null">
    <div class="modal rec-modal-sm">
      <div class="modal-head">
        <span class="modal-title">{{ t.docsDeleteTitle }}</span>
      </div>
      <div class="modal-body rec-confirm">
        <div class="rec-line"><span>文档</span><b>{{ pendingDelete.name }}</b></div>
        <div class="rec-line"><span>切片</span><b>{{ pendingDelete.chunks }}</b></div>
        <p class="rec-warn">{{ t.docsDeleteWarn }}</p>
      </div>
      <div class="modal-foot">
        <button class="btn" @click="pendingDelete = null" :disabled="busy">{{ t.cancel }}</button>
        <button class="btn danger" @click="confirmDelete" :disabled="busy">
          {{ t.docsConfirmDelete }}
        </button>
      </div>
    </div>
  </div>

  <!-- 原文预览：解析后的全文 + 分块，顺带能核对切得好不好 -->
  <div v-if="preview" class="modal-mask" @click.self="preview = null">
    <div class="modal doc-preview-modal">
      <div class="modal-head">
        <span class="modal-title">{{ t.docsPreview }} · {{ preview.name }}</span>
        <button class="modal-x" @click="preview = null">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
               stroke-linecap="round" stroke-linejoin="round">
            <line x1="18" y1="6" x2="6" y2="18"></line>
            <line x1="6" y1="6" x2="18" y2="18"></line>
          </svg>
        </button>
      </div>
      <div class="modal-body">
        <div v-if="isMarkdown(preview.name)" class="modal-doc prose"
             v-html="md(preview.text)"></div>
        <pre v-else class="modal-text">{{ preview.text }}</pre>
        <div class="doc-chunks">
          <div class="doc-chunks-title">
            {{ t.docsChunksTitle }} · {{ fmt(t.docsChunks, { n: preview.chunks.length }) }}
          </div>
          <div v-for="c in preview.chunks" :key="c.seq" class="doc-chunk">
            <span class="doc-chunk-no">#{{ c.seq + 1 }}</span>
            <p>{{ c.text }}</p>
          </div>
        </div>
      </div>
      <div class="modal-foot">
        <button class="btn solid" @click="preview = null">{{ t.recoverClose }}</button>
      </div>
    </div>
  </div>
</main>
`,
};
