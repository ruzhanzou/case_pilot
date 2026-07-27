const apiBaseUrl =
  process.env.NEXT_PUBLIC_CASEPILOT_API_URL ?? "http://localhost:8000";

export type Account = {
  id: string;
  email: string;
  display_name: string;
  spaces: {
    id: string;
    name: string;
    description: string;
    role: string;
  }[];
};

export type ExecutionStatusApi =
  | "not_run"
  | "passed"
  | "failed"
  | "skipped"
  | "blocked";

export type CaseStepDto = {
  id: string;
  action: string;
  expected: string;
};

export type CaseCollectionDto = {
  id: string;
  space_id: string;
  name: string;
  description: string;
  case_count: number;
  created_at: string;
};

export type TestCaseDto = {
  id: string;
  case_key: string;
  collection_ids: string[];
  current_revision_id: string;
  revision_number: number;
  title: string;
  module: string;
  priority: "P0" | "P1" | "P2";
  case_type: string;
  tags: string[];
  preconditions: string[];
  steps: CaseStepDto[];
  source: string;
  created_at: string;
};

export type TestCaseInput = {
  case_key?: string;
  title: string;
  module: string;
  priority: "P0" | "P1" | "P2";
  case_type: string;
  tags: string[];
  preconditions: string[];
  steps: {
    id?: string;
    action: string;
    expected: string;
  }[];
  source: string;
};

export type ExecutionRecordDto = {
  id: string;
  test_case: TestCaseDto;
  status: ExecutionStatusApi;
  completed_step_ids: string[];
  actual_result: string;
  defect_ref: string;
  updated_by_name: string | null;
  updated_at: string;
};

export type ExecutionRunDto = {
  id: string;
  collection_id: string;
  collection_name: string;
  description: string;
  status: string;
  creator_name: string;
  contributor_names: string[];
  created_at: string;
  last_activity_at: string;
  completed_at: string | null;
  records: ExecutionRecordDto[];
};

export type ExecutionRunSummaryDto = Omit<ExecutionRunDto, "records"> & {
  total_count: number;
  not_run_count: number;
  passed_count: number;
  failed_count: number;
  skipped_count: number;
  blocked_count: number;
};

async function apiRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(payload?.detail ?? `api_request_failed_${response.status}`);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function listCollections(spaceId: string): Promise<CaseCollectionDto[]> {
  return apiRequest(`/api/v1/spaces/${spaceId}/collections`);
}

export function createCollection(
  spaceId: string,
  input: { name: string; description: string },
): Promise<CaseCollectionDto> {
  return apiRequest(`/api/v1/spaces/${spaceId}/collections`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateCollection(
  collectionId: string,
  input: { name?: string; description?: string },
): Promise<CaseCollectionDto> {
  return apiRequest(`/api/v1/collections/${collectionId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteCollection(collectionId: string): Promise<void> {
  return apiRequest(`/api/v1/collections/${collectionId}`, {
    method: "DELETE",
  });
}

export function listTestCases(collectionId: string): Promise<TestCaseDto[]> {
  return apiRequest(`/api/v1/collections/${collectionId}/test-cases`);
}

export function createTestCase(
  collectionId: string,
  input: TestCaseInput,
): Promise<TestCaseDto> {
  return apiRequest(`/api/v1/collections/${collectionId}/test-cases`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function updateTestCase(
  caseId: string,
  input: TestCaseInput & { base_revision_id: string },
): Promise<TestCaseDto> {
  return apiRequest(`/api/v1/test-cases/${caseId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

export function deleteTestCase(caseId: string): Promise<void> {
  return apiRequest(`/api/v1/test-cases/${caseId}`, {
    method: "DELETE",
  });
}

export function createExecutionRun(
  collectionId: string,
  input: { description: string },
): Promise<ExecutionRunDto> {
  return apiRequest(`/api/v1/collections/${collectionId}/execution-runs`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function listExecutionRuns(
  collectionId: string,
): Promise<ExecutionRunSummaryDto[]> {
  return apiRequest(`/api/v1/collections/${collectionId}/execution-runs`);
}

export function listSpaceExecutionRuns(
  spaceId: string,
): Promise<ExecutionRunSummaryDto[]> {
  return apiRequest(`/api/v1/spaces/${spaceId}/execution-runs`);
}

export function getExecutionRun(runId: string): Promise<ExecutionRunDto> {
  return apiRequest(`/api/v1/execution-runs/${runId}`);
}

export function closeExecutionRun(
  runId: string,
  status: "completed" | "aborted",
): Promise<ExecutionRunDto> {
  return apiRequest(`/api/v1/execution-runs/${runId}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function updateExecutionRecord(
  recordId: string,
  input: {
    status: ExecutionStatusApi;
    completed_step_ids: string[];
    actual_result: string;
    defect_ref: string;
    base_updated_at: string;
  },
): Promise<ExecutionRecordDto> {
  return apiRequest(`/api/v1/execution-records/${recordId}`, {
    method: "PATCH",
    body: JSON.stringify(input),
  });
}

async function authRequest(
  path: string,
  init?: RequestInit,
): Promise<Account> {
  const response = await fetch(`${apiBaseUrl}/api/v1/auth${path}`, {
    ...init,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as
      | { detail?: string }
      | null;
    throw new Error(payload?.detail ?? `auth_request_failed_${response.status}`);
  }
  return response.json() as Promise<Account>;
}

export function getCurrentAccount(): Promise<Account> {
  return authRequest("/me");
}

export function loginAccount(input: {
  email: string;
  password: string;
}): Promise<Account> {
  return authRequest("/login", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function registerAccount(input: {
  display_name: string;
  email: string;
  password: string;
}): Promise<Account> {
  return authRequest("/register", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export async function logoutAccount(): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/api/v1/auth/logout`, {
    method: "POST",
    credentials: "include",
  });
  if (!response.ok && response.status !== 401) {
    throw new Error(`logout_failed_${response.status}`);
  }
}
