/** Readable provenance for the before/after review; keep original evidence verbatim. */
export function sourceRefText(value: unknown): string {
  if (!Array.isArray(value) || !value.length) return "—";
  return value.map((source, index) => {
    if (!source || typeof source !== "object") return `${index + 1}. ${String(source ?? "")}`;
    const heading = [source.label, source.locator].filter(item => typeof item === "string" && item).join(" / ");
    const excerpt = typeof source.excerpt === "string" ? source.excerpt : "";
    let detail = excerpt;
    try {
      const ref = JSON.parse(excerpt);
      if (ref && typeof ref === "object" && ref.source_key && ["reuse", "modify"].includes(ref.action)) {
        // Internal lookup keys and hashes are not useful review content.
        detail = [ref.case_key, ref.revision == null ? "" : `V${ref.revision}`, ref.reason]
          .filter(item => typeof item === "string" && item).join(" · ");
      }
    } catch { /* Plain text excerpts are evidence, not JSON. */ }
    return `${index + 1}. ${heading}${detail ? `\n${detail}` : ""}`;
  }).join("\n\n");
}
