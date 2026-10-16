/* ============================================================================
 * 归墟 · 开机动画的宿主半侧
 * ----------------------------------------------------------------------------
 * 运行时（js/boot.js）只管演。谁看、什么时候看、怎么放行，全归这里。
 *
 * 为什么拆成两个文件、分两次加载：
 *   音频解锁只认【用户手势】。AudioContext 必须先被一次真实交互唤醒，
 *   而第一幕是自动开播的 —— 如果运行时在解析期就加载完并起跑，
 *   等用户第一次点击时第一句台词早过去了，解锁也补不回来。
 *   所以这里先只挂一个全屏闸门，等人按了键，再去加载运行时。
 *
 * 本文件必须【先于应用】执行：Vue 一挂载就有内容，闸门晚一步
 * 就会"先闪一下界面再盖上"。
 * ========================================================================== */
(function () {
  'use strict'

  /* 本标签页已经走过一遍：连闸门都不开。
     判据和运行时 finish() 写的是同一个键 —— 一处定义，两处读。
     index.html 顶部那段内联脚本读的也是它，且在样式加载前就写好了
     html[data-boot="skip"]，所以这里只管判断，不用再设一次。 */
  var shown = false
  try { shown = sessionStorage.getItem('dsh-startup-screen:shown') === '1' } catch (e) {}

  /* 配置。运行时的 DEFAULTS 已经是归墟的值（见 js/boot.js），
     所以这里只列"要覆盖默认"的项 —— 空对象也是合法的。
     留着这个文件是为了以后身份名称能接后端配置。 */
  window.__DSH_STARTUP__ = {
    enabled: true,
    mode: 'session'
  }

  if (shown) {
    window.__DSH_STARTUP_SKIP__ = true
    return
  }

  var started = false

  /* 解锁必须在【手势还在的时候】做，不能等运行时加载完再做。
     运行时自己的 unlock() 干三件事：resume 语音引擎、无声念一个空格
     把引擎唤醒（专治"第一句被吃掉开头"）、补播被压住的那句。
     但它的监听器是加载时才注册的 —— 那会儿这个手势早过去了，
     于是它一次都没跑，第一句就真的没了。所以这里先替它做掉。 */
  function unlockAudio() {
    try {
      var AC = window.AudioContext || window.webkitAudioContext
      if (AC) { var c = new AC(); if (c.state === 'suspended') c.resume() }
    } catch (e) { /* 没有 WebAudio 就算了 */ }
    try {
      if (window.speechSynthesis && window.SpeechSynthesisUtterance) {
        window.speechSynthesis.resume()
        var u = new window.SpeechSynthesisUtterance(' ')
        u.volume = 0
        window.speechSynthesis.speak(u)
      }
    } catch (e) { /* 没有 TTS 就算了 */ }
  }

  function start() {
    if (started) return
    started = true
    unlockAudio()
    var gate = document.getElementById('gate')
    if (gate) gate.classList.add('gone')
    var s = document.createElement('script')
    s.src = '/js/boot.js'
    document.body.appendChild(s)
  }

  /* 有任意交互就启动 —— 点、按、滚、触，谁先来算谁。
     只挂一次，所以用一个开关兜住，避免四类事件各触发一遍。 */
  ['pointerdown', 'keydown', 'touchstart', 'wheel'].forEach(function (ev) {
    document.addEventListener(ev, start, { capture: true })
  })
})()
