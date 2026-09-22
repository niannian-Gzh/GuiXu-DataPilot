/* 界面文案字典。

   带 {x} 的是占位符模板，用 fmt() 填——不拆成 prefix + 值 + suffix：
   中英文语序不同（「思考 · 第 2 轮」对 "Thinking · Round 2"），
   拆成前后缀拼起来，换语言时必然散架。

   en 先留空对象：查不到就回落 zh，界面不会出现空白或 undefined。 */

export const I18N = {
  zh: {
    /* 品牌 */
    brandTag: '数据处理 Agent',

    /* 左栏 */
    tabSessions: '会话',
    tabTrace: '轨迹',
    newChat: '新对话',
    noSessions: '还没有历史会话',
    deleteSession: '删除会话',
    clickAgainToDelete: '再点一次即删除',

    /* 轨迹页 */
    traceTitle: '执行轨迹',
    traceScope: '执行过程只属于当前这次对话',
    traceEmpty: '执行轨迹只属于当前这次对话，换个会话或先问点什么',
    traceRounds: '本会话轮次',
    totalSteps: '总步数',
    toolTime: '工具耗时',
    statOk: '成功',
    statFail: '失败 / 拒绝',
    noToolOutput: '这一步没有返回内容（等待确认或被中断）',
    thinkRound: '思考 · 第 {n} 轮',
    thinkPlain: '思考',
    empty: '空',
    running: '正在处理…',

    /* 欢迎页 */
    welcomeTitle: '今天想问点什么？',
    welcomeSubtitle: '用一句话，处理你的数据',
    sampleHint: '试试「把已下证的项目导成 Excel」',

    /* 输入区 */
    inputPlaceholder: '问点什么，或把 Excel 拖进来',
    sendHint: '发送 ·',
    newlineHint: '换行',
    cancel: '取消',

    /* 产物 */
    artifacts: '产物',
    preview: '预览',
    download: '下载',
    downloadView: '下载查看',

    /* 设置页 */
    settings: '设置',
    save: '保存',
    saving: '保存中…',
    discardChanges: '放弃改动',
    appearance: '外观',
    theme: '主题',
    dark: '深色',
    light: '浅色',
    unsaved: '未保存',
    changed: '已改',
    resetDefault: '恢复默认',
    readonlyInfo: '只读信息',
    maintain: '维护',
    notSet: '未设置',
    all: '全部',

    /* 维护组 */
    exportFiles: '导出与报告文件',
    historySessions: '历史会话',
    filesCount: '· 共 {n} 个',
    sessionsCount: '· 共 {n} 个',
    deleteFilesWarn: '将永久删除 {n} 个文件，不可撤销',
    deleteSessionsWarn: '将永久删除 {n} 个会话，含全部对话记录',
    confirmDelete: '确认删除',
    confirm: '确认？',
    clearAllFiles: '清空所有文件',
    deleteAllSessions: '删除全部会话',

    /* 数据库概览 */
    schemaTitle: '数据库概览',
    schemaDesc: '只读表结构。字段名、类型、必填都是数据库的事实，这里改不了；能改的只有中文映射',
    refresh: '刷新',
    refreshing: '刷新中…',
    refreshNoChange: '无变化',
    refreshAddedTables: '新增 {n} 张表',
    refreshAddedFields: '新增 {n} 个字段',
    refreshRemovedFields: '移除 {n} 个字段',
    unnamedTable: '未命名表',
    fieldsCount: '· {n} 个字段',
    fieldName: '字段名',
    fieldType: '类型',
    fieldConstraint: '约束',
    fieldLabel: '中文含义',
    required: '必填',
    nullable: '可空',
    unlabeled: '未标注',
    unsavedCount: '{n} 处未保存',
    labelHint: '这段说明会原样发给模型，写得越具体，判断越准',
    confirmSaveTitle: '确认保存以下修改？',
    confirmSave: '确认保存',
    ok: '确定',
    confirmLeaveTitle: '有未保存的修改，确定离开？',
    confirmLeave: '离开',
    saved: '已保存',
    tableNameChange: '表名',
  },

  en: {},
};

/**
 * 取某个语言的字典，直接给模板用属性访问：t.artifacts。
 *
 * 不导出一个 t(key) 函数——模板里写 t('artifacts') 又长又容易和
 * 属性访问混起来，而且 Vue 模板对函数调用的容错不如属性访问直观。
 */
export function dict(lang = 'zh') {
  return I18N[lang] || I18N.zh;
}

/** 填占位符：fmt('第 {n} 轮', { n: 2 }) → '第 2 轮' */
export function fmt(template, params) {
  return String(template).replace(/\{(\w+)\}/g, (m, k) =>
    (params && params[k] !== undefined ? params[k] : m));
}
