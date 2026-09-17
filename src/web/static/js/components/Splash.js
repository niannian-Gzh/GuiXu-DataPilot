/* 开机动画。DOM 由 main.js 的 boot() 直接驱动（getElementById），
   模板只是静态骨架，所以这里不需要从 store 取任何东西 */
export default {
  name: 'BootSplash',
  setup() {
    // 模板里没有任何绑定：动画元素由 main.js 的 boot() 用
    // getElementById 直接驱动，所以这里不注入 store
    return {};
  },
  template: `
<div id="boot">
  <div class="boot-stage">
    <div class="compass">
      <svg viewBox="0 0 48 48">
        <circle class="ticks" cx="24" cy="24" r="20.5" stroke-dasharray="1.6 9.13"></circle>
        <circle class="ring-inner" cx="24" cy="24" r="15.5"></circle>

        <!-- 四个芒尖各有类名，依次点亮的顺序写在 CSS 里 -->
        <g class="rose">
          <path class="tip tip-n" d="M24 5 28.5 24 24 19.5 19.5 24Z"></path>
          <path class="tip tip-s" d="M24 43 28.5 24 24 28.5 19.5 24Z"></path>
          <path class="tip tip-w" d="M5 24 24 19.5 19.5 24 24 28.5Z"></path>
          <path class="tip tip-e" d="M43 24 24 19.5 28.5 24 24 28.5Z"></path>
          <circle class="rose-core" cx="24" cy="24" r="2.2"></circle>
        </g>

        <g class="helm-spin">
          <path class="helm-arc" d="M9.2 32.5A17 17 0 0 1 36.4 10.6"></path>
          <circle class="helm-dot" cx="36.6" cy="10.4" r="2.6"></circle>
        </g>
      </svg>
    </div>

    <div>
      <div class="boot-word">
        <span style="animation-delay:.10s">D</span>
        <span style="animation-delay:.16s">A</span>
        <span style="animation-delay:.22s">T</span>
        <span style="animation-delay:.28s">A</span>
        <span style="animation-delay:.34s">P</span>
        <span style="animation-delay:.40s">I</span>
        <span style="animation-delay:.46s">L</span>
        <span style="animation-delay:.52s">O</span>
        <span style="animation-delay:.58s">T</span>
      </div>
      <div class="boot-sub" style="text-align:center;margin-top:9px">DATA PROCESSING AGENT</div>
    </div>

    <div class="boot-stats" v-cloak id="bootStats">
      <!-- 由 Vue 填充：动画时长 = 真实初始化时长 -->
    </div>

    <div class="boot-line"><i id="bootBar"></i></div>
  </div>
</div>
`,
};
