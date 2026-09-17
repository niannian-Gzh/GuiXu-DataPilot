/* 无状态的工具函数与常量。
   全部是纯函数：给定输入必然得到同样输出，不碰 DOM、不碰网络、不碰 store，
   所以从 setup 里提出来是安全的。 */

/* 字段的界面显示名。改前后对比、确认卡片都靠它把 project_name 变成「项目名称」 */
export const FIELD_LABELS = {
  project_name: '项目名称', owner: '负责人', category: '分类',
  status_raw: '状态', issued_date: '下发时间', certified_date: '下证时间',
  resubmit_name: '重提项目名', reject_date: '打回时间',
  resubmit_date: '重提时间', reject_count: '打回次数',
};

/* SQL 高亮的关键字表 */
export const SQL_WORDS = [
  'SELECT', 'FROM', 'WHERE', 'AND', 'OR', 'NOT', 'IN', 'LIKE', 'ORDER', 'BY',
  'GROUP', 'HAVING', 'LIMIT', 'COUNT', 'SUM', 'AVG', 'MAX', 'MIN', 'AS',
  'JOIN', 'LEFT', 'RIGHT', 'INNER', 'ON', 'DESC', 'ASC', 'IS', 'NULL',
  'TRUE', 'FALSE', 'BETWEEN', 'DISTINCT', 'CAST', 'CASE', 'WHEN', 'THEN',
  'ELSE', 'END', 'INTERVAL', 'TIMESTAMP', 'CURRENT_DATE',
];

/* ---------------- 工具函数 ---------------- */
export const escapeHtml = (s) => {
  const d = document.createElement('div');
  d.textContent = s ?? '';
  return d.innerHTML;
};

/* 成对的 ** 直接落成标签，绕开 CommonMark 的定界符判定。
   规范规定：闭合的 ** 前面若是标点，则后面必须也是空白或标点，
   否则不构成右定界符，整对星号会原样留在正文里。
   英文靠词间空格躲过一劫，中文没有空格——
   「这是**包含匹配（含组合状态）**的口径」里的 ** 前面是「）」、
   后面是「的」，正是那个被判无效的组合。
   实测 markdown-it 表现完全相同，这是规范行为而非 marked 的缺陷。
   代码块和行内代码里的星号是字面量，不参与替换。 */
export const strongify = (text) => {
  const s = String(text ?? '');
  if (!s.includes('**')) return s;

  /* 前后都要求不是星号，这样 ****甲**** 这类嵌套写法会整个跳过，
     交回 marked 按原样解析成嵌套 strong，而不是被切歪 */
  const pair = (seg) => seg.replace(
    /(?<!\*)\*\*(?=[^\s*])([\s\S]*?[^\s*])\*\*(?!\*)/g,
    '<strong>$1</strong>',
  );

  // 按 ``` 切段，奇数下标是围栏代码块，原样保留
  const fences = s.split('```');
  for (let i = 0; i < fences.length; i += 2) {
    // 行内代码不跨行，逐行按 ` 切格，奇数下标是代码
    fences[i] = fences[i].split('\n').map((line) => {
      const cells = line.split('`');
      for (let j = 0; j < cells.length; j += 2) cells[j] = pair(cells[j]);
      return cells.join('`');
    }).join('\n');
  }
  return fences.join('```');
};

export const md = (text) => {
  try { return marked.parse(strongify(text)); }
  catch (e) { return escapeHtml(text); }
};

export const safeParse = (raw) => {
  try { return JSON.parse(raw); } catch (e) { return null; }
};

export const prettyJson = (obj) => {
  try { return JSON.stringify(obj, null, 2); } catch (e) { return String(obj); }
};

export const highlightSql = (sql) => {
  const re = new RegExp('\\b(' + SQL_WORDS.join('|') + ')\\b', 'gi');
  return escapeHtml(sql).replace(re, '<span class="kw">$1</span>');
};

export const fmtVal = (v) => {
  if (v === null || v === undefined) return '—';
  if (typeof v === 'object') return prettyJson(v);
  return String(v);
};

export const shortTime = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  const hm = pad(d.getHours()) + ':' + pad(d.getMinutes());
  if (d.toDateString() === new Date().toDateString()) return hm;
  return (d.getMonth() + 1) + '/' + d.getDate() + ' ' + hm;
};

export const toolGist = (tool) => {
  const p = tool.parsed;
  if (p) {
    if (p.row_count != null) return p.row_count + ' 行';
    if (p.answer) return String(p.answer).slice(0, 70);
    if (p.message) return String(p.message).slice(0, 70);
  }
  const a = tool.args || {};
  const v = a.question || a.filter_question || '';
  return v ? String(v).slice(0, 70) : '';
};

