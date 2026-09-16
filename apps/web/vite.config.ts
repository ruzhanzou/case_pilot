import vinext from "vinext";
import { defineConfig } from "vite";
import { sites } from "./build/sites-vite-plugin";

const SITE_CREATOR_PLACEHOLDER_DATABASE_ID =
  "00000000-0000-4000-8000-000000000000";

// Vinext's development overlay treats Chrome's benign ResizeObserver delivery
// notifications as fatal script errors. React Flow can legitimately produce one
// while its container is resized, so filter only those browser notifications and
// keep the overlay enabled for every real runtime error.
const ignoreResizeObserverDeliveryOverlay = {
  name: "casepilot-ignore-resize-observer-delivery-overlay",
  apply: "serve" as const,
  enforce: "pre" as const,
  transform(code: string, id: string) {
    if (!id.includes("vinext/dist/server/dev-error-overlay.js")) return null;
    const marker =
      'window.addEventListener("error", (event) => {\n\t\tconst err = event.error;';
    if (!code.includes(marker)) return null;
    return code.replace(
      marker,
      'window.addEventListener("error", (event) => {\n' +
        '\t\tif (/^ResizeObserver loop (?:completed with undelivered notifications|limit exceeded)\\.?$/.test(event.message || "")) {\n' +
        "\t\t\tevent.preventDefault();\n" +
        "\t\t\treturn;\n" +
        "\t\t}\n" +
        "\t\tconst err = event.error;",
    );
  },
};

// CasePilot currently uses PostgreSQL and Redis, so no Cloudflare D1/R2
// bindings are required for a clean public checkout.
const d1: string | null = null;
const r2: string | null = null;

// macOS Seatbelt blocks FSEvents, so Codex previews need polling for HMR.
const isCodexSeatbeltSandbox = process.env.CODEX_SANDBOX === "seatbelt";

const localBindingConfig = {
  main: "./worker/index.ts",
  compatibility_flags: ["nodejs_compat"],
  d1_databases: d1
    ? [
        {
          binding: d1,
          database_name: "site-creator-d1",
          database_id: SITE_CREATOR_PLACEHOLDER_DATABASE_ID,
        },
      ]
    : [],
  r2_buckets: r2
    ? [
        {
          binding: r2,
          bucket_name: "site-creator-r2",
        },
      ]
    : [],
};

export default defineConfig(async () => {
  // Keep Wrangler and Miniflare state project-local. These are non-secret tool
  // settings; application environment belongs in ignored `.env*` files.
  process.env.WRANGLER_WRITE_LOGS ??= "false";
  process.env.WRANGLER_LOG_PATH ??= ".wrangler/logs";
  process.env.MINIFLARE_REGISTRY_PATH ??= ".wrangler/registry";

  // Wrangler snapshots its log path while the Cloudflare plugin is imported.
  const { cloudflare } = await import("@cloudflare/vite-plugin");

  return {
    server: isCodexSeatbeltSandbox
      ? { watch: { useFsEvents: false, usePolling: true } }
      : undefined,
    plugins: [
      ignoreResizeObserverDeliveryOverlay,
      vinext(),
      sites(),
      cloudflare({
        viteEnvironment: { name: "rsc", childEnvironments: ["ssr"] },
        config: localBindingConfig,
      }),
    ],
  };
});
