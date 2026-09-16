export type CasePilotRoute =
  | {
      page: "workbench";
      conversationId?: string;
      collectionId?: string;
    }
  | { page: "knowledge" }
  | { page: "library"; collectionId?: string; caseId?: string }
  | { page: "execution"; collectionId?: string };

function segment(value: string | undefined): string | undefined {
  return value ? decodeURIComponent(value) : undefined;
}

export function parseCasePilotRoute(
  routeSegments: string[] | undefined,
): CasePilotRoute {
  const [section, resource, id] = routeSegments ?? [];
  if (!section || section === "workbench") {
    if (resource === "conversations" && id) {
      return { page: "workbench", conversationId: segment(id) };
    }
    if (resource === "collections" && id) {
      return { page: "workbench", collectionId: segment(id) };
    }
    return { page: "workbench" };
  }
  if (section === "knowledge") return { page: "knowledge" };
  if (section === "cases") {
    return {
      page: "library",
      collectionId: segment(resource),
      caseId: segment(id),
    };
  }
  if (section === "executions") {
    return { page: "execution", collectionId: segment(resource) };
  }
  return { page: "workbench" };
}

function encode(value: string): string {
  return encodeURIComponent(value);
}

export function casePilotPath(route: CasePilotRoute): string {
  if (route.page === "knowledge") return "/knowledge";
  if (route.page === "execution") {
    return route.collectionId
      ? `/executions/${encode(route.collectionId)}`
      : "/executions";
  }
  if (route.page === "library") {
    if (!route.collectionId) return "/cases";
    const collectionPath = `/cases/${encode(route.collectionId)}`;
    return route.caseId
      ? `${collectionPath}/${encode(route.caseId)}`
      : collectionPath;
  }
  if (route.conversationId) {
    return `/workbench/conversations/${encode(route.conversationId)}`;
  }
  if (route.collectionId) {
    return `/workbench/collections/${encode(route.collectionId)}`;
  }
  return "/workbench";
}