/* 思考节点的唯一构造入口。实时推送和历史回放都从这里出——
   两条路径各写一份的话，迟早会漂移成一个有 round 一个没有、
   一个有 open 一个没 open，界面上就长得不一样了 */
export const makeThinkNode = (round, text) => ({
  kind: 'think',
  round: round ?? null,
  text: text || '',
  open: false,
});

/* 折叠状态下的一行预览。思维链开头多是"我们需要…"这类套话，
   信息量不高，但至少能让人判断值不值得展开 */
export const thinkGist = (text) =>
  String(text || '').replace(/\s+/g, ' ').trim().slice(0, 70);

export const confirmColumns = (c) => (c.rows && c.rows.length ? Object.keys(c.rows[0]) : []);
export const confirmTitle = (c) => {
  if (!c.resolved) return c.scope + ' · 等待确认';
  return c.scope + ' · ' + (c.cancelled ? '已取消' : '已执行');
};

/* ---------------- 确认卡片构造 ---------------- */
export const candidateRows = (list) =>
  list.map((c) => ({
    '项目名称': c.project_name,
    '负责人': c.owner || '—',
    '状态': c.status_raw || '—',
  }));

export const buildConfirm = (pending) => {
  const type = pending.type;
  const base = { resolved: false, verdict: '', rows: [], diffs: null, verb: '确认' };

  if (type === 'delete') {
    const n = pending.candidates.length;
    return Object.assign(base, {
      scope: '删除 ' + n + ' 条记录',
      verb: '确认删除',
      danger: true,
      rows: candidateRows(pending.candidates),
      note: '确认后这 ' + n + ' 条进入回收站，7 天内可恢复。',
    });
  }

  if (type === 'restore') {
    const n = pending.candidates.length;
    return Object.assign(base, {
      scope: '恢复 ' + n + ' 条记录',
      verb: '确认恢复',
      rows: candidateRows(pending.candidates),
      note: '确认后这 ' + n + ' 条重新回到项目台账。',
    });
  }

  if (type === 'create') {
    const r = pending.record;
    return Object.assign(base, {
      scope: '新增 1 条记录',
      verb: '确认新增',
      rows: [{
        '项目名称': r.project_name,
        '负责人': r.owner || '—',
        '分类': r.category || '—',
        '状态': r.status_raw || '已提交',
        '下发时间': r.issued_date || '今天',
      }],
      note: '确认后写入台账。',
    });
  }

  if (type === 'batch_create') {
    const n = pending.records.length;
    return Object.assign(base, {
      scope: '批量新增 ' + n + ' 条记录',
      verb: '确认新增',
      rows: candidateRows(pending.records),
      note: '确认后这 ' + n + ' 条写入台账。',
    });
  }

  if (type === 'update') {
    const n = pending.candidates.length;
    const first = pending.candidates[0] || {};
    const diffs = Object.entries(pending.updates || {}).map(([k, v]) => ({
      field: FIELD_LABELS[k] || k,
      from: n === 1 ? fmtVal(first[k]) : '（' + n + ' 条各不相同）',
      to: fmtVal(v),
    }));
    return Object.assign(base, {
      scope: '修改 ' + n + ' 条记录',
      verb: '确认修改',
      rows: pending.candidates.map((c) => ({
        '项目名称': c.project_name,
        '负责人': c.owner || '—',
        '当前状态': c.status_raw || '—',
      })),
      diffs,
      note: '确认后立即写入台账。',
    });
  }

  if (type === 'import') {
    const s = pending.scan_result || {};
    const count = (k) => (s[k] ? s[k].length : 0);
    return Object.assign(base, {
      scope: 'Excel 导入',
      verb: '确认导入',
      rows: [
        { '类别': '新增记录', '条数': count('new_records'), '说明': '文件里有、台账里没有' },
        { '类别': '字段冲突', '条数': count('conflicts'), '说明': '同名记录字段对不上' },
        { '类别': '已删除待恢复', '条数': count('deleted_in_db'), '说明': '台账里是删除态、文件里又出现' },
        { '类别': '文件缺失', '条数': count('missing_from_excel'), '说明': '台账里有、文件里没有（不影响）' },
      ],
      note: '默认口径：新增全部导入，冲突以台账为准，已删除的保持删除。'
          + '要改口径请直接在输入框说明，例如「导入，并恢复已删除的记录」。',
    });
  }

  return Object.assign(base, {
    scope: '需要确认',
    verb: '确认',
    note: pending.message || '',
  });
};
