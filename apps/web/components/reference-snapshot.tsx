import type { CaseChangeSetDto } from "@/lib/casepilot-api";

/** Both review surfaces show the proposal's captured sources, not today's replacement context. */
export function ReferenceSnapshot({ binding }: { binding: CaseChangeSetDto["reference_binding"] }) {
  if (!binding?.sources?.length) return null;
  return <details className="workbench-reference-files">
    <summary>本提案引用资料 · 集合配置 v{binding.collection_version}</summary>
    {binding.sources.map(source => <div key={source.source_id}>
      {source.name} · 来源 v{source.source_revision}
      {source.documents.map(document => <small key={document.id}>
        {" "}{document.name} · 文件 v{document.version}
      </small>)}
    </div>)}
    <small>这是生成提案时的资料快照；资料变更或解除绑定后，旧确认会被拒绝。</small>
  </details>;
}
