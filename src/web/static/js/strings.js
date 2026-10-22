/* 界面文案表。

   **产品只有中文。** 这里不是多语言框架——没有 en、没有语言切换，
   也不为"将来翻译"留空位。集中在这里的理由只有两个：

   1. 文案和模板分开，改措辞不用翻组件
   2. 带 {x} 的占位符用 fmt() 填，避免 prefix + 值 + suffix 拼接

   将来真要加语言，再给这里加一层映射；现在不预支那层结构。 */

export const STRINGS = {
    /* 轨迹页 */
    traceEmpty: '执行轨迹只属于当前这次对话，换个会话或先问点什么',
    noToolOutput: '这一步没有返回内容（等待确认或被中断）',

    /* 欢迎页 */
    welcomeTitle: '今天想问点什么？',
    welcomeSubtitle: '用一句话，处理你的数据',

    /* 输入区 */
    cancel: '取消',
    send: '发送',
    nextQuestion: '下一题',

    /* 产物 */
    artifacts: '产物',
    preview: '预览',

    /* 设置页 */
    settings: '设置',
    save: '保存',
    saving: '保存中…',
    discardChanges: '放弃改动',
    resetDefault: '恢复默认',

    /* 维护组 */
    exportFiles: '导出与报告文件',
    historySessions: '历史会话',
    confirmDelete: '确认删除',
    clearAllFiles: '清空所有文件',
    deleteAllSessions: '删除全部会话',

    /* 数据库概览 */
    schemaTitle: '数据库概览',
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
    primaryKey: '主键',
    uniqueKey: '唯一',
    compositeUnique: '组合唯一',
    relations: '关系',
    relationAdd: '添加',
    relationRemove: '删除这条关系',
    noRelations: '还没有关系',
    relFrom: '本端',
    relTo: '对端',
    relCardinality: '基数',
    relNone: '不填',
    relNeedBoth: '两端都要选列',
    relAddFail: '添加失败：',
    relDropFail: '删除失败：',
    relAdded: '已添加关系',
    relRemoved: '已删除关系',

    /* 版本更新 */
    updateTitle: '版本更新',
    updateCheck: '检查更新',
    updateChecking: '检查中…',
    updateLatest: '已是最新 {v}',
    updateFound: '发现新版本 {v}',
    updateFailed: '暂时连不上 GitHub',
    updateOpen: '打开下载页',
    updateHint: '只在你点按钮时联网；不会自动下载或安装',

    /* 恢复页 */
    /* 文档库 */
    docsTitle: '文档库',
    docsCount: '{n} 份 · {m} 块',
    docsTabLibrary: '文档库',
    docsTabTrash: '回收站',
    docsTrashEmpty: '回收站是空的',
    docsTrashCount: '回收站 {n}',
    docsDeletedAt: '{at} 删除',
    docsDaysLeft: '剩 {n} 天',
    docsRestore: '恢复',
    docsRestored: '已恢复：{name}',
    docsDeleted: '已移入回收站：{name}',
    docsPreview: '原文',
    docsChunksTitle: '分块',
    docsUpload: '上传文档',
    docsUploading: '入库中…',
    docsDrop: '把 PDF / Word / txt / md 拖到这里',
    docsEmpty: '文档库还是空的',
    docsEmptyHint: '制度、手册、规范这类资料传上来，Agent 就能检索它们',
    docsSearchPlaceholder: '检索一句话，看看能命中哪段',
    docsSearch: '检索',
    docsSearchEmpty: '没有找到相关内容',
    docsRebuild: '重建索引',
    docsRebuilt: '索引已重建 · {n} 块 · {ms} ms',
    docsDelete: '删除',
    docsDeleteTitle: '删除文档',
    docsDeleteWarn: '文档会移入回收站，保留期内可以恢复；切片和检索结果会立即隐藏。',
    docsConfirmDelete: '确认删除',
    docsUploaded: '已入库：{name} · {n} 块',
    docsLoadFail: '读取文档库失败',
    docsChunks: '{n} 块',

    recoverTitle: '恢复',
    recoverTrash: '垃圾桶',
    recoverVersions: '版本历史',
    recoverSearchTrash: '搜表名、行内容或时间',
    recoverSearchVersions: '搜表名、类别或时间',
    recoverEmptyTrash: '回收站是空的',
    recoverEmptyVersions: '还没有任何快照',
    recoverLoadFail: '读取失败',
    recoverDeletedCount: '{n} 条',
    recoverSnapCount: '{n} 份',
    recoverRowCount: '{n} 行',
    recoverRestore: '恢复',
    recoverPreview: '预览',
    recoverRollback: '回滚',
    recoverNoPk: '这张表没有主键，无法按行恢复',
    recoverTableGone: '表已删除',
    recoverRestored: '已恢复 {n} 条',
    recoverRolledBack: '已回滚到 {at}',
    recoverRollbackWarn: '当前数据会先存一份快照，回滚错了还能回来。',
    recoverRebuild: '这张表当前不存在，回滚会把它重建出来。',
    recoverRollbackTitle: '确认回滚？',
    recoverConfirmRollback: '确认回滚',
    recoverShown: '显示前 {n} 行，共 {total} 行',
    recoverClose: '关闭',
    recoverFieldTable: '表',
    recoverFieldTime: '时间',
    recoverFieldKind: '类别',
    recoverFieldRows: '行数',
};

/**
 * 取文案表，直接给模板用属性访问：t.artifacts。
 *
 * 不导出一个 t(key) 函数——模板里写 t('artifacts') 又长又容易和
 * 属性访问混起来，而且 Vue 模板对函数调用的容错不如属性访问直观。
 */
export function dict() {
  return STRINGS;
}

/** 填占位符：fmt('第 {n} 轮', { n: 2 }) → '第 2 轮' */
export function fmt(template, params) {
  return String(template).replace(/\{(\w+)\}/g, (m, k) =>
    (params && params[k] !== undefined ? params[k] : m));
}
