/* 右栏：本次会话的产物列表。轨迹已搬到左栏独立页 */
export default {
  name: 'FilesPanel',
  setup() {
    // 共享 store 展开后仍是 ref 对象本身，响应性不丢，
    // 模板里的插值和事件绑定一个字都不用改
    return { ...Vue.inject('store') };
  },
  template: `
  <aside class="dock" :class="{hidden: !railOpen}">
    <!-- 头部是「计数」，不是「标题 + 按钮」。
         产物就那么几个，用户想知道的是「有几个」——
         所以数字给到 22px，标题给到刻字大小 -->
    <div class="dock-head">
      <div class="t-kicker-zh">产物</div>
      <div class="dock-count">{{ allArtifacts.length }}</div>
      <div class="dock-sub t-meta">本次会话</div>
      <button class="dock-fold" @click="toggleRail" title="收起产物栏">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"
             stroke-linecap="round" stroke-linejoin="round">
          <polyline points="9 18 15 12 9 6"></polyline>
        </svg>
      </button>
    </div>

    <div class="dock-body">
      <!-- 产物 —— 本次对话产出的文件。不进全局列表：
           产物和「哪一轮对话、基于什么条件导出的」绑在一起才有意义 -->
      <div v-if="!allArtifacts.length" class="empty-note">
        本次会话还没有产出文件<br>
        <span style="font-size:10.5px">试试「把已下证的项目导成 Excel」</span>
      </div>
      <!-- 整项可点 = 预览。原来下面挂着「预览 / 下载」两个按钮，
           但下载在预览里也有——一个动作留一个入口就够 -->
      <button v-for="(a, i) in allArtifacts" :key="i" class="art" @click="previewFile(a)">
        <span class="art-ic" :class="a.kind">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
          </svg>
        </span>
        <span class="art-b">
          <span class="art-n">{{ a.name }}</span>
          <span class="art-m">
            {{ a.label }}<template v-if="a.rows != null"> · {{ a.rows }} 行</template>
          </span>
        </span>
      </button>
    </div>
  </aside>
`,
};
