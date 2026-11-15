"use client";

import { useCallback, useEffect, useState } from "react";
import { CameraAdmin, UserAdmin } from "./admin";
import { ApiError, Session, api } from "./api";
import { AlertFeed, ScheduleForm } from "./dashboard";
import { AuthCard, Login, Mark, Notice, useAction } from "./ui";

type Tab = "alerts" | "schedule" | "cameras" | "users";
const tabs: Record<Tab, string> = { alerts: "Cảnh báo", schedule: "Lịch cảnh báo", cameras: "Camera", users: "Người dùng" };

export default function Home() {
  const [session, setSession] = useState<Session | null | undefined>(undefined);
  const [tab, setTab] = useState<Tab>("alerts");
  const [error, setError] = useState("");
  const action = useAction();

  const load = useCallback(async () => {
    setError("");
    try {
      setSession(await api<Session>("auth/me"));
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 401) setSession(null);
      else setError(failure instanceof Error ? failure.message : "Không thể tải tài khoản.");
    }
  }, []);
  const expired = useCallback(() => { setSession(null); setTab("alerts"); }, []);

  useEffect(() => { void load(); }, [load]);

  if (session === undefined || error) {
    return <AuthCard title={error ? "Không thể kết nối" : "Đang tải…"}>
      <Notice error={error} />
      {error && <button onClick={() => void load()}>Thử lại</button>}
    </AuthCard>;
  }
  if (!session) return <Login onLogin={() => void load()} />;

  return <div className="shell">
    <header className="topbar">
      <div className="topbar-inner">
        <div className="brand"><Mark /> Cảnh báo camera</div>
        <div className="account"><span>{session.name}<small>{session.role === "admin" ? "Quản trị viên" : "Người dùng"}</small></span>
          <button className="secondary" disabled={action.busy} onClick={() => void action.run(async () => {
            await api("auth/logout", "POST");
            expired();
          })}>Đăng xuất</button>
        </div>
      </div>
    </header>
    <div className="workspace">
      <nav aria-label="Điều hướng chính">
        {(Object.entries(tabs) as [Tab, string][]).filter(([name]) => session.role === "admin" || name === "alerts" || name === "schedule").map(([name, label]) =>
          <button key={name} type="button" aria-current={tab === name ? "page" : undefined} onClick={() => setTab(name)}>{label}</button>
        )}
      </nav>
      <main>
        <Notice {...action} />
        {tab === "alerts" && <AlertFeed onExpired={expired} />}
        {tab === "schedule" && <ScheduleForm onExpired={expired} />}
        {session.role === "admin" && tab === "cameras" && <CameraAdmin />}
        {session.role === "admin" && tab === "users" && <UserAdmin />}
      </main>
    </div>
  </div>;
}
