"use client";

import { FormEvent, ReactNode, useState } from "react";
import { api } from "./api";

export function Mark() {
  return <span className="mark" aria-hidden="true"><svg width="21" height="21" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="5" width="18" height="14" rx="3"/><circle cx="12" cy="12" r="3.5"/><path d="M17.5 8h.1"/></svg></span>;
}

export function Notice({ error, message }: { error: string; message?: string }) {
  if (error) return <p className="notice error" role="alert">{error}</p>;
  return message ? <p className="notice success" role="status">{message}</p> : null;
}

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  async function run(action: () => Promise<string | void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setMessage((await action()) || "");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Đã xảy ra lỗi.");
    } finally {
      setBusy(false);
    }
  }

  return { busy, error, message, run };
}

export function AuthCard({ title, children }: { title: string; children: ReactNode }) {
  return <main className="auth-shell">
    <section className="panel auth-card">
      <div className="brand"><Mark /> Cảnh báo camera</div>
      <h1>{title}</h1>
      {children}
    </section>
  </main>;
}

export function Login({ onLogin }: { onLogin: () => void }) {
  const [forgot, setForgot] = useState(false);
  return <AuthCard title={forgot ? "Khôi phục mật khẩu" : "Đăng nhập"}>
    {forgot ? <Forgot onBack={() => setForgot(false)} /> : <LoginForm onForgot={() => setForgot(true)} onLogin={onLogin} />}
  </AuthCard>;
}

function LoginForm({ onForgot, onLogin }: { onForgot: () => void; onLogin: () => void }) {
  const action = useAction();
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = Object.fromEntries(new FormData(event.currentTarget));
    void action.run(async () => {
      await api("auth/login", "POST", body);
      onLogin();
    });
  }
  return <form className="stack" onSubmit={submit}>
    <label>Email<input type="email" name="email" autoComplete="username" required /></label>
    <label>Mật khẩu<input type="password" name="password" autoComplete="current-password" required maxLength={128} /></label>
    <Notice {...action} />
    <button disabled={action.busy}>Đăng nhập</button>
    <button type="button" className="text-button" onClick={onForgot}>Quên mật khẩu?</button>
  </form>;
}

function Forgot({ onBack }: { onBack: () => void }) {
  const action = useAction();
  return <form className="stack" onSubmit={(event) => {
    event.preventDefault();
    const email = new FormData(event.currentTarget).get("email");
    void action.run(async () => {
      await api("auth/forgot", "POST", { email });
      return "Nếu email thuộc tài khoản đang hoạt động, bạn sẽ nhận được liên kết đặt lại mật khẩu.";
    });
  }}>
    <label>Email<input type="email" name="email" autoComplete="email" required /></label>
    <Notice {...action} />
    <button disabled={action.busy}>Gửi liên kết</button>
    <button type="button" className="text-button" onClick={onBack}>Quay lại đăng nhập</button>
  </form>;
}
