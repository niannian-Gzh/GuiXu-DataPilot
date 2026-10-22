/* ============================================================================
 * 归墟 · 开机动画运行时（浏览器端，零依赖）
 * ----------------------------------------------------------------------------
 * 由 js/boot.config.js 在【用户手势之后】动态加载，在 Vue 应用挂载前接管首屏。
 *
 *   第一幕   黑幕 + 归墟标记／"归墟"／"GUIXU"（字距收紧 + 爆散粒子 + 扫光）
 *   过场     过曝洗白（黑 → 灰 → 暖白底板），硬切
 *   第二幕   技术档案底板：品牌块擦出 / 页脚 / 进度条 / 左侧六格阶段柱
 *   序列     五步，每步「中文大字 + 英文等宽字幕 + 底部长句日志 + 步骤计数」
 *            第 1、2 步等待用户确认（按钮 / Enter / 空格 / 点击），可跳过
 *   终幕     WELCOME TO / [GUIXU] / 归墟标记，色散故障后揭幕
 *
 * 源自 dsh-startup-screen（MIT，Copyright (c) 2026 沈宏宏）。
 * 许可要求副本保留版权与许可声明，所以这段和 css/splash.css 的文件头都不能删。
 *
 * 我们的改动集中在三处，其余是原样：
 *   1. 标识：DeepSeek 鲸鱼 → 归墟八瓣（guixuPetals / svgMark），
 *      CSS 里那个 .dsu-whale 类名留着没动 —— 它是参考样式表的钩子，
 *      改名就得连带改一份 34KB 的样式表，不值当
 *   2. 素材：参考项目那套第三方 mp3 全部摘掉（授权原因，见 DEFAULTS 注释）
 *   3. 时序：白带与扫光音对齐到 750ms，第一句人声单独留白
 *
 * 配置来自 window.__DSH_STARTUP__；window.__DSH_STARTUP_API__.replay() 可重播。
 * ========================================================================== */
