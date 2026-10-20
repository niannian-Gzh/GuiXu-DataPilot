/* 无状态的工具函数与常量。
   全部是纯函数：给定输入必然得到同样输出，不碰 DOM、不碰网络、不碰 store，
   所以从 setup 里提出来是安全的。 */

/* 字段的界面显示名。改前后对比、确认卡片都靠它把 project_name 变成「项目名称」 */
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

/* 生成一个时间戳，格式和会话落盘时写的 gx_at 完全一致
   （本地时间、秒级、不带时区，见 src/session.py 的 _now()）。

   为什么前端也要自己生成一个：实时那一轮还没落盘，等不到后端的值。
   两边格式必须一样——差一点，同一次会话里就会出现「有的轮次解析得了、
   有的解析不了」，而这种错是静默的，只表现为某个时间是空的 */
export const stamp = (d = new Date()) => {
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
       + `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
};

/* 对话轮上的那个时刻。带秒是必需的：一轮里「问」和「答」往往只差几秒，
   只到分的话两边永远是同一个数，标了等于没标。
   不是今天的就补上日期，否则翻旧会话时会以为它是刚发生的 */
export const clockTime = (iso) => {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '';
  const pad = (n) => String(n).padStart(2, '0');
  const hms = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  if (d.toDateString() === new Date().toDateString()) return hms;
  return `${d.getMonth() + 1}/${d.getDate()} ${hms}`;
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
  return c.scope + ' · ' + (c.cancelled ? '已终止' : '已执行');
};

/* ---------------- 确认卡片构造 ---------------- */
/* 确认卡片：后端给数据，前端管长相。
   ============================================================
   后端只给 {type, table, columns, records, affected, danger, changes}，
   其中 columns 是**中文列名**（从表定义取），records 是与之对应的二维数组。

   这样这张卡片对**任何表**都成立。旧版把项目表的字段写死在这里
   （project_name / owner / status_raw），换一张表就显示错——
   而"多表"正是这个项目要去的方向。

   文案（scope / note）在前端按 type 写死，后端不传——
   design 的原话："卡片文案前端写死一句，后端不传文案"。 */
const CONFIRM_SCOPE = {
  delete:    (n) => `删除 ${n} 条记录`,
  restore:   (n) => `恢复 ${n} 条记录`,
  create:    (n) => (n > 1 ? `新增 ${n} 条记录` : '新增 1 条记录'),
  update:    (n) => `修改 ${n} 条记录`,
  transform: (n) => `修改 ${n} 条记录`,
  struct:    () => '修改表结构',
  import:    () => 'Excel 导入',
};

const CONFIRM_NOTE = {
  delete:    (n) => `确认后这 ${n} 条进入回收站，7 天内可恢复。`,
  restore:   (n) => `确认后这 ${n} 条重新回到台账。`,
  create:    () => '确认后写入台账。',
  update:    () => '确认后立即写入台账。',
  transform: (n) => `将修改 ${n} 条记录，请核对下方预览。`,
  struct:    () => '这是改表结构的操作，执行后结构会变。',
  import:    () => '默认口径：新增全部导入，冲突以台账为准，已删除的保持删除。'
                + '要改口径请直接在输入框说明，例如「导入，并恢复已删除的记录」。',
};

export const buildConfirm = (pending) => {
  const type = pending.type;
  const n = pending.affected ?? (pending.records ? pending.records.length : 0);

  const c = {
    resolved: false,
    verdict: '',
    rows: [],
    diffs: null,
    typed_input: '',
    confirm_mode: pending.confirm_mode || 'simple',
    confirm_hint: pending.confirm_hint || '确认',
    danger: !!pending.danger,
    scope: (CONFIRM_SCOPE[type] || (() => '需要确认'))(n),
    verb: pending.verb || (type === 'delete' ? '确认删除'
                         : type === 'restore' ? '确认恢复'
                         : '确认'),
    note: (CONFIRM_NOTE[type] || (() => ''))(n),
  };

  // 通用表格：列名 + 二维行。认不出业务字段，也没有业务字段可认。
  if (Array.isArray(pending.columns) && Array.isArray(pending.records)) {
    c.rows = pending.records.map((row) => {
      const obj = {};
      pending.columns.forEach((col, i) => {
        const v = Array.isArray(row) ? row[i] : row[col];
        obj[col] = v === null || v === undefined ? '—' : fmtVal(v);
      });
      return obj;
    });
  }

  // 字段级改动（update / transform）：{field, before, after}
  if (Array.isArray(pending.changes)) {
    c.diffs = pending.changes.map((d) => ({
      field: d.field,
      from: fmtVal(d.before),
      to: fmtVal(d.after),
    }));
  }

  return c;
};
