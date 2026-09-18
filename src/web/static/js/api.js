/* 后端接口的集中出口。

   这一层只管「怎么把数据拿回来」，不管「拿到之后怎么显示」。
   错误提示刻意留给调用方——同一个接口在不同场景下的提示语并不一样
   （启动时恢复会话要静默，用户手动点开会话才要报错），
   在这一层写死就只能二选一。 */

const API = '';

export const apiPath = (p) => API + p;

/* ---------------- 设置 ---------------- */

export async function getSettings() {
  const res = await fetch(API + '/settings');
  if (!res.ok) return null;
  return res.json();
}

/**
 * 保存设置。成功返回 { ok: true }，失败返回 { ok: false, message }。
 * 不抛异常：调用方要的是「能不能给用户一个说法」，不是堆栈。
 */
export async function saveSettings(values) {
  try {
    const res = await fetch(API + '/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ values }),
    });
    const data = await res.json();
    if (!res.ok) return { ok: false, message: data.detail || '保存失败' };
    return { ok: true };
  } catch (e) {
    return { ok: false, message: e.message };
  }
}

/* ---------------- 供应商 ---------------- */

export async function getProviders() {
  try {
    const res = await fetch(API + '/settings/providers');
    if (!res.ok) return null;
    return res.json();
  } catch (e) {
    return null;
  }
}

/** 切供应商。model 可以不传，后端会用该家的预设首选。 */
export async function selectProvider(provider, model) {
  try {
    const res = await fetch(API + '/settings/providers/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, model: model || null }),
    });
    const data = await res.json();
    if (!res.ok) return { ok: false, message: data.detail || '切换失败' };
    return { ok: true, ...data };
  } catch (e) {
    return { ok: false, message: e.message };
  }
}

export async function saveKey(provider, key) {
  try {
    const res = await fetch(API + '/settings/keys', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, key }),
    });
    const data = await res.json();
    if (!res.ok) return { ok: false, message: data.detail || '保存失败' };
    return { ok: true };
  } catch (e) {
    return { ok: false, message: e.message };
  }
}

/** 拉取该供应商真实可用的模型。失败不算错误，返回的 models 会是空数组。 */
export async function fetchModels(provider) {
  try {
    const res = await fetch(API + '/settings/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    });
    const data = await res.json();
    if (!res.ok) return { ok: false, models: [], message: data.detail || '获取失败' };
    return data;
  } catch (e) {
    return { ok: false, models: [], message: e.message };
  }
}

/** 连接测试。后端会等 5 秒超时，这里不用另设。 */
export async function testProvider(provider) {
  try {
    const res = await fetch(API + '/settings/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider }),
    });
    const data = await res.json();
    if (!res.ok) return { ok: false, message: data.detail || '测试失败' };
    return data;
  } catch (e) {
    return { ok: false, message: e.message };
  }
}

/* ---------------- 会话 ---------------- */

/* 列表类接口失败一律返回空数组，不往外抛：
   原实现里这两个调用是静默的（拉不到就保持上一次的列表），
   换成抛错会凭空多出一堆错误提示，行为就变了 */
export async function getSessions() {
  try {
    const res = await fetch(API + '/sessions');
    if (!res.ok) return [];
    return (await res.json()).sessions || [];
  } catch (e) {
    return [];
  }
}

export async function loadSession(id) {
  const res = await fetch(API + '/sessions/' + id);
  if (!res.ok) return null;
  return res.json();
}

export async function deleteSession(id) {
  try {
    await fetch(API + '/sessions/' + id, { method: 'DELETE' });
  } catch (e) { /* 删不掉就下次再删，不值得打断用户 */ }
}

/* ---------------- 文件 ---------------- */

export async function getFiles() {
  try {
    const res = await fetch(API + '/files');
    if (!res.ok) return [];
    return (await res.json()).files || [];
  } catch (e) {
    return [];
  }
}

export async function clearFiles() {
  const res = await fetch(API + '/files', { method: 'DELETE' });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || '清空失败');
  return data.deleted;
}

/* 接口说不支持时返回 null（调用方提示「无法预览这个文件」），
   网络断了才抛错（调用方提示「预览失败：原因」）——
   这两种情况原本就是两句话，不能合并 */
export async function preview(path) {
  const res = await fetch(API + '/preview?path=' + encodeURIComponent(path));
  if (!res.ok) return null;
  return res.json();
}

/* 下载走一个隐藏的 <a>，不用 fetch：
   文件可能是几十 MB，走 fetch 要先整个读进内存再转 blob，
   而浏览器原生下载直接落盘，还能复用它的进度条 */
export function download(path, name) {
  const a = document.createElement('a');
  a.href = API + '/download?path=' + encodeURIComponent(path);
  a.download = name;
  a.click();
}

export async function upload(file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch(API + '/upload', { method: 'POST', body: fd });
  const data = await res.json();
  if (!res.ok) throw new Error(data.detail || '未知错误');
  return data;
}

/* ---------------- 对话 ---------------- */

/**
 * 发起一次流式对话，逐事件回调。
 *
 * onEvent 每收到一个 SSE 事件就被调用一次——前端靠它把工具卡片
 * 一个一个画出来，而不是等整轮跑完再一次性渲染。
 *
 * 返回 true 表示正常结束，false 表示连接中断（调用方据此写错误提示）。
 */
export async function chat({ question, sessionId, onEvent }) {
  const res = await fetch(API + '/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, session_id: sessionId || null }),
  });
  if (!res.ok) throw new Error('HTTP ' + res.status);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });

    // SSE 以空行分隔事件。最后一段可能是半个事件，留在 buf 里等下一片
    const chunks = buf.split('\n\n');
    buf = chunks.pop();

    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith('data:')) continue;
      let ev;
      try {
        ev = JSON.parse(line.slice(5).trim());
      } catch (e) {
        // 静默跳过会让问题极难查：事件没了，界面停在加载态，
        // 控制台却干干净净。至少留下痕迹
        console.warn('[SSE] 事件解析失败，已跳过：', e.message, line.slice(0, 200));
        continue;
      }
      await onEvent(ev);
    }
  }
}
