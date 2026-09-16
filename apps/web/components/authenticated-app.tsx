"use client";

import { CaseManagementApp } from "@/components/case-management-app";
import {
  getCurrentAccount,
  loginAccount,
  logoutAccount,
  registerAccount,
  type Account,
} from "@/lib/casepilot-api";
import type { CasePilotRoute } from "@/lib/casepilot-route";
import { I18nProvider, LanguageSwitcher, useI18n } from "@/lib/i18n";
import { AnimatePresence, motion } from "motion/react";
import {
  ArrowRight,
  CheckCircle2,
  ClipboardCheck,
  LoaderCircle,
} from "lucide-react";
import { useEffect, useState } from "react";

type AuthMode = "login" | "register";

const demoCredentials = {
  display_name: "体验用户",
  email: "demo@casepilot.local",
  password: "CasePilot123!",
};

export function AuthenticatedApp({ route }: { route: CasePilotRoute }) {
  return (
    <I18nProvider>
      <AuthenticatedAppContent route={route} />
    </I18nProvider>
  );
}

function AuthenticatedAppContent({ route }: { route: CasePilotRoute }) {
  const { t } = useI18n();
  const [account, setAccount] = useState<Account | null>(null);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [mode, setMode] = useState<AuthMode>("login");
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    void getCurrentAccount()
      .then((result) => active && setAccount(result))
      .catch(() => undefined)
      .finally(() => active && setLoading(false));
    return () => {
      active = false;
    };
  }, []);

  const submit = async (formData: FormData) => {
    setSubmitting(true);
    setError("");
    const email = String(formData.get("email") ?? "");
    const password = String(formData.get("password") ?? "");
    try {
      const result =
        mode === "login"
          ? await loginAccount({ email, password })
          : await registerAccount({
              display_name: String(formData.get("display_name") ?? ""),
              email,
              password,
            });
      setAccount(result);
    } catch (caught) {
      const code = caught instanceof Error ? caught.message : "";
      setError(
        code === "invalid_credentials"
          ? t("auth.error.invalid")
          : code === "email_already_registered"
            ? t("auth.error.exists")
            : t("auth.error.offline"),
      );
    } finally {
      setSubmitting(false);
    }
  };

  const logout = async () => {
    await logoutAccount().catch(() => undefined);
    setAccount(null);
    setMode("login");
  };

  if (loading) {
    return (
      <main className="auth-loading">
        <LanguageSwitcher />
        <LoaderCircle size={24} className="auth-spinner" />
        <span>{t("auth.loading")}</span>
      </main>
    );
  }

  if (account) {
    return (
      <CaseManagementApp account={account} onLogout={logout} route={route} />
    );
  }

  return (
    <main className="auth-shell">
      <LanguageSwitcher />
      <section className="auth-story">
        <div className="auth-brand"><ClipboardCheck size={18} />CasePilot</div>
        <div>
          <span className="eyebrow">{t("auth.eyebrow")}</span>
          <h1>{t("auth.title.line1")}<br />{t("auth.title.line2")}</h1>
          <p>{t("auth.description")}</p>
        </div>
        <div className="auth-flow">
          <span><b>01</b>{t("auth.step.login")}</span>
          <span><b>02</b>{t("auth.step.manage")}</span>
          <span><b>03</b>{t("auth.step.execute")}</span>
        </div>
      </section>

      <section className="auth-card" aria-labelledby="auth-title">
        <AnimatePresence mode="wait">
          <motion.div
            key={mode}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
          >
            <div className="auth-card__head">
              <span className="auth-card__mark"><CheckCircle2 size={20} /></span>
              <h2 id="auth-title">{mode === "login" ? t("auth.welcome") : t("auth.createAccount")}</h2>
              <p>{mode === "login" ? t("auth.loginHint") : t("auth.registerHint")}</p>
            </div>
            <form action={submit} className="auth-form">
              {mode === "register" && (
                <label>
                  {t("auth.displayName")}
                  <input
                    name="display_name"
                    defaultValue={demoCredentials.display_name}
                    autoComplete="name"
                    required
                  />
                </label>
              )}
              <label>
                {t("auth.email")}
                <input
                  name="email"
                  type="email"
                  defaultValue={demoCredentials.email}
                  autoComplete="email"
                  required
                />
              </label>
              <label>
                {t("auth.password")}
                <input
                  name="password"
                  type="password"
                  defaultValue={demoCredentials.password}
                  autoComplete={mode === "login" ? "current-password" : "new-password"}
                  minLength={10}
                  required
                />
              </label>
              {error && <div className="auth-error" role="alert">{error}</div>}
              <button className="auth-submit" type="submit" disabled={submitting}>
                {submitting ? <LoaderCircle size={16} className="auth-spinner" /> : null}
                {mode === "login" ? t("auth.loginSubmit") : t("auth.registerSubmit")}
                {!submitting && <ArrowRight size={16} />}
              </button>
            </form>
            <button
              className="auth-switch"
              type="button"
              onClick={() => {
                setMode(mode === "login" ? "register" : "login");
                setError("");
              }}
            >
              {mode === "login" ? t("auth.createPrompt") : t("auth.loginPrompt")}
            </button>
            <div className="auth-demo-note">
              <strong>{t("auth.demo")}</strong>
              <span>{demoCredentials.email} · {demoCredentials.password}</span>
            </div>
          </motion.div>
        </AnimatePresence>
      </section>
    </main>
  );
}
