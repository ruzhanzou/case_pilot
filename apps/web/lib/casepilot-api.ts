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

type GenerationJob = {
  id: string;
};

type GenerationEvent = {
  progress?: number;
};

export type GenerationCompleted = {
  risks: {
    id: string;
    severity: string;
    title: string;
    source: string;
  }[];
  test_cases: {
    id: string;
    title: string;
    status: string;
    preconditions: string[];
    steps: {
      action: string;
      expected: string;
    }[];
  }[];
};

export async function startMockGeneration(input: {
  prompt: string;
  fileNames: string[];
  spaceId: string;
  modelId: "auto" | "pro" | "local";
}): Promise<GenerationJob> {
  const response = await fetch(`${apiBaseUrl}/api/v1/generation-jobs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    credentials: "include",
    body: JSON.stringify({
      prompt: input.prompt,
      file_names: input.fileNames,
      space_id: input.spaceId,
      model_id: input.modelId,
    }),
  });

  if (!response.ok) {
    throw new Error(`Mock generation request failed: ${response.status}`);
  }

  return response.json() as Promise<GenerationJob>;
}

export function watchMockGeneration(
  jobId: string,
  onProgress: (progress: number) => void,
): Promise<GenerationCompleted> {
  return new Promise((resolve, reject) => {
    const source = new EventSource(
      `${apiBaseUrl}/api/v1/generation-jobs/${jobId}/events`,
      { withCredentials: true },
    );
    const timeout = window.setTimeout(() => {
      source.close();
      reject(new Error("Mock generation stream timed out"));
    }, 15_000);

    const finish = (callback: () => void) => {
      window.clearTimeout(timeout);
      source.close();
      callback();
    };

    source.addEventListener("generation.progress", (event) => {
      const payload = JSON.parse(
        (event as MessageEvent<string>).data,
      ) as GenerationEvent;
      onProgress(payload.progress ?? 0);
    });
    source.addEventListener("generation.completed", (event) => {
      const payload = JSON.parse(
        (event as MessageEvent<string>).data,
      ) as GenerationCompleted;
      finish(() => resolve(payload));
    });
    source.addEventListener("generation.failed", () =>
      finish(() => reject(new Error("Mock generation failed"))),
    );
    source.onerror = () =>
      finish(() => reject(new Error("Mock generation stream disconnected")));
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
