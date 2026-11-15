"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "../api";
import { AuthCard, Notice, useAction } from "../ui";

export default function ResetPassword() {
  const [token, setToken] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  const action = useAction();

  useEffect(() => {
    const value = new URLSearchParams(window.location.hash.slice(1)).get("token") || "";
    setToken(/^[\w-]{43}$/.test(value) ? value : "");
  }, []);

  return <AuthCard title="Đặt lại mật khẩu">
    <Notice error={token === "" ? "Liên kết không hợp lệ." : action.error} message={action.message} />
    {!done && token && <form className="stack" onSubmit={(event) => {
      event.preventDefault();
      const body = new FormData(event.currentTarget);
      void action.run(async () => {
        const password = body.get("password");
        if (password !== body.get("confirm")) throw new Error("Mật khẩu nhập lại không khớp.");
        await api("auth/reset", "POST", { token, password });
        window.history.replaceState(null, "", window.location.pathname);
        setDone(true);
        return "Đã đặt lại mật khẩu.";
      });
    }}>
      <label>Mật khẩu mới<input name="password" type="password" autoComplete="new-password" required minLength={10} maxLength={128} /></label>
      <label>Nhập lại mật khẩu<input name="confirm" type="password" autoComplete="new-password" required minLength={10} maxLength={128} /></label>
      <button disabled={action.busy}>Cập nhật mật khẩu</button>
    </form>}
    <Link className="back-link" href="/">Về trang đăng nhập</Link>
  </AuthCard>;
}
