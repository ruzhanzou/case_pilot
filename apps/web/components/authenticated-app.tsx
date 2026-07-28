"use client";

import { CaseManagementApp } from "@/components/case-management-app";
import {
  getCurrentAccount,
  loginAccount,
  logoutAccount,
  registerAccount,
  type Account,
} from "@/lib/casepilot-api";
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

export function AuthenticatedApp() {
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
          ? "邮箱或密码不正确"
          : code === "email_already_registered"
            ? "该邮箱已注册，请直接登录"
            : "本地数据服务尚未就绪，请确认 PostgreSQL 和 API 已启动",
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
        <LoaderCircle size={24} className="auth-spinner" />
        <span>正在连接本地工作区…</span>
      </main>
    );
  }

  if (account) {
    return <CaseManagementApp account={account} onLogout={logout} />;
  }

  return (
    <main className="auth-shell">
      <section className="auth-story">
        <div className="auth-brand"><ClipboardCheck size={18} />CasePilot</div>
        <div>
          <span className="eyebrow">TEST CASE MANAGEMENT WORKSPACE</span>
          <h1>管理、评审并执行<br />结构化测试用例。</h1>
          <p>登录后进入本地质量空间，维护用例集合、修订结构化用例，并记录每一次 QA 执行结果。</p>
        </div>
        <div className="auth-flow">
          <span><b>01</b>登录本地账号</span>
          <span><b>02</b>管理用例资产</span>
          <span><b>03</b>执行并留痕</span>
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
              <h2 id="auth-title">{mode === "login" ? "欢迎回来" : "创建本地账号"}</h2>
              <p>{mode === "login" ? "登录后继续用例管理与执行" : "账号与数据仅保存在本地环境"}</p>
            </div>
            <form action={submit} className="auth-form">
              {mode === "register" && (
                <label>
                  显示名称
                  <input
                    name="display_name"
                    defaultValue={demoCredentials.display_name}
                    autoComplete="name"
                    required
                  />
                </label>
              )}
              <label>
                邮箱
                <input
                  name="email"
                  type="email"
                  defaultValue={demoCredentials.email}
                  autoComplete="email"
                  required
                />
              </label>
              <label>
                密码
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
                {mode === "login" ? "登录并进入工作台" : "创建账号并进入"}
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
              {mode === "login" ? "第一次使用？创建本地账号" : "已有账号？返回登录"}
            </button>
            <div className="auth-demo-note">
              <strong>验收示例账号</strong>
              <span>{demoCredentials.email} · {demoCredentials.password}</span>
            </div>
          </motion.div>
        </AnimatePresence>
      </section>
    </main>
  );
}
