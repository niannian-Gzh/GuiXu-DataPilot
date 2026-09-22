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
      <svg viewBox="0 0 48 48" fill="none">
        <defs>
          <linearGradient id="cp-lit" gradientUnits="userSpaceOnUse" x1="24" y1="4" x2="24" y2="44">
            <stop offset="0" stop-color="var(--rose-hi)"/>
            <stop offset="0.5" stop-color="var(--rose-mid)"/>
            <stop offset="1" stop-color="var(--rose-mid)" stop-opacity=".62"/>
          </linearGradient>
          <linearGradient id="cp-shade" gradientUnits="userSpaceOnUse" x1="24" y1="4" x2="24" y2="44">
            <stop offset="0" stop-color="var(--rose-mid)"/>
            <stop offset="0.5" stop-color="var(--rose-lo)"/>
            <stop offset="1" stop-color="var(--rose-lo)" stop-opacity=".48"/>
          </linearGradient>
          <linearGradient id="cp-tick" gradientUnits="userSpaceOnUse" x1="24" y1="4" x2="24" y2="44">
            <stop offset="0" stop-color="var(--mark)" stop-opacity=".72"/>
            <stop offset="1" stop-color="var(--mark)" stop-opacity=".3"/>
          </linearGradient>
          <linearGradient id="cp-ring" gradientUnits="userSpaceOnUse" x1="24" y1="4" x2="24" y2="44">
            <stop offset="0" stop-color="var(--mark)" style="stop-opacity:var(--ring-hi)"/>
            <stop offset="0.5" stop-color="var(--mark)" style="stop-opacity:var(--ring-mid)"/>
            <stop offset="1" stop-color="var(--mark)" style="stop-opacity:var(--ring-lo)"/>
          </linearGradient>
          <linearGradient id="cp-arc" gradientUnits="userSpaceOnUse"
                          x1="9.28" y1="32.5" x2="35.6" y2="11.6">
            <stop offset="0" stop-color="var(--rose-mid)" stop-opacity="0"/>
            <stop offset="0.55" stop-color="var(--rose-mid)" stop-opacity=".38"/>
            <stop offset="1" stop-color="var(--rose-mid)" stop-opacity=".8"/>
          </linearGradient>
          <radialGradient id="cp-core">
            <stop offset="0" stop-color="var(--rose-core-hi)"/>
            <stop offset="0.45" stop-color="var(--rose-core)"/>
            <stop offset="1" stop-color="var(--rose-core)" stop-opacity=".22"/>
          </radialGradient>
          <radialGradient id="cp-halo">
            <stop offset="0" stop-color="var(--rose-hi)" style="stop-opacity:var(--rose-halo)"/>
            <stop offset="0.55" stop-color="var(--rose-hi)" style="stop-opacity:calc(var(--rose-halo) * .38)"/>
            <stop offset="1" stop-color="var(--rose-hi)" stop-opacity="0"/>
          </radialGradient>
          <filter id="cp-glow" x="-300%" y="-300%" width="700%" height="700%">
            <feGaussianBlur stdDeviation="1.4"/>
          </filter>
          <filter id="cp-spark" x="-400%" y="-400%" width="900%" height="900%">
            <feGaussianBlur stdDeviation="0.45"/>
          </filter>
        </defs>

        <circle cx="24" cy="24" r="23.5" fill="url(#cp-halo)"/>

        <!-- 刻度：12 条径向细线，0/90/180/270 为主。
             类名留在 g 上，展开动画（rotate + scale）照旧作用在整圈 -->
        <g class="ticks" stroke="url(#cp-tick)">
          <line x1="24" y1="4.1" x2="24" y2="0.8" stroke-width=".9" transform="rotate(0 24 24)"/>
          <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".55" transform="rotate(30 24 24)"/>
          <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".55" transform="rotate(60 24 24)"/>
          <line x1="24" y1="4.1" x2="24" y2="0.8" stroke-width=".9" transform="rotate(90 24 24)"/>
          <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".55" transform="rotate(120 24 24)"/>
          <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".55" transform="rotate(150 24 24)"/>
          <line x1="24" y1="4.1" x2="24" y2="0.8" stroke-width=".9" transform="rotate(180 24 24)"/>
          <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".55" transform="rotate(210 24 24)"/>
          <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".55" transform="rotate(240 24 24)"/>
          <line x1="24" y1="4.1" x2="24" y2="0.8" stroke-width=".9" transform="rotate(270 24 24)"/>
          <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".55" transform="rotate(300 24 24)"/>
          <line x1="24" y1="2.8" x2="24" y2="0.8" stroke-width=".55" transform="rotate(330 24 24)"/>
        </g>
        <circle class="ring-inner" cx="24" cy="24" r="14"
                stroke="url(#cp-ring)" stroke-width=".8"></circle>

        <!-- 四个芒尖各有类名，依次点亮的顺序写在 CSS 里。
             每个尖是两个面，用 g 包起来——动画的 opacity / filter 作用在 g 上，
             两个面一起亮一起灭 -->
        <g class="rose">
          <g class="tip tip-n">
            <path d="M24 5 L24 19.5 L19.5 24 Z" fill="url(#cp-lit)"></path>
            <path d="M24 5 L28.5 24 L24 19.5 Z" fill="url(#cp-shade)"></path>
          </g>
          <g class="tip tip-s">
            <path d="M24 43 L24 28.5 L19.5 24 Z" fill="url(#cp-lit)" opacity=".88"></path>
            <path d="M24 43 L28.5 24 L24 28.5 Z" fill="url(#cp-shade)" opacity=".88"></path>
          </g>
          <g class="tip tip-w">
            <path d="M5 24 L24 19.5 L19.5 24 Z" fill="url(#cp-lit)" opacity=".94"></path>
            <path d="M5 24 L19.5 24 L24 28.5 Z" fill="url(#cp-shade)" opacity=".94"></path>
          </g>
          <g class="tip tip-e">
            <path d="M43 24 L24 19.5 L28.5 24 Z" fill="url(#cp-lit)" opacity=".94"></path>
            <path d="M43 24 L28.5 24 L24 28.5 Z" fill="url(#cp-shade)" opacity=".94"></path>
          </g>
        </g>

        <g class="rose-core">
          <circle cx="24" cy="24" r="3.4" fill="var(--rose-hi)"
                  style="opacity:var(--rose-core-glow)" filter="url(#cp-glow)"></circle>
          <circle cx="24" cy="24" r="2.5" fill="url(#cp-core)"></circle>
        </g>

        <g class="helm-spin">
          <path class="helm-arc" d="M9.28 32.5 A17 17 0 0 1 35.6 11.6"
                stroke="url(#cp-arc)" stroke-width="1.7" fill="none"></path>
          <circle class="helm-dot" cx="35.6" cy="11.6" r="2.2" fill="var(--rose-mid)"></circle>
          <circle class="helm-dot" cx="35.6" cy="11.6" r=".9" fill="var(--rose-hi)"></circle>
        </g>

        <!-- 尖端高光：跟北尖锁定（2.40s）一起出现 -->
        <circle class="spark" cx="24" cy="6.9" r="1.15" fill="var(--rose-spark)"
                filter="url(#cp-spark)"></circle>
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
