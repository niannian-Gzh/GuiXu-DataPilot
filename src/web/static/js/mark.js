/* 归墟的品牌标记 · 唯一真源
   ============================================================
   几何和开机动画里那枚是【同一个】：50 的画布、中心 25、
   外尖 r21.5、最宽 r15.5、内尖 r6.5。改这里就得同时改
   js/boot.js 的 guixuPetals()——两处一旦不一致，开机和工作台
   就不是一家了。

   填充一律 currentColor。它在开机动画里本来就是纯色的，
   工作台上也该是同一个东西：没有渐变，没有一处模糊半径
   （见 docs/design-language.md 二章）。

   早先这版用的是「八片渐变 + 中心辉光」，那是照意象画的，
   不是照开机动画画的——两边摆在一起一眼就不像一家。
   这类错我犯过两次，判据写在 docs/design-language.md 附二。

   参数来源与逐版对比：.refs/notes/guixu-mark-5.html */

const N = 8;
const R_OUT = 21.5;   // 外尖
const R_IN  = 6.5;    // 内尖：让出一圈空腔给光点
const R_MID = 15.5;   // 最宽处。靠外 ⇒ 读作「流进去」，不是「散出去」
const C     = 25;     // 画布中心
const D     = 8.4;    // 贝塞尔控制点偏移：t = .5 处正好等于半宽

/* 一片纺锤：两端收尖、中间鼓。它不是几个构件拼的——
   是一个母题重复八次 */
const PETAL = `M${C} ${C - R_OUT}`
  + ` Q${C + D} ${C - R_MID} ${C} ${C - R_IN}`
  + ` Q${C - D} ${C - R_MID} ${C} ${C - R_OUT} Z`;

/**
 * 八瓣 + 中心光点。
 *
 * 尺寸和颜色都由调用点的 CSS 给（svg 会撑满容器、颜色取 currentColor），
 * 所以这里没有 size 参数——一处判断散布到各调用点，是「同一个东西长得不一样」
 * 的来源。
 *
 * 两个动作也只写在 CSS 里（css/app.css 的 .gx-petals / .gx-core）：
 * 这里只负责画出来。尺寸小的那几处（顶栏 26px、头像 28px）会被
 * 那一节里的规则关掉动画——折算下来光点才 1px，动了也看不见，
 * 白耗 GPU。
 */
export function guixuMark() {
  // 八片合成一条 path：它们是同一个母题的八次重复，不是八个零件
  const petals = [...Array(N)]
    .map((_, i) => `<path d="${PETAL}" transform="rotate(${(i * 360) / N} ${C} ${C})"/>`)
    .join('');

  return `<svg viewBox="0 0 50 50" fill="none" aria-hidden="true">
<g class="gx-petals" fill="currentColor">${petals}</g>
<circle class="gx-core" cx="${C}" cy="${C}" r="2.6" fill="currentColor"/>
</svg>`;
}
