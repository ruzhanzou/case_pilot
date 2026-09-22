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
