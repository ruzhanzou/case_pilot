export function agentToolLabels(pick: (english: string, chinese: string) => string): Record<string, string> {
  return {
    get_workspace_context: pick("Read workspace", "读取工作区"), query_cases: pick("Search cases", "检索用例"),
    query_assets: pick("Search reusable assets", "检索可复用资产"), query_collections: pick("Query collections", "查询集合"),
    query_uploaded_cases: pick("Query historical table cases", "历史表用例查询"),
    preview_uploaded_cases: pick("Preview historical case drafts", "历史用例草稿预览"),
    select_collection: pick("Switch working collection", "切换工作集合"),
    query_candidates: pick("Query candidates", "查询候选"), select_assets: pick("Update selected assets", "更新资产选择"),
    update_selection: pick("Update selection", "更新选择范围"), plan_work: pick("Plan requested actions", "规划请求操作"),
    plan_test_points: pick("Plan test points", "规划测试点"), prepare_generation: pick("Prepare generation plan", "准备生成规划"),
    prepare_rewrite: pick("Prepare rewrite preview", "准备改写预览"), prepare_delete: pick("Prepare deletion review", "准备删除审阅"),
    prepare_reuse: pick("Prepare reuse review", "准备复用审阅"), prepare_review: pick("Prepare case review", "准备用例评审"),
    prepare_dedup: pick("Prepare duplicate analysis", "准备冗余分析"), prepare_coverage: pick("Prepare coverage analysis", "准备覆盖分析"),
    answer_knowledge: pick("Prepare grounded answer", "准备有据回答"), answer_question: pick("Answer question", "回答问题"),
    review_cases: pick("Review cases", "评审用例"), deduplicate_cases: pick("Analyze duplicates", "分析冗余"), analyze_coverage: pick("Analyze coverage", "分析覆盖"),
    delete_collection: pick("Prepare collection soft deletion", "准备集合软删除方案"),
    create_collection: pick("Prepare collection creation", "准备创建集合方案"), rename_collection: pick("Prepare collection rename", "准备集合重命名方案"),
    read_attachment_evidence: pick("Read attachment evidence", "读取附件依据"), list_attachments: pick("List reference files", "列出引用文件"),
    read_attachment: pick("Read reference file", "读取引用文件"), search_evidence: pick("Search evidence", "检索依据"),
  };
}
