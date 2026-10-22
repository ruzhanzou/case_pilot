"use client";

import type { GenerationAssetSelection } from "@/lib/casepilot-api";
import { useI18n } from "@/lib/i18n";

export function GenerationAssets({ selection, selected, onChange, onConfirm, busy, scope = [], onScopeChange, preview = false }: {
  selection: GenerationAssetSelection;
  selected: string[];
  onChange: (ids: string[]) => void;
  onConfirm: () => void;
  busy: boolean;
  scope?: string[];
  onScopeChange?: (ids: string[]) => void;
  preview?: boolean;
}) {
  const { pick } = useI18n();
  const ids = new Set(selected);
  const modifying = selection.followup_intent === "CASE_MODIFY";
  const groups = new Map<string, { name: string; sources: typeof selection.sources }>();
  for (const source of selection.sources) {
    const collection = source.collections[0];
    const key = collection?.id ?? source.label;
    const group = groups.get(key) ?? { name: collection?.name ?? source.label, sources: [] };
    group.sources.push(source); groups.set(key, group);
  }
  const scoped = !!selection.target_points?.length;
  const imports = selection.import_report ?? [];
  const importWarnings = imports.filter(row => !row.valid && !row.ignored);
  return <section aria-label={pick("Existing asset selection", "现有用例资产选择")} className="conversation-intent-confirmation">
    <strong>{pick("Confirm assets before planning", "先确认资产，再继续")}</strong>
    <p>{pick("Test object: ", "测试对象：")}{selection.test_object}</p>
    {imports.length > 0 && <details className="generation-assets__import-report" open={importWarnings.length > 0}>
      <summary>{pick("Uploaded case recognition", "上传用例识别结果")} · {imports.filter(row => row.valid).length}{pick(" recognized", " 条已识别")} · {importWarnings.length}{pick(" need checking", " 处待核对")}</summary>
      <p>{pick("The model organizes source cells without filling missing expectations. Review the case text and source locations before confirming. Unresolved rows are not available for reuse.", "模型整理原始单元格，不补写缺失预期。请展开下方用例核对内容与来源后再确认；未识别完整的内容不参与复用。")}</p>
      {imports.some(row => row.method === "fallback") && <p role="status">{pick("Some sections could not be organized by the model. Only standard table extraction is available for those sections; upload again to retry.", "部分内容未完成模型整理，目前仅保留标准表格解析结果；可重新上传重试。")}</p>}
      <ul>{imports.filter(row => !row.valid).slice(0, 100).map((row, index) => <li key={`${row.label}:${row.sheet}:${row.row}:${index}`}>
        {row.label} · {row.sheet} · {pick("Row ", "第 ")}{row.row}{row.row_end && row.row_end !== row.row ? `–${row.row_end}` : ""}{pick("", " 行")}：{row.reason}
      </li>)}</ul>
      {imports.filter(row => !row.valid).length > 100 && <p>{pick("Showing the first 100 diagnostics. Split the file to inspect the remaining rows.", "当前展示前 100 条解析说明，可拆分文件核对其余内容。")}</p>}
    </details>}
    {selection.search?.truncated && <p role="status">{pick(
      `Matched ${selection.search.matched_case_count} cases across a search scope of ${selection.search.scope_collection_count} collections. Checked the top ${selection.search.returned_case_count} candidates; other matches have not been reviewed. Narrow the collection or scenario to find more specific references.`,
      `搜索范围 ${selection.search.scope_collection_count} 个用例集，共匹配 ${selection.search.matched_case_count} 条，本轮核对前 ${selection.search.returned_case_count} 条候选，其他匹配项尚未核对。可补充集合名称或具体场景缩小范围。`
    )}</p>}
    <p>{selection.strategy === "select"
      ? pick("Selected assets will form the new collection. No new cases will be generated.", "选中的资产将组成新用例集合，不生成新用例。")
      : modifying
        ? pick("Confirm reference assets, then review the affected cases before generating change proposals.", "确认参考来源后，继续确认修改范围并生成变更建议。")
        : scoped
          ? pick("The model will decide reuse, adaptation or new generation for the selected points. Other results stay intact.", "模型将为选中测试点判断直接复用、参考改写或全新生成，未选内容保留。")
          : pick("After confirmation, the model will plan points and decide direct reuse, adaptation or new generation.", "确认后规划测试点，由模型逐点判断直接复用、参考改写或全新生成。")}</p>
    <p>{pick("Matching the test object makes an asset eligible for review, not automatically reusable. Check its rules, steps and expectations before selecting it.", "测试对象一致只表示可参与参考，不代表可以直接复用。请核对规则、步骤和预期；确认来源后再查看逐点处理建议。")}</p>
    {!!selection.target_points?.length && <fieldset disabled={busy}>
      <legend>{pick("Confirm affected test points", "确认本轮影响的测试点，未选内容保留")}</legend>
      {selection.target_points.map(point => <label key={point.id} style={{ display: "block" }}>
        <input type="checkbox" checked={scope.includes(point.id)} onChange={event => onScopeChange?.(event.target.checked ? [...scope, point.id] : scope.filter(id => id !== point.id))} />{point.title}
      </label>)}
    </fieldset>}
    {selection.sources.length === 0 && <p>{pick("No assets with a verified matching test object were found.", "未找到可确认测试对象一致的资产。")}</p>}
    {selection.sources.length > 0 && <p aria-live="polite">{pick("Selected: ", "已选：")}{selection.sources.filter(source => ids.has(source.case_id)).length} / {selection.sources.length}</p>}
    <div className="generation-assets__list" role="group" aria-label={pick("Available assets", "可选资产")} tabIndex={selection.sources.length ? 0 : -1}>
    {[...groups.entries()].map(([key, group]) => <fieldset key={key} className="generation-assets__collection">
      <legend><label><input type="checkbox" disabled={busy} checked={group.sources.every(source => ids.has(source.case_id))} aria-label={pick(`Select collection ${group.name}`, `选用集合 ${group.name}`)} onChange={event => { const groupIds = new Set(group.sources.map(source => source.case_id)); onChange(event.target.checked ? [...new Set([...selected, ...groupIds])] : selected.filter(id => !groupIds.has(id))); }} />{group.name} · {group.sources.length}{pick(" matching cases", " 条匹配用例")}</label></legend>
    {group.sources.map(source => <div key={source.key}>
      <label><input type="checkbox" checked={ids.has(source.case_id)} disabled={busy}
        onChange={event => onChange(event.target.checked ? [...selected, source.case_id] : selected.filter(id => id !== source.case_id))} />
        {source.snapshot.title}
      </label>
      <small>{source.collections.map(collection => collection.name).join("、") || source.label}{source.locator ? ` · ${source.locator}` : ""} · {source.match_reason}</small>
      {(preview || source.kind === "excel") && <details><summary>{pick("View case", "查看用例")}</summary>
        <p>{source.snapshot.preconditions.join("；")}</p>
        <ol>{source.snapshot.steps.map((step, index) => <li key={index}>{step.action} → {step.expected}</li>)}</ol>
      </details>}
    </div>)}
    </fieldset>)}
    </div>
    {!selection.sources.length && selection.strategy === "select" && <p role="status">{pick("Selection-only mode will not generate new cases. Refine your search in the conversation, or ask to generate new cases.", "当前为仅选已有用例，不会自动新增。请在对话区调整搜索条件，或明确要求生成新用例。")}</p>}
    <button type="button" disabled={busy || (!!selection.target_points?.length && !scope.length) || (selection.strategy === "select" && selected.length === 0)} onClick={onConfirm}>
      {selection.strategy === "select" ? pick("Confirm selection and form collection", "确认选用并组成集合") : modifying ? pick("Confirm references and continue changes", "确认参考并继续修改") : scoped ? pick("Confirm sources and affected points", "确认来源与影响范围") : selected.length ? pick("Confirm reuse and start planning", "确认复用并开始规划") : pick("Continue planning without reuse", "不复用，继续规划")}
    </button>
  </section>;
}