(function () {
  'use strict'

  if (window.__DSH_STARTUP_LOADED__) return
  window.__DSH_STARTUP_LOADED__ = true

  var ROOT_ID = 'dsh-startup-root'

  /* ── 默认配置（与 Host 侧 lib/index.js 的 DEFAULTS 保持一致）──────────── */
  /* ── 默认配置（js/boot.config.js 的 window.__DSH_STARTUP__ 覆盖它）────── */
  var DEFAULTS = {
    enabled: true,
    mode: 'session',            // 本标签页播过一次就不再播，见 boot.config.js
    theme: 'dark',              // 归墟是深底，参考项目那套暖白浅色不用
    speed: 1,
    requireInteraction: true,   // 第 1、2 步等待用户确认
    allowSkip: true,

    sound: true,                // 界面音效
    /* 音量的三个数是一起的，改一个要回头看另外两个：
         base × 乘数 × 滑杆值，且外面套了 Math.min(1, …)。
       原来 语音 0.85×1.6=1.36、音效 0.55×2=1.10，两个都撞上限被截到 1，
       滑杆形同虚设，而且语音比音效整整响一倍。
       现在两个乘数都调到「滑杆拉满也不撞顶」的位置（语音 0.72 / 音效 0.88），
       默认值下语音 0.65、音效 0.62 —— 人声是连续的、点击是瞬态的，
       感知上人声会更突出，所以数值上让它略高一点就够了。 */
    soundVolume: 0.7,
    /* 素材策略分两半，原因不同，别混着看：
       【音效】合成。参考项目的 sfx-tick.mp3 / sfx-ticks-run.mp3 是它 README
         里明说的第三方素材，不在 MIT 覆盖范围内，不能随我们的仓库分发 ——
         而打字机那声"哒"原本走的正是它。所以音效全部 WebAudio 现场合成。
       【旁白】素材。/audio/line-1..6.mp3 是我们自己用 edge-tts 的 Ava 音色导出的
         （B 档 rate -14% / pitch +0Hz），不是第三方录音。
         为什么不继续用 TTS：拣音色是浏览器的行为 —— Edge 上是神经语音 Ava、
         Chrome 上是 Google US English、断网又掉回 Zira。同一个人的同一个浏览器，
         声音都能变。开机动画的旁白不该靠浏览器、靠联网、靠系统语言包。
         导成文件之后，声音就锁死在文件里了。
         素材加载不到会自动回落 TTS，见 voice.line()。 */
    sfx: 'synth',
    voiceSource: 'asset',
    assetBase: '/audio/',

    voice: true,
    voiceLang: 'en',            // 英文播报 + 中英字幕：英文音色普遍更好，也更像仪器播报
    /* 下面三行现在【只作用于 TTS 回落】：走素材时不经过 speechSynthesis，
       速度和音调在导出那一刻就烤进 mp3 了，改这三行对旁白没有影响。 */
    voiceName: '',              // '' = 自动挑（见 NATURAL_HINTS / FEMALE_HINTS）
    voiceRate: 0.86,
    voicePitch: 0.55,           // 压一档，往"系统播报"靠。TTS 只有速度和音调两个旋钮
    voiceVolume: 0.9,
    voiceCue: true,             // 开口前后的两声轻提示
    /* 留白同样【只作用于 TTS 回落】。走素材时没有这一环 ——
       line() 是"提示音响过就直接播 mp3"，中间不垫时间；
       留白在设计上属于 TTS：引擎起转有延迟，不垫一下会和人声撞在一起。 */
    voiceLead: 90,              // 提示音之后留多少空白再开口
    /* 第一句单独留白。它前面是一段静场，没有上一句要等 ——
       后面六句的留白是"呼吸"，它的留白只是"延迟"。 */
    voiceLeadFirst: 0,

    identity: 'OPERATOR',
    identityId: '0001',
    accessLevel: '1',
    brand1: 'GUIXU',
    brand2: 'DATA PROCESSING AGENT',
    brand3a: 'GUIXU',
    brand3b: '',
    spacedName: '',
    orgZh: '归墟',
    orgEn: 'GUIXU',
    orgSub: 'DATA PROCESSING AGENT',
    welcomeBox: 'GUIXU',
    footer: 'GUIXU · DATA PROCESSING AGENT',

    /* 配色！下面三行由 root.style.setProperty 写成【内联样式】，
       权重高过任何样式表 —— 所以改颜色改这里，别去 splash.css 里改，
       那儿写了也不生效（旧预览页就栽在这一点上：css 里覆盖的蓝色
       一直被这里的研究橙压着，跑的一直是参考项目的配色）。 */
    accent: '#3d7dff',
    glitchA: '#f87272',
    glitchB: '#3d7dff'
  }

  /* ── 序列脚本：中文主字 + 英文等宽字幕 + 底部日志 ───────────────────────
     `say` 是给语音播报用的自然语句（照着参考片里女声念状态行的节奏），
     卡在各自文字出现的时间点上；`hold` 是视觉基准时长，
     实际停多久取 max(hold, 播报时长 + 收尾留白)，见 stepLoop()。 */
  var STEPS = [
    {
      /* 第 1 步是 config.yaml 的建立点。
         首次启动时它弹一个表单（供应商 / API Key / 模型），
         填完写进 config.yaml 再往下走——而不是让用户事后自己去建一个文件。
         名字不用改：「需要访问许可」本来就是在要一个访问凭证，
         而 API Key 就是那个凭证。 */
      zh: '需要访问许可',
      en: 'ACCESS PERMISSION REQUIRED',
      say: 'Access permission required.',
      audio: 'line-1',
      log: '等待用户授权…',
      logEn: 'AWAITING OPERATOR CONSENT',
      badge: 'AUTHORIZATION',
      action: 'grant',
      btnZh: '授予访问权限',
      btnEn: 'GRANT ACCESS',
      hold: 900,
      progress: 0.34
    },
    {
      zh: '身份资料确认',
      en: 'IDENTITY VERIFICATION',
      say: 'Identity verification.',
      audio: 'line-2',
      log: '核对身份资料…',
      logEn: 'MATCHING OPERATOR RECORD',
      badge: 'IDENTITY',
      action: 'confirm',
      btnZh: '确认身份',
      btnEn: 'CONFIRM IDENTITY',
      hold: 700,
      progress: 0.5
    },
    {
      zh: '接收访问需求',
      en: 'ACCESS REQUEST RECEIVED',
      say: 'Access request received.',
      audio: 'line-3',
      log: '接收访问需求，建立会话通道…',
      logEn: 'HANDSHAKE ESTABLISHED',
      badge: 'REQUEST',
      action: 'auto',
      hold: 1200,
      progress: 0.66,
      assembleLogo: true
    },
    {
      zh: '开始读取权限',
      en: 'PERMISSION READ STARTED',
      say: 'Beginning permission read.',
      audio: 'line-4',
      log: '开始读取权限，索引工作区与会话…',
      logEn: 'READING PERMISSION SET',
      badge: 'READ',
      action: 'auto',
      hold: 1200,
      progress: 0.8,
      hex: true
    },
    {
      zh: '读取完毕 · 核验通过',
      en: 'READ COMPLETE · VERIFIED',
      say: 'Read complete. Verification passed.',
      audio: 'line-5',
      log: '读取完毕，核验通过，权限已授予',
      logEn: 'PERMISSION AUTHORIZED',
      badge: 'VERIFY',
      action: 'auto',
      hold: 1600,
      progress: 0.93,
      reticle: true
    }
  ]

  function cfg() {
    var raw = (window.__DSH_STARTUP__ && typeof window.__DSH_STARTUP__ === 'object')
      ? window.__DSH_STARTUP__
      : {}
    var out = {}
    for (var k in DEFAULTS) if (Object.prototype.hasOwnProperty.call(DEFAULTS, k)) out[k] = DEFAULTS[k]
    for (var k2 in raw) {
      if (Object.prototype.hasOwnProperty.call(raw, k2) && raw[k2] !== undefined && raw[k2] !== null) {
        out[k2] = raw[k2]
      }
    }
    out.speed = Math.min(3, Math.max(0.35, Number(out.speed) || 1))
    if (!out.spacedName) out.spacedName = String(out.orgEn || DEFAULTS.orgEn).toUpperCase().split('').join(' ')
    out.identity = String(out.identity || DEFAULTS.identity).slice(0, 48)
    /* 代号取身份名称里的字母数字；纯中文名字取不到时退回 OPERATOR */
    out.identityId = String(out.identityId || out.identity).toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 12)
    if (!out.identityId) out.identityId = 'OPERATOR'
    return out
  }

  var C = cfg()

  /** 重播：把运行时脚本重新挂一次（配置/身份名称改动后 preview 用它）。 */
  function injectSelf() {
    window.__DSH_STARTUP_LOADED__ = false
    var old = document.getElementById(ROOT_ID)
    if (old && old.parentNode) old.parentNode.removeChild(old)
    window.__DSH_STARTUP_SKIP__ = false
    var s = document.createElement('script')
    /* 正式运行时由 Host 路由提供（加时间戳绕开缓存）；
       离线预览页会把相对路径写进 __DSH_STARTUP_SCRIPT_URL__，file:// 下不加查询串。 */
    if (window.__DSH_STARTUP_SCRIPT_URL__) {
      s.src = window.__DSH_STARTUP_SCRIPT_URL__
    } else {
      s.src = '/js/boot.js?t=' + Date.now()
    }
    document.head.appendChild(s)
  }

  /* Host 侧的首屏兜底脚本已经判定"这次不播"（未启用 / 本会话已播 / 今日已播）：
     这里不再建 DOM，但仍然暴露 API，方便设置页按需重播。 */
  if (window.__DSH_STARTUP_SKIP__ === true) {
    window.__DSH_STARTUP_API__ = {
      replay: injectSelf,
      skip: function () {},
      finish: function () {},
      config: C
    }
    return
  }

  /* 最后一道保险：无论前面哪一步抛异常，都不许把用户留在黑幕里 */
  setTimeout(function () {
    try {
      var r = document.getElementById(ROOT_ID)
      if (r && r.classList && r.classList.contains('dsu-boot')) {
        if (r.parentNode) r.parentNode.removeChild(r)
        document.documentElement.classList.remove('dsu-lock')
        if (document.body) document.body.style.overflow = ''
        window.__DSH_STARTUP_FAILED__ = true
      }
    } catch (e) { /* 兜底本身不许再抛 */ }
  }, 9000)

  /* ── 小工具 ───────────────────────────────────────────────────────────── */
  function el(tag, cls, text) {
    var n = document.createElement(tag)
    if (cls) n.className = cls
    if (text != null) n.textContent = text
    return n
  }

  /* 归墟：八片纺锤。整朵合成【一个 path】而不是八个——
     因为下面 assembleLogo() 要靠 path.getTotalLength() 做参考片那套
     「先勾线、再落墨」；八个独立 path 的话它只会画到第一片。
     合成一条之后，勾线会绕着圆心把八瓣依次描出来，落墨是一次填满。

     几何取自 src/web/static/js/mark.js：花瓣两端收尖、最宽处靠外，
     外尖 r22.4 / 内尖 r6.8（50 画布，中心 25）。 */
  function guixuPetals() {
    var base = [[0, -21.5], [8.4, -15.5], [0, -6.5], [-8.4, -15.5]]
    var d = ''
    for (var i = 0; i < 8; i++) {
      var t = i * 45 * Math.PI / 180, cs = Math.cos(t), sn = Math.sin(t)
      var pts = base.map(function (p) {
        return [
          (25 + p[0] * cs - p[1] * sn).toFixed(2),
          (25 + p[0] * sn + p[1] * cs).toFixed(2)
        ]
      })
      d += 'M' + pts[0].join(' ') + 'Q' + pts[1].join(' ') + ' ' + pts[2].join(' ') +
           'Q' + pts[3].join(' ') + ' ' + pts[0].join(' ') + 'Z'
    }
    return d
  }

  function svgMark(cls) {
    var ns = 'http://www.w3.org/2000/svg'
    var svg = document.createElementNS(ns, 'svg')
    svg.setAttribute('viewBox', '0 0 50 50')
    svg.setAttribute('aria-hidden', 'true')
    if (cls) svg.setAttribute('class', cls)
    var p = document.createElementNS(ns, 'path')
    p.setAttribute('d', guixuPetals())
    p.setAttribute('fill-rule', 'nonzero')
    p.setAttribute('fill', 'currentColor')
    svg.appendChild(p)
    var c = document.createElementNS(ns, 'circle')
    c.setAttribute('cx', '25'); c.setAttribute('cy', '25'); c.setAttribute('r', '2.6')
    c.setAttribute('fill', 'currentColor')
    svg.appendChild(c)
    return svg
  }

  /* 收紧那一刻的碎屑爆散。
     —— 爆心在【正在收紧的那行字】上：收紧的是它，碎的就该是它。
     —— 方向一律朝外：每颗碎屑的航向由它离爆心的方位角决定（再叠一点抖动），
        所以不会出现"穿过中心"或者"往里收"的粒子。
     —— 起点沿整行撒开，读起来是"整行崩开"，不是一个点喷出。
     —— 速度偏斜（多数中速、少数飞极远）、寿命各不相同（先后碎灭），
        这两条是"碎"的来源；整齐的速度和寿命只会散成一圈水花。
     —— 尺寸：最小 0.7、最大 3.4（硬上限，不越）。
     纯实心圆，没有 shadowBlur。 */
  function burstParticles() {
    var host = ui.black
    if (!host) return
    var anchor = ui.blackEn || ui.blackInner
    if (!anchor) return

    var cv = document.createElement('canvas')
    cv.className = 'dsu-burst'
    host.appendChild(cv)
    var dpr = Math.min(window.devicePixelRatio || 1, 2)
    var W = host.clientWidth || window.innerWidth
    var H = host.clientHeight || window.innerHeight
    cv.width = W * dpr; cv.height = H * dpr
    cv.style.width = W + 'px'; cv.style.height = H + 'px'
    var g = cv.getContext('2d')
    g.setTransform(dpr, 0, 0, dpr, 0, 0)

    var box = anchor.getBoundingClientRect()
    var hb = host.getBoundingClientRect()
    var cx = box.left - hb.left + box.width / 2
    var cy = box.top - hb.top + box.height / 2
    var span = Math.max(140, box.width)

    var R_MIN = 0.7, R_MAX = 2.5          // 硬上限：任何碎屑都不会超过 R_MAX

    var ps = []
    for (var i = 0; i < 170; i++) {
      var px = cx + (Math.random() - 0.5) * span * 0.85
      var py = cy + (Math.random() - 0.5) * 16
      var dx = px - cx, dy = py - cy
      var dl = Math.sqrt(dx * dx + dy * dy)
      /* 航向 = 该点到爆心的方位角（一律朝外）+ 一点抖动，
         抖动是为了不让它退化成一条水平直线 */
      var ang = (dl > 8 ? Math.atan2(dy, dx) : Math.random() * Math.PI * 2)
                + (Math.random() - 0.5) * 0.9
      var sp = 200 + Math.pow(Math.random(), 2.1) * 780
      ps.push({
        x: px, y: py,
        vx: Math.cos(ang) * sp,
        vy: Math.sin(ang) * sp,
        r: R_MIN + Math.random() * (R_MAX - R_MIN),
        life: 0.38 + Math.random() * 0.70,
        t: 0
      })
    }

    var last = performance.now()
    ;(function tick(now) {
      var dt = Math.min(48, now - last) / 1000; last = now
      g.clearRect(0, 0, W, H)
      var alive = 0
      for (var i = 0; i < ps.length; i++) {
        var p = ps[i]
        p.t += dt
        var k = 1 - p.t / p.life
        if (k <= 0) continue
        alive++
        p.x += p.vx * dt; p.y += p.vy * dt
        p.vx *= 0.980; p.vy *= 0.980       // 阻尼再放轻，溅得更远
        g.beginPath()
        g.arc(p.x, p.y, Math.max(0.15, p.r * (0.34 + k * 0.66)), 0, 6.2832)
        g.fillStyle = 'rgba(232,240,255,' + (0.85 * Math.min(1, k * 1.7)).toFixed(3) + ')'
        g.fill()
      }
      if (alive) requestAnimationFrame(tick)
      else if (cv.parentNode) cv.parentNode.removeChild(cv)
    })(last)
  }

  /** 逐字渐显：比逐字截断更稳（居中排版不会因为字宽变化而抖动） */
  function typeIn(host, text, stagger) {
    host.textContent = ''
    var frag = document.createDocumentFragment()
    var n = 0
    for (var i = 0; i < text.length; i++) {
      var ch = text.charAt(i)
      if (ch === ' ') {
        frag.appendChild(document.createTextNode('\u00a0'))
        continue
      }
      var s = el('span', 'dsu-ch', ch)
      s.style.transitionDelay = Math.round(n * stagger) + 'ms'
      frag.appendChild(s)
      n++
    }
    host.appendChild(frag)
  }

  function setIn(node, on, cls) {
    if (!node) return
    node.classList.toggle(cls || 'dsu-in', !!on)
  }

  /* ── DOM 搭建 ─────────────────────────────────────────────────────────── */
  var root = document.getElementById(ROOT_ID)
  if (!root) {
    root = el('div')
    root.id = ROOT_ID
    root.className = 'dsu-root'
    document.body.appendChild(root)
  }
  root.classList.toggle('dsu-dark', C.theme === 'dark')
  root.style.setProperty('--dsu-speed', String(C.speed))
  root.style.setProperty('--dsu-accent', C.accent)
  root.style.setProperty('--dsu-glitch-a', C.glitchA)
  root.style.setProperty('--dsu-glitch-b', C.glitchB)

  var ui = {}
  var clockTimer = null
  var html =
    '<div class="dsu-plate"></div>' +
    '<div class="dsu-vignette"></div>' +
    '<div class="dsu-watermark"></div>' +
    '<div class="dsu-grain"></div>' +
    '<div class="dsu-black">' +
      '<div class="dsu-black-inner"></div>' +
      '<div class="dsu-sweep"></div>' +
    '</div>' +
    '<div class="dsu-wash"></div>' +
    '<header class="dsu-brand">' +
      '<div class="dsu-brand-1"></div><div class="dsu-brand-2"></div>' +
      '<div class="dsu-brand-3"><b></b><span></span></div>' +
    '</header>' +
    '<div class="dsu-stepcount">[ 00 / 06 ] INIT</div>' +
    '<div class="dsu-center">' +
      '<div class="dsu-status"><span class="dsu-status-zh"></span><i class="dsu-caret"></i></div>' +
      '<div class="dsu-sub-en"></div>' +
      '<div class="dsu-rule"></div>' +
      '<div class="dsu-logo"></div>' +
      '<div class="dsu-dots" hidden></div>' +
    '</div>' +
    '<div class="dsu-idline"></div>' +
    '<div class="dsu-reticle"></div>' +
    '<div class="dsu-hex"></div>' +
    '<div class="dsu-welcome">' +
      '<div class="dsu-w1">WELCOME TO</div>' +
      '<div class="dsu-w2"></div>' +
      '<div class="dsu-w3"></div>' +
      '<div class="dsu-w4"></div>' +
    '</div>' +
    '<div class="dsu-action">' +
      '<div class="dsu-card" hidden></div>' +
      '<button class="dsu-btn" type="button">' +
        '<span class="dsu-btn-zh"></span><span class="dsu-btn-en"></span>' +
      '</button>' +
      '<div class="dsu-hint"></div>' +
    '</div>' +
    /* 首次启动的表单。它是动画里唯一需要打字的地方，所以做成「弹窗」——
       浮在中央、盖住一部分场景，而不是挤进底部按钮那一行。
       没有步骤条：就一步，画两条进度是假的。
       「接口地址」默认不出，选了自定义供应商才长出来——
       预设供应商的地址是已知的，让用户填是给他出题。
       按钮单独一个类名，不能叫 .dsu-btn —— 那个是底部那枚，q() 会抓错 */
    '<div class="dsu-form" hidden>' +
      '<div class="dsu-form-in">' +
        '<i class="dsu-fbr dsu-fbr-tl"></i><i class="dsu-fbr dsu-fbr-tr"></i>' +
        '<i class="dsu-fbr dsu-fbr-bl"></i><i class="dsu-fbr dsu-fbr-br"></i>' +

        '<div class="dsu-form-top">' +
          '<div class="dsu-form-mark"></div>' +
          '<div class="dsu-form-kicker">INITIALIZE</div>' +
          '<div class="dsu-form-title">初始化配置</div>' +
        '</div>' +
        '<div class="dsu-form-rule"></div>' +

        '<div class="dsu-ff">' +
          '<div class="dsu-ff-l">' +
            '<span class="dsu-ff-k">供应商</span>' +
            '<span class="dsu-ff-h">PRESET</span>' +
          '</div>' +
          /* 选项从 /settings/providers 拉（17 家），不硬编码。
             value 用 id，落盘时再到那份预设里查 env 变量名——
             每家密钥的环境变量名都不一样 */
          '<div class="dsu-ff-box">' +
            '<select class="dsu-form-sel" data-k="provider">' +
              '<option value="">载入中…</option>' +
            '</select>' +
            '<svg class="dsu-ff-chev" viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2.5 4.5 6 8l3.5-3.5"/></svg>' +
          '</div>' +
        '</div>' +

        /* 自定义供应商才需要：预设的地址是已知的 */
        '<div class="dsu-ff" data-only="custom" hidden>' +
          '<div class="dsu-ff-l">' +
            '<span class="dsu-ff-k">接口地址</span>' +
            '<span class="dsu-ff-h">BASE URL</span>' +
          '</div>' +
          '<div class="dsu-ff-box">' +
            '<input class="dsu-form-inp" data-k="base_url" type="text" placeholder="https://…/v1" spellcheck="false">' +
          '</div>' +
        '</div>' +

        '<div class="dsu-ff">' +
          '<div class="dsu-ff-l">' +
            '<span class="dsu-ff-k">API 密钥</span>' +
            '<span class="dsu-ff-h">API KEY</span>' +
          '</div>' +
          '<div class="dsu-ff-box">' +
            '<input class="dsu-form-inp" data-k="key" type="password" placeholder="sk-…" spellcheck="false">' +
          '</div>' +
        '</div>' +

        /* 模型这格用 datalist 而不是 select：能选也能打。
           拉得到就列出来选，拉不到（不是所有家都实现了 /models）
           用户还能自己填 —— select 会把这条路堵死 */
        '<div class="dsu-ff dsu-ff-model">' +
          '<div class="dsu-ff-l">' +
            '<span class="dsu-ff-k">模型</span>' +
            '<span class="dsu-ff-h">MODEL</span>' +
          '</div>' +
          '<div class="dsu-ff-box">' +
            '<input class="dsu-form-inp" data-k="model" type="text" placeholder="填完密钥后自动获取" spellcheck="false">' +
            '<span class="dsu-ff-state"></span>' +
            '<button class="dsu-ff-pick" type="button" title="选择模型" aria-label="选择模型">' +
              '<svg viewBox="0 0 12 12" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2.5 4.5 6 8l3.5-3.5"/></svg>' +
            '</button>' +
            '<div class="dsu-model-menu" hidden></div>' +
          '</div>' +
        '</div>' +

        '<div class="dsu-form-err" hidden></div>' +

        '<div class="dsu-form-note">' +
          '密钥只写入本机 config.yaml，不随任何请求外传。' +
          '这里也是本项目唯一的网络依赖——数据源在本地。' +
        '</div>' +

        '<div class="dsu-form-go">' +
          '<button class="dsu-form-btn" type="button">' +
            '<span>验证并接入</span>' +
            '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M2.5 8h11M9 3.5 13.5 8 9 12.5"/></svg>' +
          '</button>' +
        '</div>' +
      '</div>' +
    '</div>' +
    '<div class="dsu-frame">' +
      '<i class="dsu-corner dsu-c-tl"></i><i class="dsu-corner dsu-c-tr"></i>' +
      '<i class="dsu-corner dsu-c-bl"></i><i class="dsu-corner dsu-c-br"></i>' +
      '<div class="dsu-scanline"></div>' +
    '</div>' +
    '<div class="dsu-slats"></div>' +
    '<div class="dsu-voice"><i></i><i></i><i></i><i></i><i></i></div>' +
    '<div class="dsu-meta"><span class="dsu-meta-1"></span><span class="dsu-meta-2"></span></div>' +
    '<div class="dsu-skip">SKIP ▸</div>' +
    '<footer class="dsu-foot"><span></span><i></i></footer>' +
    '<div class="dsu-subtitle">' +
      '<span class="dsu-sub-zh"></span><span class="dsu-sub-en2"></span>' +
    '</div>' +
    '<div class="dsu-progress"><i></i></div>' +
    '<div class="dsu-bloom"></div>' +
    '<div class="dsu-streak"></div>' +
    '<div class="dsu-flash"></div>'

  root.innerHTML = html

  function q(sel) { return root.querySelector(sel) }
  ui.plate = q('.dsu-plate')
  ui.watermark = q('.dsu-watermark')
  ui.black = q('.dsu-black')
  ui.blackInner = q('.dsu-black-inner')
  ui.sweep = q('.dsu-sweep')
  ui.wash = q('.dsu-wash')
  ui.flash = q('.dsu-flash')
  ui.bloom = q('.dsu-bloom')
  ui.streak = q('.dsu-streak')
  ui.vignette = q('.dsu-vignette')
  ui.brand = q('.dsu-brand')
  ui.center = q('.dsu-center')
  ui.brand1 = q('.dsu-brand-1')
  ui.brand2 = q('.dsu-brand-2')
  ui.brand3b = q('.dsu-brand-3 b')
  ui.brand3s = q('.dsu-brand-3 span')
  ui.stepcount = q('.dsu-stepcount')
  ui.status = q('.dsu-status')
  ui.statusZh = q('.dsu-status-zh')
  ui.caret = q('.dsu-caret')
  ui.subEn = q('.dsu-sub-en')
  ui.rule = q('.dsu-rule')
  ui.logo = q('.dsu-logo')
  ui.dots = q('.dsu-dots')
  ui.idline = q('.dsu-idline')
  ui.reticle = q('.dsu-reticle')
  ui.hex = q('.dsu-hex')
  ui.welcome = q('.dsu-welcome')
  ui.w1 = q('.dsu-w1')
  ui.w2 = q('.dsu-w2')
  ui.w3 = q('.dsu-w3')
  ui.w4 = q('.dsu-w4')
  ui.action = q('.dsu-action')
  ui.card = q('.dsu-card')
  ui.btn = q('.dsu-btn')
  ui.btnZh = q('.dsu-btn-zh')
  ui.btnEn = q('.dsu-btn-en')
  ui.hint = q('.dsu-hint')
  ui.form = q('.dsu-form')
  ui.formInp = q('.dsu-form [data-k="key"]')
  ui.formErr = q('.dsu-form-err')
  ui.formBtn = q('.dsu-form-btn')
  ui.formProvider = q('.dsu-form [data-k="provider"]')
  /* 标记和动画其它地方用的是同一个 svg —— 它在这儿代表「谁在问你」 */
  q('.dsu-form-mark').appendChild(svgMark())
  ui.formBtn.addEventListener('click', submitForm)
  ui.formProvider.addEventListener('change', function () {
    syncCustom()
    /* 换供应商 = 换端点，之前那份列表作废 */
    var list = document.getElementById('dsu-model-list')
    if (list) list.innerHTML = ''
    var m = root.querySelector('.dsu-form [data-k="model"]')
    if (m) m.value = ''
    setModelState('')
    pullModels()
  })
  /* 填完密钥（或地址）松手就去拉一次。用 blur 不用 input ——
     否则每敲一个字发一个请求 */
  q('.dsu-form [data-k="key"]').addEventListener('blur', pullModels)
  q('.dsu-form [data-k="base_url"]').addEventListener('blur', pullModels)
  /* 模型下拉：自定义菜单，不依赖原生 datalist 的箭头行为。
     点箭头开合，点选项回填，点表单外/Esc 关闭。 */
  var modelPick = q('.dsu-ff-pick')
  var modelMenu = q('.dsu-model-menu')
  if (modelPick && modelMenu) {
    modelPick.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation()
      modelMenu.hidden = !modelMenu.hidden
    })
    q('.dsu-form [data-k="model"]').addEventListener('focus', function () {
      if (modelMenu.children.length) modelMenu.hidden = false
    })
    document.addEventListener('click', function (e) {
      if (!modelMenu.hidden && !e.target.closest('.dsu-ff-model')) modelMenu.hidden = true
    })
    q('.dsu-form [data-k="model"]').addEventListener('keydown', function (e) {
      if (e.key === 'Escape') modelMenu.hidden = true
    })
  }
  /* 表单里按 Enter 是「提交」，不是「继续」——输入框里的回车和空白键的回车
     是两件事，不拦的话用户填完一按就跳过了整段动画 */
  q('.dsu-form').addEventListener('keydown', function (e) {
    if (e.key !== 'Enter') return
    if (e.target && e.target.tagName === 'SELECT') return
    e.preventDefault(); e.stopPropagation(); submitForm()
  })
  ui.skip = q('.dsu-skip')
  ui.foot = q('.dsu-foot')
  ui.footText = q('.dsu-foot span')
  ui.subZh = q('.dsu-sub-zh')
  ui.subEn2 = q('.dsu-sub-en2')
  ui.progress = q('.dsu-progress')
  ui.bar = q('.dsu-progress i')
  ui.frame = q('.dsu-frame')
  ui.scanline = q('.dsu-scanline')
  ui.slats = q('.dsu-slats')
  ui.voice = q('.dsu-voice')
  ui.meta = q('.dsu-meta')
  ui.meta1 = q('.dsu-meta-1')
  ui.meta2 = q('.dsu-meta-2')

  /* 内容填充 */
  ui.brand1.textContent = C.brand1
  ui.brand2.textContent = C.brand2
  ui.brand3b.textContent = C.brand3a
  ui.brand3s.textContent = C.brand3b
  ui.footText.textContent = C.footer
  ui.w2.textContent = C.welcomeBox
  ui.w4.textContent = '欢迎 ' + C.identity + ' 访问'
  ui.idline.textContent = '· ID CONFIRMED : ' + C.identityId

  ;(function blackStage() {
    var inner = ui.blackInner
    var mark = svgMark('dsu-whale')
    inner.appendChild(mark)
    inner.appendChild(el('div', 'dsu-black-zh', C.orgZh))
    var en = el('div', 'dsu-black-en', C.orgEn)
    inner.appendChild(en)
    inner.appendChild(el('div', 'dsu-black-sub', C.orgSub))
    ui.blackEn = en
  })()

  ;(function logoStage() {
    ui.logo.appendChild(svgMark())
    ui.logo.appendChild(el('div', 'dsu-logolabel', C.spacedName))
  })()

  ;(function welcomeLogo() {
    ui.w3.appendChild(svgMark())
    ui.w3.appendChild(el('span', 'dsu-w3label', C.spacedName))
  })()

  ;(function watermark() {
    var boxes = [
      [0.60, 0.02, 0.16, 0.96], [0.78, 0.02, 0.16, 0.96], [0.96, 0.02, 0.16, 0.96],
      [0.05, 0.02, 0.10, 0.5]
    ]
    for (var i = 0; i < boxes.length; i++) {
      var b = boxes[i]
      var n = el('div', 'dsu-wm')
      n.style.left = (b[0] * 100) + '%'
      n.style.top = (b[1] * 100) + '%'
      n.style.width = (b[2] * 100) + '%'
      n.style.height = (b[3] * 100) + '%'
      ui.watermark.appendChild(n)
    }
  })()

  /* 左侧六格阶段柱 + 品牌块下方的小字数据行 + 实时时钟 */
  ;(function slatsAndMeta() {
    for (var i = 0; i < STEPS.length + 1; i++) ui.slats.appendChild(el('i', 'dsu-slat'))
    ui.meta1.textContent = 'REV ' + (window.__DP_VERSION__ || '1.0.0') + ' · WEB PROFILE'
    paintClock()
    clockTimer = setInterval(paintClock, 1000)
  })()

  ;(function reticle() {
    var ns = 'http://www.w3.org/2000/svg'
    var svg = document.createElementNS(ns, 'svg')
    svg.setAttribute('viewBox', '0 0 400 400')
    function arc(cx, cy, r, a0, a1, cls, cap) {
      var rad = function (d) { return (d - 90) * Math.PI / 180 }
      var x0 = cx + r * Math.cos(rad(a0)), y0 = cy + r * Math.sin(rad(a0))
      var x1 = cx + r * Math.cos(rad(a1)), y1 = cy + r * Math.sin(rad(a1))
      var large = (a1 - a0) > 180 ? 1 : 0
      var p = document.createElementNS(ns, 'path')
      p.setAttribute('d', 'M' + x0.toFixed(2) + ' ' + y0.toFixed(2) +
        ' A' + r + ' ' + r + ' 0 ' + large + ' 1 ' + x1.toFixed(2) + ' ' + y1.toFixed(2))
      p.setAttribute('class', cls)
      if (cap) p.setAttribute('stroke-linecap', cap)
      return { node: p, x: x1, y: y1, x0: x0, y0: y0 }
    }
    var gA = document.createElementNS(ns, 'g')
    gA.setAttribute('class', 'dsu-ret-rot-a')
    /* 300° 弧，缺口留在正下方 6 点钟方向：底部字幕永远不会被压到，
       弧末端圆点落在 5 点钟位置，和原片一致。 */
    var a = arc(200, 200, 150, 215, 505, 'dsu-ring-a', 'round')
    gA.appendChild(a.node)
    var da = document.createElementNS(ns, 'circle')
    da.setAttribute('class', 'dsu-dot-a')
    da.setAttribute('cx', a.x.toFixed(2)); da.setAttribute('cy', a.y.toFixed(2)); da.setAttribute('r', '7')
    gA.appendChild(da)
    svg.appendChild(gA)

    var gB = document.createElementNS(ns, 'g')
    gB.setAttribute('class', 'dsu-ret-rot-b')
    var b = arc(200, 200, 104, 200, 490, 'dsu-ring-b', 'round')
    gB.appendChild(b.node)
    var db = document.createElementNS(ns, 'circle')
    db.setAttribute('class', 'dsu-dot-b')
    db.setAttribute('cx', b.x0.toFixed(2)); db.setAttribute('cy', b.y0.toFixed(2)); db.setAttribute('r', '4')
    gB.appendChild(db)
    svg.appendChild(gB)

    var gC = document.createElementNS(ns, 'g')
    var bl = arc(200, 200, 62, 118, 242, 'dsu-bracket', 'round')
    var br = arc(200, 200, 62, 298, 62, 'dsu-bracket', 'round')
    gC.appendChild(bl.node); gC.appendChild(br.node)
    svg.appendChild(gC)

    var pts = [[152, 132], [252, 268], [278, 150]]
    for (var i = 0; i < pts.length; i++) {
      var c = document.createElementNS(ns, 'circle')
      c.setAttribute('class', 'dsu-dot-o')
      c.setAttribute('cx', pts[i][0]); c.setAttribute('cy', pts[i][1]); c.setAttribute('r', '2.8')
      svg.appendChild(c)
    }
    ui.reticle.appendChild(svg)
  })()

  /* ── 时间线引擎 ───────────────────────────────────────────────────────── */
  var timers = []
  var waiters = []
  var skipped = false
  var finished = false
  var hexTimer = null

  function ms(base) { return Math.round(base / C.speed) }

  function wait(base) {
    return new Promise(function (resolve) {
      if (skipped) return resolve()
      var done = false
      function fin() {
        if (done) return
        done = true
        var i = waiters.indexOf(fin)
        if (i >= 0) waiters.splice(i, 1)
        resolve()
      }
      var t = setTimeout(fin, Math.max(0, ms(base)))
      timers.push(t)
      waiters.push(fin)
    })
  }

  function waitAction(step) {
    return new Promise(function (resolve) {
      if (skipped || !C.requireInteraction) return resolve()
      var done = false
      function fin() {
        if (done) return
        done = true
        cleanup()
        resolve()
      }
      function onKey(e) {
        /* 表单弹着的时候键盘归表单——回车属于输入框、空格属于下拉。
           这里是 document 级的监听，不挡的话焦点一离开输入框，
           在下拉上按个空格就把整段动画送走了，而配置还没建 */
        if (ui.form && !ui.form.hidden) return
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') { e.preventDefault(); fin() }
      }
      function onClick(e) {
        e.preventDefault()
        /* 第 1 步：先判是不是首次启动。
           是 → 弹表单，等它填完再继续；不是 → 直接进下一步 */
        if (step && step.action === 'grant' && !hasConfig()) {
          showForm(fin)
          return
        }
        fin()
      }
      function cleanup() {
        ui.btn.removeEventListener('click', onClick)
        ui.action.removeEventListener('click', onClick)
        document.removeEventListener('keydown', onKey)
        var i = waiters.indexOf(fin)
        if (i >= 0) waiters.splice(i, 1)
      }
      ui.btn.addEventListener('click', onClick)
      ui.action.addEventListener('click', onClick)
      document.addEventListener('keydown', onKey)
      waiters.push(fin)
    })
  }

  function releaseAll() {
    for (var i = 0; i < timers.length; i++) clearTimeout(timers[i])
    timers.length = 0
    var list = waiters.slice()
    waiters.length = 0
    for (var j = 0; j < list.length; j++) { try { list[j]() } catch (err) { /* noop */ } }
  }

  function setProgress(p) {
    var pct = Math.max(0, Math.min(1, p))
    ui.bar.style.width = Math.round(pct * 100) + '%'
  }

  /** 六格阶段柱：走过的压暗、当前的拉满并点亮主题橙 */
  function setSlats(active) {
    var items = ui.slats.children
    for (var i = 0; i < items.length; i++) {
      var idx = i + 1
      items[i].classList.toggle('dsu-on', idx === active)
      items[i].classList.toggle('dsu-past', idx < active)
    }
  }

  /** 扫描线自上而下扫一遍（底板洗白后一次，验准时再一次） */
  function sweep() {
    if (!ui.scanline) return
    ui.scanline.classList.remove('dsu-go')
    void ui.scanline.offsetWidth
    ui.scanline.classList.add('dsu-go')
  }

  function paintClock() {
    var d = new Date()
    var pad = function (n) { return (n < 10 ? '0' : '') + n }
    ui.meta2.textContent = pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds())
  }

  function setSubtitle(zh, en) {
    ui.subZh.classList.remove('dsu-in')
    ui.subEn2.classList.remove('dsu-in')
    setTimeout(function () {
      ui.subZh.textContent = zh || ''
      ui.subEn2.textContent = en || ''
      ui.subZh.classList.add('dsu-in')
      if (en) ui.subEn2.classList.add('dsu-in')
    }, ms(140))
  }

  function setStepCount(i, code) {
    var totalSteps = STEPS.length + 1
    ui.stepcount.textContent = '[ ' + String(i).padStart(2, '0') + ' / ' +
      String(totalSteps).padStart(2, '0') + ' ] ' + code
  }

  function startHex() {
    var lines = 12
    function line() {
      var s = ''
      for (var i = 0; i < 26; i++) {
        s += '0123456789ABCDEF'.charAt(Math.floor(Math.random() * 16))
        if (i % 2 === 1) s += ' '
      }
      return s
    }
    function paint() {
      var out = []
      for (var i = 0; i < lines; i++) out.push(line())
      ui.hex.innerHTML = out.join('<br>')
    }
    paint()
    ui.hex.classList.add('dsu-in')
    audio.tickRun()
    hexTimer = setInterval(paint, 110)
  }
  function stopHex() {
    if (hexTimer) { clearInterval(hexTimer); hexTimer = null }
    ui.hex.classList.remove('dsu-in')
  }

  /* ── 声音 ──────────────────────────────────────────────────────────────
   * 两条独立的通道，都不依赖任何音频文件：
   *   audio —— 界面音效，WebAudio 现场合成（咔哒 / 双音确认 / 噪声扫频 / 和声钟）
   *   voice —— 女声播报，Web Speech API 念每一行的英文（照参考片的女声节奏：
   *            7.3-9.3s 念状态行、19.6-21.2s 念 PERMISSION AUTHORIZED）
   * 浏览器策略要求"先有用户手势"，所以第一次点击/按键会补一次解锁 + 补播。 */
  function clamp01(v, lo, hi) {
    var n = Number(v)
    return isFinite(n) ? Math.min(hi, Math.max(lo, n)) : lo
  }

  var audio = (function () {
    var ctx = null
    function ac(force) {
      /* 语音素材要独立于「界面音效」开关：force=true 时无视 C.sound */
      if (!C.sound && !force) return null
      try {
        var AC = window.AudioContext || window.webkitAudioContext
        if (!AC) return null
        if (!ctx) ctx = new AC()
        if (ctx.state === 'suspended' && typeof ctx.resume === 'function') ctx.resume()
        return ctx
      } catch (e) { return null }
    }
    function vol(gain) { return Math.max(0.0002, (gain == null ? 0.05 : gain) * clamp01(C.soundVolume, 0, 1) * 1.6) }
    function tone(freq, dur, type, gain, delay, glideTo) {
      var c = ac(); if (!c) return
      try {
        var t0 = c.currentTime + (delay || 0)
        var o = c.createOscillator(), g = c.createGain()
        o.type = type || 'sine'
        o.frequency.setValueAtTime(freq, t0)
        if (glideTo) o.frequency.exponentialRampToValueAtTime(glideTo, t0 + dur)
        g.gain.setValueAtTime(0.0001, t0)
        g.gain.exponentialRampToValueAtTime(vol(gain), t0 + Math.min(0.02, dur * 0.3))
        g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur)
        o.connect(g); g.connect(c.destination)
        o.start(t0); o.stop(t0 + dur + 0.03)
      } catch (e) { /* 静默降级 */ }
    }
    function noise(dur, gain) {
      var c = ac(); if (!c) return
      try {
        var n = Math.floor(c.sampleRate * dur)
        var buf = c.createBuffer(1, n, c.sampleRate)
        var d = buf.getChannelData(0)
        for (var i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * (1 - i / n)
        var src = c.createBufferSource(); src.buffer = buf
        var f = c.createBiquadFilter(); f.type = 'bandpass'
        f.frequency.value = 1500; f.Q.value = 0.6
        var g = c.createGain(); g.gain.value = vol(gain)
        src.connect(f); f.connect(g); g.connect(c.destination)
        src.start()
      } catch (e) { /* 静默降级 */ }
    }
    /* 拉真素材（原项目那条是 /dsh-startup/asset/，那是 dsh 环境的位置，
       独立宿主要自己指路，所以挪到 C.assetBase 上）；
       拿不到就自动回落到下面合成的音，功能不依赖网络/素材存在与否。 */
    var buffers = {}
    var fetching = {}
    function loadAsset(name) {
      if (C.sfx === 'synth') return
      if (buffers[name] || fetching[name]) return
      fetching[name] = true
      try {
        fetch(C.assetBase + name + '.mp3')
          .then(function (r) { return r.ok ? r.arrayBuffer() : null })
          .then(function (ab) { return ab ? ac().decodeAudioData(ab) : null })
          .then(function (buf) { if (buf) buffers[name] = buf })
          .catch(function () { /* 没素材就走合成音 */ })
      } catch (e) { /* fetch 不存在也一样降级 */ }
    }
    /* 素材预加载：fetch + decodeAudioData 不需要用户手势，所以加载时就拉，
       这样第一步就能用真声，而不用等用户第一次点击。 */
    var pending = {}
    function ensureAsset(name) {
      if (buffers[name]) return Promise.resolve(true)
      if (pending[name]) return pending[name]
      if (C.voiceSource === 'tts') return Promise.resolve(false)
      pending[name] = new Promise(function (resolve) {
        try {
          fetch(C.assetBase + name + '.mp3')
            .then(function (r) { return r.ok ? r.arrayBuffer() : null })
            .then(function (ab) { if (!ab) return null; return ac(true).decodeAudioData(ab) })
            .then(function (buf) {
              if (buf) { buffers[name] = buf; resolve(true) } else { resolve(false) }
            })
            .catch(function () { resolve(false) })
        } catch (e) { resolve(false) }
      })
      return pending[name]
    }

    /** 播素材并等它播完，resolve 实际时长(ms)。拿不到素材 resolve 0。 */
    function playAssetAndWait(name, gain) {
      return new Promise(function (resolve) {
        var c = ac(true)
        var buf = buffers[name]
        if (!c || !buf) { resolve(0); return }
        try {
          var src = c.createBufferSource()
          src.buffer = buf
          var g = c.createGain()
          g.gain.value = Math.min(1, (gain == null ? 0.85 : gain) * clamp01(C.voiceVolume, 0, 1) * 0.85)
          src.connect(g); g.connect(c.destination)
          src.onended = function () { resolve(Math.round(buf.duration * 1000)) }
          src.start()
        } catch (e) { resolve(0) }
      })
    }

    function playAsset(name, gain) {
      var c = ac(); if (!c) return false
      var buf = buffers[name]
      if (!buf) { loadAsset(name); return false }
      try {
        var src = c.createBufferSource()
        src.buffer = buf
        var g = c.createGain()
        g.gain.value = Math.min(1, (gain == null ? 0.55 : gain) * clamp01(C.soundVolume, 0, 1) * 1.6)
        src.connect(g); g.connect(c.destination)
        src.start()
        return true
      } catch (e) { return false }
    }

    return {
      resume: function () { ac(); loadAsset('sfx-tick'); loadAsset('sfx-ticks-run') },
      preload: function () { loadAsset('sfx-tick'); loadAsset('sfx-ticks-run') },
      ensureAsset: ensureAsset,
      playAssetAndWait: playAssetAndWait,
      /* 文字渐显 / 阶段推进 / 按钮确认 —— 优先用真素材 */
      /* tick() 删了。它是参考项目给"打字机"准备的，但在它原版里就从没被调用过
         （typeIn 只设 transitionDelay，不发声；别处也不调），是个死函数。
         我们确认过不要打字机音效，所以不留这个钩子。
         哪天要加：把 tone(1760, 0.035, 'square', 0.022) 按 stagger 挂进 typeIn。 */
      confirm: function () { if (!playAsset('sfx-tick', 0.85)) { tone(660, 0.09, 'triangle', 0.07); tone(990, 0.17, 'triangle', 0.055, 0.085) } },
      /* 六边形乱码那一段的"数据流"声。原版这一条【只挂素材、没有合成兜底】，
         所以切成 synth 之后它整个哑掉——素材拿不到就是什么都不放。
         合成版是十几声极短的高频点，30ms 一响，密度就是"乱码在滚"的感觉；
         三个频率轮着来，免得听起来像节拍器。 */
      tickRun: function () {
        if (playAsset('sfx-ticks-run', 0.5)) return
        for (var i = 0; i < 14; i++) {
          tone(2600 + (i % 3) * 340, 0.012, 'square', 0.009, i * 0.03)
        }
      },
      step: function () { if (!playAsset('sfx-tick', 0.6)) { tone(880, 0.05, 'sine', 0.05); tone(1320, 0.07, 'sine', 0.028, 0.045) } },
      hover: function () { tone(2200, 0.02, 'sine', 0.018) },
      sweep: function () { noise(0.75, 0.035) },
      /* 念台词之前的两声轻提示：这一笔让 TTS 从"浏览器念字"变成"系统播报" */
      cue: function () { tone(1046.5, 0.05, 'sine', 0.028); tone(1568, 0.06, 'sine', 0.02, 0.40) },
      rise: function () { tone(220, 1.1, 'sine', 0.032, 0, 990) },
      /* 视觉扫光那一带的"咻"：高频扫下来，底下垫一层短气声。
         这一带原本完全无声——原来那声 sweep 被挂在 760ms 之后的白幕上了 */
      swish: function () {
        tone(2800, 0.34, 'sine', 0.028, 0, 380)
        noise(0.22, 0.02)
      },
      /* 收紧爆散那一带的碎裂：一下干噪声 + 四颗错开的高频碎片。
         用方波是因为它更脆；音量压得低——它是"崩开"，不是"敲锣" */
      shatter: function () {
        noise(0.16, 0.05)
        tone(2400, 0.05, 'square', 0.016, 0)
        tone(3100, 0.04, 'square', 0.013, 0.035)
        tone(1850, 0.06, 'square', 0.012, 0.07)
        tone(4200, 0.035, 'square', 0.010, 0.11)
      },
      chime: function () {
        tone(659.25, 0.9, 'sine', 0.055)
        tone(830.61, 0.9, 'sine', 0.04, 0.09)
        tone(987.77, 1.3, 'sine', 0.045, 0.18)
      }
    }
  })()

  var voice = (function () {
    var supported = typeof window !== 'undefined' && !!window.speechSynthesis &&
      typeof window.SpeechSynthesisUtterance === 'function'
    var voices = []
    var picked = { en: null, zh: null }
    var meter = null
    var saidOnce = false
    var pending = { en: '', zh: '' }

    /* 想让它听起来像"AI 播报"，音色本身比什么都重要。
       同一台机器上，"Microsoft Zira Desktop" 是上世纪拼接合成，念长句塑料味很重；
       Edge 的 "... Online (Natural)"、Chrome 的 "Google ..."、macOS 的 Siri 才是神经网络音色。
       所以这里按分数挑，而不是挨个名字第一个命中。 */
    var NATURAL_HINTS = ['natural', 'neural', 'online', 'premium', 'enhanced', 'siri', 'google']
    var FEMALE_HINTS = [
      'aria', 'jenny', 'michelle', 'emma', 'ava', 'libby', 'sonia', 'maisie',
      'zira', 'samantha', 'karen', 'moira', 'tessa', 'victoria', 'serena', 'allison',
      'susan', 'fiona', 'hazel', 'female', 'woman',
      'xiaoxiao', 'xiaoyi', 'xiaomo', 'huihui', 'yaoyao', '晓晓', '晓伊', '女声'
    ]
    var MALE_HINTS = ['david', 'mark', 'guy', 'ryan', 'george', 'daniel', 'alex', 'fred',
      'male', 'yunxi', 'yunjian', 'kangkang']

    /** 给一个音色打分：神经网络 > 女声 > 语种吻合 > 本地 */
    function score(v, want) {
      var name = String(v.name || '').toLowerCase()
      var lang = String(v.lang || '').toLowerCase()
      var sc = 0
      for (var i = 0; i < NATURAL_HINTS.length; i++) {
        if (name.indexOf(NATURAL_HINTS[i]) !== -1) { sc += 60; break }
      }
      for (var j = 0; j < FEMALE_HINTS.length; j++) {
        if (name.indexOf(FEMALE_HINTS[j]) !== -1) { sc += 40; break }
      }
      for (var k = 0; k < MALE_HINTS.length; k++) {
        if (name.indexOf(MALE_HINTS[k]) !== -1) { sc -= 45; break }
      }
      if (lang.indexOf(want) === 0) sc += 25
      if (v.localService) sc += 4          /* 本地音色起播快，不会先卡半秒 */
      if (v.default) sc += 3
      return sc
    }

    /** 挑某语种最合适的一个音色（want 传 'en' / 'zh' 这样的两字母前缀） */
    function bestFor(want) {
      if (!voices.length) return null
      if (C.voiceName) {
        for (var i = 0; i < voices.length; i++) {
          var v = voices[i]
          if (v.name === C.voiceName && String(v.lang || '').toLowerCase().indexOf(want) === 0) return v
        }
      }
      var pool = []
      for (var j = 0; j < voices.length; j++) {
        if (String(voices[j].lang || '').toLowerCase().indexOf(want) === 0) pool.push(voices[j])
      }
      if (!pool.length) pool = voices.slice()
      var best = null
      var bs = -1e9
      for (var n = 0; n < pool.length; n++) {
        var sc = score(pool[n], want)
        if (sc > bs) { bs = sc; best = pool[n] }
      }
      return best
    }

    function setMeter(on) { if (meter) meter.classList.toggle('dsu-on', !!on) }

    function load() {
      if (!supported) return
      try { voices = window.speechSynthesis.getVoices() || [] } catch (e) { voices = [] }
      picked.en = bestFor('en')
      picked.zh = bestFor('zh')
    }

    /** 全大写名字有些引擎会一个字母一个字母念，转成 Title Case 更像在叫名字 */
    function spokenName(name) {
      return String(name || '').replace(/\S+/g, function (w) {
        return (/^[A-Z0-9.\-]+$/.test(w) && w.length > 1) ? w.charAt(0) + w.slice(1).toLowerCase() : w
      })
    }

    function utter(text, lang) {
      try {
        var u = new window.SpeechSynthesisUtterance(text)
        var v = lang.indexOf('zh') === 0 ? picked.zh : picked.en
        if (v) { u.voice = v; u.lang = v.lang || lang } else u.lang = lang
        /* 神经网络音色在 .95 / 1.02 这个档位最像"系统在播报"：
           再快就赶，再慢就假；音调略抬一点显得干净利落 */
        u.rate = clamp01(C.voiceRate, 0.5, 2)
        u.pitch = clamp01(C.voicePitch, 0, 2)
        u.volume = clamp01(C.voiceVolume, 0, 1)
        u.onstart = function () { setMeter(true) }
        u.onend = function () { setMeter(false) }
        u.onerror = function () { setMeter(false) }
        window.speechSynthesis.speak(u)
        return true
      } catch (e) { return false }
    }

    /** 一句话的时长估算（个别引擎不触发 onend 时兜底；中文按字、英文按字符） */
    function estimateMs(items) {
      var chars = 0
      var rate = clamp01(C.voiceRate, 0.5, 2) || 1
      for (var i = 0; i < items.length; i++) {
        var t = String(items[i].t || '')
        chars += /[\u4e00-\u9fa5]/.test(t) ? t.length * 1.7 : t.length
      }
      return Math.round((chars / 13) * 1000 / rate) + 460
    }

    function buildUtter(text, lang) {
      var u = new window.SpeechSynthesisUtterance(text)
      var v = lang.indexOf('zh') === 0 ? picked.zh : picked.en
      if (v) { u.voice = v; u.lang = v.lang || lang } else u.lang = lang
      u.rate = clamp01(C.voiceRate, 0.5, 2)
      u.pitch = clamp01(C.voicePitch, 0, 2)
      u.volume = clamp01(C.voiceVolume, 0, 1)
      return u
    }

    return {
      supported: supported,
      load: load,
      attach: function (node) { meter = node },

      /**
       * 念一行，返回"这一行实际花了多久(ms)"的 Promise。
       *
       * 三个关键决定：
       *  - **不 cancel 上一句**。原来每步都 cancel，用户点快一点、或者
       *    hold 短于台词长度，语音就被硬生生掐断 —— 那正是要避免的。
       *    speechSynthesis 本身是队列，不 cancel 就是顺序播报。
       *  - 提示音响过之后留 `voiceLead` 的空白再开口，这是旁白的呼吸感。
       *  - 等 `onend` 才 resolve，动画据此决定这一步停多久；个别引擎不触发
       *    onend 时按估算兜底，绝不把动画卡死。
       */
      line: function (en, zh, asset, lead) {
        /* 有真声素材就优先用素材（音色就是你给的那个）；拿不到再回落 TTS */
        if (asset && C.voice && C.voiceSource !== 'tts' && !finished) {
          return audio.ensureAsset(asset).then(function (ok) {
            if (!ok || finished) return 0
            if (C.voiceCue !== false) audio.cue()
            return audio.playAssetAndWait(asset, 0.85).then(function (ms) {
              if (ms > 0) setMeter(true)
              return ms
            })
          }).then(function (ms) {
            if (ms > 0) { saidOnce = true; return ms }
            return ttsLine(en, zh, lead)
          })
        }
        return ttsLine(en, zh, lead)
      },

      /** TTS 路径：素材缺失 / voiceSource=tts / 终幕那条动态名字 */
      tts: function (en, zh) { return ttsLine(en, zh) },

      /** 不等待的版本：设置页试听 / 任何"念完就行"的场合 */
      say: function (en, zh) { return this.line(en, zh) },

      /** 浏览器要求"先有用户手势"才放声：第一次点击/按键解锁 + 补播当前行 */
      unlock: function () {
        try { if (supported) window.speechSynthesis.resume() } catch (e) {}
        audio.resume()
        /* 预热：先无声念一个空格，把引擎唤醒，避免第一句被吃掉开头半个字 */
        if (supported && !saidOnce) {
          try {
            var w = new window.SpeechSynthesisUtterance(' ')
            w.volume = 0
            var v = picked.en || picked.zh
            if (v) { w.voice = v; w.lang = v.lang }
            window.speechSynthesis.speak(w)
          } catch (e) { /* noop */ }
        }
        if (!saidOnce && C.voice && (pending.en || pending.zh)) this.say(pending.en, pending.zh)
      },
      speakName: spokenName,
      current: function () {
        var a = picked.en ? picked.en.name : ''
        var b = picked.zh ? picked.zh.name : ''
        return a === b ? a : (a + (b ? '  /  ' + b : ''))
      },
      listVoices: function () { return voices.slice() },
      /** 只有这里才真的掐断语音（跳过 / 揭幕） */
      stop: function () { try { if (supported) window.speechSynthesis.cancel() } catch (e) {} setMeter(false) }
    }

    /** TTS 合成并等它念完，resolve 实际时长(ms)；拿不到引擎时 resolve 0。
     *  lead 是单句覆盖：不传就吃全局 C.voiceLead。 */
    function ttsLine(en, zh, leadOverride) {
      return new Promise(function (resolve) {
        if (!supported || !C.voice || finished) { resolve(0); return }
        pending = { en: en || '', zh: zh || '' }
        var items = []
        var mode = C.voiceLang
        if (mode === 'zh') { if (zh) items.push({ t: zh, l: 'zh-CN' }) }
        else if (mode === 'both') {
          if (zh) items.push({ t: zh, l: 'zh-CN' })
          if (en) items.push({ t: en, l: 'en-US' })
        } else if (en) { items.push({ t: en, l: 'en-US' }) }
        if (!items.length) { resolve(0); return }

        saidOnce = true
        if (C.voiceCue !== false) audio.cue()

        var startedAt = Date.now()
        var est = estimateMs(items)
        /* 单句覆盖优先。注意 clamp 的下界是 0 —— 留白只能减到"立刻开口"，
           再往前就得从别处挪（动画的入点），那就不只是语音的事了 */
        var lead = clamp01(leadOverride == null ? C.voiceLead : leadOverride, 0, 1200)
        var settled = false
        var watchdog = null

        function settle() {
          if (settled) return
          settled = true
          if (watchdog) clearTimeout(watchdog)
          setMeter(false)
          resolve(Math.max(0, Date.now() - startedAt))
        }

        setTimeout(function () {
          if (finished) { settle(); return }
          var last = items.length - 1
          for (var i = 0; i <= last; i++) {
            var u = buildUtter(items[i].t, items[i].l)
            if (i === last) {
              u.onstart = function () { setMeter(true) }
              u.onend = settle
              u.onerror = settle
            }
            try { window.speechSynthesis.speak(u) } catch (e) { if (i === last) settle() }
          }
          watchdog = setTimeout(settle, est + 900)
        }, lead)
      })
    }
  })()

  /* 语音/音效接线：声卡要等用户手势才能出声，这里挂一次性解锁 */
  voice.attach(q('.dsu-voice'))
  ;(function preloadVoices() {
    if (C.voiceSource === 'tts') return
    for (var i = 0; i < STEPS.length; i++) if (STEPS[i].audio) audio.ensureAsset(STEPS[i].audio)
    audio.ensureAsset('line-6')   /* 终幕欢迎语 */
  })()
  ;(function wireSound() {
    voice.load()
    if (voice.supported && typeof window.speechSynthesis.addEventListener === 'function') {
      try { window.speechSynthesis.addEventListener('voiceschanged', function () { voice.load() }) } catch (e) {}
    }
    var unlocked = false
    function unlock() {
      if (unlocked) return
      unlocked = true
      voice.unlock()
      document.removeEventListener('pointerdown', unlock, true)
      document.removeEventListener('keydown', unlock, true)
      document.removeEventListener('touchstart', unlock, true)
    }
    document.addEventListener('pointerdown', unlock, true)
    document.addEventListener('keydown', unlock, true)
    document.addEventListener('touchstart', unlock, true)
  })()

  /* ── 时间线 ───────────────────────────────────────────────────────────── */
  function run() {
    return Promise.resolve()
      /* 第一幕：黑幕 --> DeepSeek 标识 */
      .then(function () { return wait(820) })
      .then(function () {
        ui.blackInner.classList.add('dsu-in')
        /* audio.rise()  -- 本轮试听暂时摘掉，恢复只要去掉这行注释 */
        return wait(240)
      })
      .then(function () {
        /* 收紧的一瞬间：粒子从中心炸开，整块轻震一下 */
        burstParticles()
        audio.shatter()
        ui.blackInner.classList.add('dsu-shake')
        ui.blackEn.classList.add('dsu-tighten')
        return wait(880)
      })
      .then(function () {
        ui.sweep.classList.add('dsu-go')
        /* 音效和白带同起同落：这一声从白幕段挪到了这里。
           白带本身被宿主页的样式压到 750ms（见 scene-1b.html），
           和 noise(0.75) 对齐 —— 谁先结束都会读成两件事 */
        audio.sweep()
        return wait(750)
      })
      /* 过场：过曝洗白 */
      .then(function () {
        ui.blackInner.classList.add('dsu-out')
        ui.wash.style.transition = 'opacity ' + ms(220) + 'ms linear'
        ui.wash.style.opacity = '1'
        return wait(260)
      })
      .then(function () {
        ui.plate.style.transition = 'opacity ' + ms(900) + 'ms ease'
        ui.plate.style.opacity = '1'
        ui.watermark.style.transition = 'opacity ' + ms(1100) + 'ms ease'
        ui.watermark.style.opacity = '1'
        ui.wash.style.transition = 'opacity ' + ms(720) + 'ms cubic-bezier(.2,.9,.2,1)'
        ui.wash.style.opacity = '0'
        ui.black.style.transition = 'opacity ' + ms(720) + 'ms ease'
        ui.black.style.opacity = '0'
        return wait(760)
      })
      /* 第二幕：品牌块 / 页脚 / 进度条 */
      .then(function () {
        ui.brand.classList.add('dsu-in')
        ui.foot.classList.add('dsu-in')
        ui.stepcount.classList.add('dsu-in')
        ui.idline.classList.add('dsu-in')
        ui.frame.classList.add('dsu-in')
        ui.slats.classList.add('dsu-in')
        ui.meta.classList.add('dsu-in')
        ui.vignette.classList.add('dsu-in')
        ui.voice.classList.add('dsu-in')
        setProgress(0.12)
        setStepCount(0, 'BOOT')
        setSlats(0)
        setSubtitle('系统自检中…', 'SYSTEM SELF-CHECK')
        /* 首次启动不给跳过。config.yaml 还没建，跳过去进到应用里
           每个功能都会报错——那比不跳更糟。填完表单后 hasConfig()
           就是 true 了，SKIP 会跟着出现 */
        if (C.allowSkip && hasConfig()) ui.skip.classList.add('dsu-in')
        /* 原来是 700ms 的干等：这一段画面是静的，声音也是静的，
           于是第一句人声要等到 4.9s 才开口，前面空得太久。
           压到 160ms（80 的倍数）——洗白一收，第一句就跟上。
           第二幕的入场过渡和 stepLoop 叠着走，不冲突。 */
        return wait(160)
      })
      .then(function () { ui.black.style.display = 'none'; sweep() })
      /* 六个阶段 */
      .then(function () { return stepLoop() })
      /* 终幕 */
      .then(function () { return finale() })
      .catch(function (err) {
        try { console.warn('[dsh-startup-screen] 动画异常，直接揭幕：', err) } catch (e2) {}
        return finish()
      })
  }

  function stepLoop() {
    var chain = Promise.resolve()
    STEPS.forEach(function (step, i) {
      chain = chain.then(function () {
        if (finished) return
        var n = i + 1
        setStepCount(n, step.badge)
        setSlats(n)
        setProgress(step.progress)
        setSubtitle(step.log, step.logEn)
        audio.step()
        /* 语音在这里起头，但**不阻塞**下面的文字渐显 —— 两者同时发生。
           第一句给单独的留白：它前面是静场，不需要"呼吸"，
           而它又是整段里唯一一句"等着被听见"的话。 */
        var spoke = voice.line(
          step.say, step.zh, step.audio,
          i === 0 ? C.voiceLeadFirst : null
        )

        ui.status.classList.toggle('dsu-zhline', true)
        /* 先摘掉 dsu-in 并强制一次样式计算，新的逐字 span 才会重新走渐显动画 */
        ui.status.classList.remove('dsu-in')
        ui.subEn.classList.remove('dsu-in')
        void ui.status.offsetWidth
        typeIn(ui.statusZh, step.zh, 46)
        typeIn(ui.subEn, step.en, 13)
        ui.caret.classList.toggle('dsu-on', !!step.action && step.action !== 'auto')
        requestAnimationFrame(function () {
          if (finished) return
          ui.status.classList.add('dsu-in')
          ui.subEn.classList.add('dsu-in')
        })
        ui.rule.classList.add('dsu-in')

        if (step.assembleLogo) assembleLogo()
        if (step.reticle) {
          /* 照原片：准星出现时中央只留状态字，归墟标记和虚线收掉，别挤成一团 */
          ui.logo.classList.remove('dsu-in')
          ui.dots.hidden = true
          ui.reticle.classList.add('dsu-in')
          sweep()
        }
        if (step.hex) startHex()

        /* 这一步停多久 = max(视觉基准, 实际播报时长 + 收尾留白) —— 台词长就多停，
           台词短也不会干等。用户点得快时同样等这一句念完，不掐断。 */
        function holdFor(spoken) {
          var target = Math.max(ms(step.hold), (spoken || 0) + ms(240))
          return wait(Math.max(0, target - (spoken || 0)))
        }

        if (step.action === 'grant' || step.action === 'confirm') {
          showAction(step)
          return wait(520).then(function () { return waitAction(step) }).then(function () {
            hideAction()
            audio.confirm()
            ui.caret.classList.remove('dsu-on')
            return spoke
          }).then(function () { return wait(ms(320)) })
        }
        if (step.hex) {
          return spoke.then(holdFor).then(function () { stopHex() })
        }
        return spoke.then(holdFor)
      })
    })
    return chain
  }

  function assembleLogo() {
    ui.logo.classList.add('dsu-in')
    ui.dots.hidden = false
    var path = ui.logo.querySelector('path')
    if (path && typeof path.getTotalLength === 'function') {
      try {
        var len = path.getTotalLength()
        path.style.fill = 'none'
        path.style.stroke = 'currentColor'
        path.style.strokeWidth = '1.1'
        path.style.strokeDasharray = len
        path.style.strokeDashoffset = len
        /* 参考片的"一笔画成"：先勾线，再落墨成面 */
        path.animate(
          [{ strokeDashoffset: len }, { strokeDashoffset: 0 }],
          { duration: ms(1400), easing: 'cubic-bezier(.55,.06,.24,1)', fill: 'forwards' }
        )
        setTimeout(function () {
          path.style.transition = 'fill ' + ms(420) + 'ms ease, stroke-width ' + ms(420) + 'ms ease'
          path.style.fill = ''
          path.style.strokeWidth = '0'
        }, ms(1450))
      } catch (err) { /* Web Animations 不可用时直接落墨 */ }
    }
    return wait(300)
  }

  function showAction(step) {
    ui.btnZh.textContent = step.btnZh
    ui.btnEn.textContent = step.btnEn
    ui.card.hidden = step.action !== 'confirm'
    if (step.action === 'confirm') {
      ui.card.innerHTML = ''
      /* 纯中文标签 + 数字/名称，去掉英文双写与主机行，别堆信息 */
      var rows = [
        ['身份名称', C.identity, true],
        ['身份编号', C.identityId, false],
        ['权限等级', C.accessLevel, false]
      ]
      rows.forEach(function (r) {
        var row = el('div', 'dsu-card-row')
        row.appendChild(el('span', null, r[0]))
        row.appendChild(el('b', r[2] ? 'dsu-zhname' : null, r[1]))
        ui.card.appendChild(row)
      })
    }
    /* 第 1 步照常显示按钮，不主动弹表单。
       要不要引导式初始化，等用户点了「授予访问权限」再判 ——
       这样按钮的语义才对：点击 = 同意授权，那就得给凭证。
       一露脸就弹表单，是用户还没做任何动作就被塞了个东西 */
    ui.form.hidden = true
    root.classList.remove('dsu-form-open')
    ui.btn.hidden = false
    ui.hint.innerHTML = '按 <kbd>Enter</kbd> / <kbd>Space</kbd>，或点击按钮继续'
    ui.action.classList.add('dsu-in')
    ui.btn.classList.add('dsu-pulse')
  }

  /* 弹配置表单。done 是"填完之后继续动画"的回调，
     由 waitAction 在用户点按钮时传进来 */
  var formDone = null

  function showForm(done) {
    formDone = done || null
    syncCustom()
    ui.formErr.hidden = true
    ui.formBtn.disabled = false
    ui.form.hidden = false
    /* 表单在的时候，中央那行大字让位 —— 不然它被表单截成两半 */
    root.classList.add('dsu-form-open')
    /* 两个「继续」会让人不知道该点哪个：表单里那个才是此刻该点的 */
    ui.btn.hidden = true
    ui.hint.innerHTML = '填完按 <kbd>Enter</kbd>，或点「验证并接入」'
    setTimeout(function () { ui.form.classList.add('dsu-in') }, 40)
    setTimeout(function () { ui.formInp.focus() }, 360)
    loadProviders()
  }

  function finishForm() {
    var d = formDone
    formDone = null
    ui.form.classList.remove('dsu-in')
    setTimeout(function () { ui.form.hidden = true }, 300)
    root.classList.remove('dsu-form-open')
    if (d) d()
  }

  /* ---------- 首次启动的配置表单 ---------- */

  /* 判断是不是首次启动。后端在页面里注入 window.__DP_CONFIGURED__，
     拿不到就当作没有配置——宁可多问一次，也不要让用户进到应用里
     才发现每个功能都报错。 */
  function hasConfig() {
    return window.__DP_CONFIGURED__ === true
  }

  /* 供应商预设，从 /settings/providers 拉（17 家）。
     每项带 id / name / base_url / models / env ——
     env 是密钥的环境变量名，每家都不一样，落盘时要按它来。 */
  var PROVIDERS = {}
  var providersLoaded = false
  var CUSTOM_ID = '__custom__'

  function loadProviders() {
    if (providersLoaded) return Promise.resolve()
    return fetch('/settings/providers')
      .then(function (r) { return r.json() })
      .then(function (j) {
        var list = (j && j.providers) || []
        if (!list.length) return
        var sel = ui.formProvider
        sel.innerHTML = ''
        list.forEach(function (p) {
          PROVIDERS[p.id] = p
          var o = document.createElement('option')
          o.value = p.id
          o.textContent = p.name
          sel.appendChild(o)
        })
        var c = document.createElement('option')
        c.value = CUSTOM_ID
        c.textContent = '自定义 OpenAI 兼容接口'
        sel.appendChild(c)
        providersLoaded = true
      })
      .catch(function () { /* 拉不到就留「载入中…」，用户自己会重开 */ })
  }

  function providerOf(id) { return PROVIDERS[id] || null }
  function isCustom() { return formVal('provider') === CUSTOM_ID }

  /* 地址：自定义的问用户，预设的查表 */
  function baseUrlFor() {
    if (isCustom()) return formVal('base_url')
    var p = providerOf(formVal('provider'))
    return p ? p.base_url : ''
  }

  /* 表单里的控件有 select 也有 input，取值统一走这里，
     免得每加一个字段就要多写一处 querySelector */
  function formVal(k) {
    var el = root.querySelector('.dsu-form [data-k="' + k + '"]')
    return el ? String(el.value || '').trim() : ''
  }

  /* 选了自定义供应商，才需要填接口地址。
     预设供应商的地址是已知的——让用户填是给他出题 */
  function syncCustom() {
    var row = root.querySelector('.dsu-ff[data-only="custom"]')
    if (row) row.hidden = !isCustom()
  }

  function formErr(msg) {
    ui.formErr.textContent = msg || ''
    ui.formErr.hidden = !msg
  }

  /* ── 拉模型列表 ──────────────────────────────────────────────────
     模型名是客观存在的，让用户手打等于让他去翻文档。
     密钥填完就自动去问端点要一份列表 —— 拉到了顺带说明 key 是通的，
     验证和取列表本来就是一回事。
     拉不到不当错误：不是所有家都实现了 /models，那时他还能自己填。 */
  var pulling = false

  function setModelState(txt, bad) {
    var s = root.querySelector('.dsu-ff-state')
    if (!s) return
    s.textContent = txt || ''
    s.classList.toggle('bad', !!bad)
  }

  function fillModels(models) {
    var menu = q('.dsu-model-menu')
    if (!menu) return
    menu.innerHTML = ''
    models.forEach(function (m) {
      var o = document.createElement('div')
      o.className = 'dsu-model-opt'
      o.setAttribute('role', 'option')
      o.textContent = m
      o.addEventListener('click', function () {
        var inp = q('.dsu-form [data-k="model"]')
        if (inp) inp.value = m
        menu.hidden = true
      })
      menu.appendChild(o)
    })
    setModelState(models.length + ' 个可选')
    /* 不预填第一个模型：留空 + placeholder，用户点下拉才看到完整列表；
       想用第一个，选一下就行，省得"预填后列表像被过滤了"。 */
    var inp = q('.dsu-form [data-k="model"]')
    if (inp) {
      inp.placeholder = '从 ' + models.length + ' 个模型里选，或直接输入'
      if (!inp.value) inp.value = ''
    }
  }

  function pullModels() {
    var provId = formVal('provider')
    var custom = isCustom()
    var baseUrl = custom ? formVal('base_url') : ''
    var key = formVal('key')
    if (!provId || !key || pulling) return
    if (custom && !baseUrl) return

    /* 预设里本来就带一份模型清单 —— 先铺上，让用户马上能选。
       再去问端点要真的：拉到了替换掉（可能更新），
       拉不到就留着预设那份（不是所有家都实现了 /models） */
    var preset = providerOf(provId)
    if (preset && preset.models && preset.models.length) fillModels(preset.models)

    pulling = true
    setModelState('核对中…')
    fetch('/settings/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: custom ? null : provId,
        base_url: baseUrl,
        key: key
      })
    })
      .then(function (r) { return r.json().catch(function () { return {} }) })
      .then(function (j) {
        pulling = false
        if (j && j.ok && (j.models || []).length) {
          fillModels(j.models)
          return
        }
        /* 拉不到不算失败：预设那份还在，用户照样能选 */
        setModelState(preset && preset.models ? preset.models.length + ' 个（预设）' : '取不到模型列表',
          !(preset && preset.models))
      })
      .catch(function () {
        pulling = false
        setModelState('连不上后端服务', true)
      })
  }

  function submitForm() {
    var provId = formVal('provider')
    var custom = isCustom()
    var key = formVal('key')
    var model = formVal('model')
    var baseUrl = baseUrlFor()

    if (!provId) {
      formErr('供应商列表还没载入完，稍等一下')
      return
    }
    if (custom && !baseUrl) {
      formErr('自定义接口要填接口地址')
      root.querySelector('.dsu-form [data-k="base_url"]').focus()
      return
    }
    if (!key) {
      formErr('请填入 API 密钥')
      ui.formInp.focus()
      return
    }
    if (!model) {
      formErr('请选择或填入模型名')
      root.querySelector('.dsu-form [data-k="model"]').focus()
      return
    }

    ui.formBtn.disabled = true
    formErr('')

    /* 先测再存。测连接那个接口本来就是为「未保存的表单值」准备的，
       所以这一步不会把没验证过的配置写进库。
       存一个连不通的 key，等于给用户埋一个"为什么什么都不工作"的雷。 */
    fetch('/settings/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: custom ? null : provId,
        base_url: baseUrl,
        model: model,
        key: key
      })
    })
      .then(function (r) {
        return r.json().catch(function () { return {} }).then(function (j) {
          return { ok: r.ok, body: j }
        })
      })
      .then(function (res) {
        if (!res.ok || res.body.ok === false) {
          formErr(res.body.detail || res.body.message || '密钥无效或网络不通')
          ui.formBtn.disabled = false
          return null
        }
        /* 模型配置现在是一张卡片（configs.json），不是 config.yaml
           的 llm 段。首次启动要建卡 + 激活，否则后面自动重建的 LLM
           拿到的还是一张空配置。 */
        return fetch('/configs', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: '默认配置',
            provider: custom ? null : provId,
            base_url: baseUrl,
            model: model,
            key: key
          })
        }).then(function (r) {
          return r.json().catch(function () { return {} }).then(function (j) {
            return { ok: r.ok, body: j }
          })
        }).then(function (r) {
          if (!r.ok || !r.body.config) {
            formErr(r.body.detail || '配置写入失败')
            ui.formBtn.disabled = false
            return null
          }
          return fetch('/configs/' + r.body.config.id + '/activate', {
            method: 'POST'
          }).then(function (r2) {
            if (!r2.ok) {
              formErr('配置已创建，但激活失败')
              ui.formBtn.disabled = false
              return null
            }
            return true
          })
        })
      })
      .then(function (ok) {
        if (!ok) return
        /* 存好并激活才放行。hasConfig() 这时读到的已经是带
           base_url + model 的活动卡，动画从第 2 步接着往下走 */
        window.__DP_CONFIGURED__ = true
        finishForm()
      })
      .catch(function () {
        formErr('连不上后端服务')
        ui.formBtn.disabled = false
      })
  }

  function hideAction() {
    ui.action.classList.remove('dsu-in')
    ui.btn.classList.remove('dsu-pulse')
    root.classList.remove('dsu-form-open')
  }

  function finale() {
    if (finished) return Promise.resolve()
    setStepCount(6, 'WELCOME')
    setSlats(6)
    setProgress(1)
    /* 底部日志和终幕里的「欢迎 xxx 访问」区分开，避免同一句出现两遍 */
    setSubtitle('身份验证完成，会话已建立', 'IDENTITY VERIFIED · SESSION ESTABLISHED')
    audio.chime()
    /* 终幕欢迎语，走 line-6 素材（导出的就是 "Welcome, Operator."）。
       这里的文本只有【回落 TTS】时才用得上，所以要和那个 mp3 逐字对齐 ——
       名字过一遍 speakName：C.identity 是全大写的 OPERATOR，
       派给 TTS 前转成 Title Case，读出来才和录音里一样是个词而不是一串字母。
       身份名在这里是【角色名】（操作者），不是人名，所以固定文案不会错。 */
    var welcome = voice.line(
      'Welcome, ' + voice.speakName(C.identity) + '.',
      '欢迎 ' + C.identity + ' 访问',
      'line-6'
    )

    ui.status.classList.remove('dsu-in')
    ui.subEn.classList.remove('dsu-in')
    ui.rule.classList.remove('dsu-in')
    ui.reticle.classList.remove('dsu-in')
    stopHex()
    /* 中央区（状态行/分隔线/归墟标记/虚线）整体退场：不清掉会和 WELCOME 版式叠字 */
    ui.center.classList.add('dsu-off')
    ui.dots.hidden = true

    return wait(360)
      .then(function () {
        ui.welcome.classList.add('dsu-in')
        ui.idline.classList.remove('dsu-in')
        return wait(420)
      })
      .then(function () {
        /* 结尾色散故障：分片位移 + 0.5px 模糊 + 混合模式，读起来像镜头色散 */
        var targets = [ui.w1, ui.w2, ui.w4]
        targets.forEach(function (t) {
          t.classList.add('dsu-glitch')
          t.setAttribute('data-text', t.textContent)
        })
        ui.w2.classList.add('dsu-glitch-box')   /* 黑底白字那块换加色混合 */
        void ui.welcome.offsetWidth
        targets.forEach(function (t) { t.classList.add('dsu-on') })
        return wait(640)
      })
      /* 光晕从中心炸开 + 变形光条横扫 + 文字青色 halation */
      .then(function () {
        root.classList.add('dsu-peak')
        ui.bloom.classList.add('dsu-go')
        ui.streak.classList.add('dsu-go')
        return wait(430)
      })
      /* 光晕最亮那一下补一记极短高光（是"眨一下"，不是长时间糊白） */
      .then(function () {
        ui.flash.style.transition = 'opacity ' + ms(70) + 'ms linear'
        ui.flash.style.opacity = '0.72'
        return wait(90)
      })
      .then(function () {
        ui.flash.style.transition = 'opacity ' + ms(340) + 'ms cubic-bezier(0.4, 0, 0.2, 1)'
        ui.flash.style.opacity = '0'
        return wait(320)
      })
      /* 欢迎语没播完就不揭幕（素材缺失时这个 Promise 立刻 resolve，不影响节奏） */
      .then(function () { return welcome })
      /* 揭幕：整个机位后撤 + 轻微失焦，比单纯淡出更有镜头感 */
      .then(function () {
        root.classList.add('dsu-handoff')
        return wait(780)
      })
      .then(function () { return finish() })
  }

  function finish() {
    if (finished) return
    finished = true
    releaseAll()
    stopHex()
    voice.stop()
    if (clockTimer) { clearInterval(clockTimer); clockTimer = null }
    try {
      if (C.mode === 'session') window.sessionStorage.setItem('dsh-startup-screen:shown', '1')
      if (C.mode === 'daily') {
        window.localStorage.setItem('dsh-startup-screen:day', new Date().toISOString().slice(0, 10))
      }
    } catch (err) { /* 隐私模式下不可写，忽略 */ }
    /* 解锁：Host 注入的关键样式用 html.dsu-lock 锁滚动，这里必须一并摘掉，
       否则揭幕后主界面会永远滚不动。 */
    document.documentElement.classList.remove('dsu-lock')
    document.documentElement.style.overflow = ''
    if (document.body) document.body.style.overflow = ''
    root.classList.remove('dsu-boot')
    root.classList.add('dsu-gone')
    setTimeout(function () {
      if (root && root.parentNode) root.parentNode.removeChild(root)
      try { window.dispatchEvent(new CustomEvent('dsh-startup:done')) } catch (err) { /* noop */ }
    }, ms(900))
  }

  function requestSkip() {
    if (skipped || finished) return
    skipped = true
    releaseAll()
    finish()
  }

  if (C.allowSkip && ui.skip) {
    ui.skip.hidden = false
    ui.skip.addEventListener('click', function (e) { e.stopPropagation(); requestSkip() })
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') requestSkip()
    })
  } else if (ui.skip) {
    ui.skip.hidden = true
  }

  /* 对外 API：settings 面板里的"立即预览"按钮和重播都走它 */
  window.__DSH_STARTUP_API__ = {
    /* 设置页试听与冒烟测试用：直接念一行 */
    speak: function (en, zh) { voice.say(en, zh) },
    speakName: function (n) { return voice.speakName(n) },
    get voice() { return voice.current() },
    replay: injectSelf,
    skip: requestSkip,
    finish: finish,
    config: C
  }

  /* 锁滚动，动画期间不露出下面的应用 */
  document.documentElement.classList.add('dsu-lock')
  document.documentElement.style.overflow = 'hidden'
  if (document.body) document.body.style.overflow = 'hidden'
  setProgress(0.05)
  root.classList.remove('dsu-boot')

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { run() })
  } else {
    run()
  }
})()
