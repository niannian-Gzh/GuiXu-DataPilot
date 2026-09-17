/* 右栏：本次会话的产物列表。轨迹已搬到左栏独立页 */
export default {
  name: 'FilesPanel',
  setup() {
    // 共享 store 展开后仍是 ref 对象本身，响应性不丢，
    // 模板里的插值和事件绑定一个字都不用改
    return { ...Vue.inject('store') };
  },
  template: `
  <aside class="col glass" :class="{hidden: !railOpen}">
    <div class="rail-head">
      <button class="tab" :class="{on: rail === 'artifacts'}" @click="rail = 'artifacts'">
        {{ t.artifacts }} <b>{{ allArtifacts.length }}</b>
      </button>
      <span style="flex:1"></span>
      <button class="icon-btn" @click="toggleRail" title="收起右侧栏">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
             stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 18 15 12 9 6"></polyline>
        </svg>
      </button>
    </div>

    <div class="rail-body">
      <!-- 产物 —— 本次对话产出的文件。不进全局列表：
           产物和「哪一轮对话、基于什么条件导出的」绑在一起才有意义 -->
      <template v-if="rail === 'artifacts'">
        <div v-if="!allArtifacts.length" class="empty-note">
          本次会话还没有产出文件<br>
          <span style="font-size:10.5px">试试「把已下证的项目导成 Excel」</span>
        </div>
        <div v-for="(a, i) in allArtifacts" :key="i" class="rail-item">
          <div class="rail-item-top">
            <span class="artifact-icon" :class="a.kind"
                  style="width:24px;height:24px;border-radius:7px">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                   stroke-linecap="round" stroke-linejoin="round" style="width:12px;height:12px">
                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                <polyline points="14 2 14 8 20 8"></polyline>
              </svg>
            </span>
            <span class="name">{{ a.name }}</span>
          </div>
          <div class="rail-item-sub">
            <span>{{ a.label }}</span>
            <span v-if="a.rows != null">{{ a.rows }} 条</span>
          </div>
          <div class="rail-acts">
            <button class="btn" @click="previewFile(a)">{{ t.preview }}</button>
            <button class="btn" @click="download(a.path, a.name)">下载</button>
          </div>
        </div>
      </template>
    </div>
  </aside>
`,
};
