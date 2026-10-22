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
  const scoped = !!selection.target_points?.length;
  return <section aria-label={pick("Existing asset selection", "现有用例资产选择")} className="conversation-intent-confirmation">
    <strong>{pick("Confirm assets before planning", "先确认资产，再继续")}</strong>
    <p>{pick("Test object: ", "测试对象：")}{selection.test_object}</p>
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
    {!!selection.target_points?.length && <fieldset disabled={busy}>
      <legend>{pick("Confirm affected test points", "确认本轮影响的测试点，未选内容保留")}</legend>
      {selection.target_points.map(point => <label key={point.id} style={{ display: "block" }}>
        <input type="checkbox" checked={scope.includes(point.id)} onChange={event => onScopeChange?.(event.target.checked ? [...scope, point.id] : scope.filter(id => id !== point.id))} />{point.title}
      </label>)}
    </fieldset>}
    {selection.sources.length === 0 && <p>{pick("No assets with a verified matching test object were found.", "未找到可确认测试对象一致的资产。")}</p>}
    {selection.sources.length > 0 && <p aria-live="polite">{pick("Selected: ", "已选：")}{selection.sources.filter(source => ids.has(source.case_id)).length} / {selection.sources.length}</p>}
    <div className="generation-assets__list" role="group" aria-label={pick("Available assets", "可选资产")} tabIndex={selection.sources.length ? 0 : -1}>
    {selection.sources.map(source => <div key={source.key}>
      <label><input type="checkbox" checked={ids.has(source.case_id)} disabled={busy}
        onChange={event => onChange(event.target.checked ? [...selected, source.case_id] : selected.filter(id => id !== source.case_id))} />
        {source.snapshot.title}
      </label>
      <small>{source.collections.map(collection => collection.name).join("、") || source.label}{source.locator ? ` · ${source.locator}` : ""} · {source.match_reason}</small>
      {preview && <details><summary>{pick("View case", "查看用例")}</summary>
        <p>{source.snapshot.preconditions.join("；")}</p>
        <ol>{source.snapshot.steps.map((step, index) => <li key={index}>{step.action} → {step.expected}</li>)}</ol>
      </details>}
    </div>)}
    </div>
    <button type="button" disabled={busy || (!!selection.target_points?.length && !scope.length) || (selection.strategy === "select" && selected.length === 0)} onClick={onConfirm}>
      {selection.strategy === "select" ? pick("Confirm selection and form collection", "确认选用并组成集合") : modifying ? pick("Confirm references and continue changes", "确认参考并继续修改") : scoped ? pick("Confirm sources and affected points", "确认来源与影响范围") : selected.length ? pick("Confirm reuse and start planning", "确认复用并开始规划") : pick("Continue planning without reuse", "不复用，继续规划")}
    </button>
  </section>;
}
