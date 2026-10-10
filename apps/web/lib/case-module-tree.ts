export function modulePath(value: string): string {
  return value.split("/").map((part) => part.trim()).filter(Boolean).join("/");
}

export function moduleAncestors(value: string): string[] {
  const parts = modulePath(value).split("/").filter(Boolean);
  return parts.map((_, index) => parts.slice(0, index + 1).join("/"));
}

export function isModuleWithin(value: string, parent: string): boolean {
  const path = modulePath(value);
  const root = modulePath(parent);
  return path === root || path.startsWith(`${root}/`);
}

/** Collapse only paths produced by the legacy planner; leave custom modules intact. */
export function planningModuleAliases(plan?: {
  feature_points: { id: string; module: string; name: string }[];
  test_points: { feature_point_ids: string[]; scenario?: string; title: string }[];
}): Record<string, string> {
  const aliases: Record<string, string> = {};
  for (const point of plan?.test_points ?? []) {
    const feature = plan?.feature_points.find(f => point.feature_point_ids.includes(f.id));
    if (!feature) continue;
    const parts = modulePath(feature.module).split("/").filter(Boolean);
    const append = (value: string) => {
      const part = value.trim().replaceAll("/", "／");
      if (part && parts.at(-1) !== part) parts.push(part);
    };
    append(feature.name);
    const canonical = parts.join("/");
    append(point.scenario ?? "");
    append(point.title);
    aliases[parts.join("/")] = canonical;
  }
  return aliases;
}
