"use client";

import { Streamdown } from "streamdown";
import { useI18n } from "@/lib/i18n";

/** Keep the original confirmation accessible; never reconstruct its authorization scope. */
export function CompactModificationConfirmation({ content, historical = false }: { content: string; historical?: boolean }) {
  const { pick } = useI18n();
  const heading = content.split("\n")[0];
  const instruction = content.match(/(?:修改要求|Modification requirements|Modification request)[:：]\s*\n([\s\S]*?)(?:\n\n|$)/i)?.[1];
  return <section className="compact-confirmation" aria-label={pick("Modification scope", "修改范围确认")}>
    <strong>{heading || pick("Review modification scope", "请确认修改范围")}</strong>
    {!historical && instruction && <p className="compact-confirmation__instruction">{instruction}</p>}
    <details>
      <summary>{historical ? pick("View earlier confirmation", "查看此前确认内容") : pick("Review affected cases and full request", "查看影响用例及完整要求")}</summary>
      <div className="compact-confirmation__details"><Streamdown>{content}</Streamdown></div>
    </details>
    {!historical && <small>{pick("Confirm to prepare suggestions. Changes are saved only after review and acceptance.", "确认后生成建议，审阅采纳后才保存。")}</small>}
  </section>;
}
