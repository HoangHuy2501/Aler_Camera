"use client";

import { useEffect, useState } from "react";

const labels = {
  person: "Phát hiện người",
  motion: "Chuyển động",
  intrusion: "Xâm nhập",
};

type Kind = keyof typeof labels;
type Schedule = { start: string; end: string };
type Alert = { id: number; camera: string; kind: Kind; occurred_at: string };

const formatter = new Intl.DateTimeFormat("vi-VN", {
  dateStyle: "short",
  timeStyle: "medium",
  timeZone: "Asia/Ho_Chi_Minh",
});

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    method,
    cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`API trả về lỗi HTTP ${response.status}.`);
  return response.json() as Promise<T>;
}

export default function Dashboard() {
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [kind, setKind] = useState<Kind>("person");
  const [testTime, setTestTime] = useState("23:00");
  const [status, setStatus] = useState("");
  const [busy, setBusy] = useState(true);

  async function run(action: () => Promise<string>) {
    setBusy(true);
    setStatus("");
    try {
      setStatus(await action());
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Không thể kết nối server.");
    } finally {
      setBusy(false);
    }
  }

  async function load() {
    const [saved, latest] = await Promise.all([
      request<Schedule>("schedule"),
      request<Alert[]>("alerts"),
    ]);
    setSchedule(saved);
    setAlerts(latest);
    return "Đã tải dữ liệu.";
  }

  useEffect(() => { void run(load); }, []);

  return (
    <main>
      <h1>Cảnh báo camera</h1>
      <section>
        <h2>Khung giờ cảnh báo</h2>
        <p>Giờ Việt Nam. Hai mốc bằng nhau sẽ bật cảnh báo cả ngày.</p>
        {schedule ? (
          <form onSubmit={(event) => {
            event.preventDefault();
            void run(async () => {
              setSchedule(await request<Schedule>("schedule", "PUT", schedule));
              return "Đã lưu khung giờ.";
            });
          }}>
            <label>Bắt đầu<input type="time" required value={schedule.start} disabled={busy}
              onChange={(event) => setSchedule({ ...schedule, start: event.target.value })} /></label>
            <label>Kết thúc<input type="time" required value={schedule.end} disabled={busy}
              onChange={(event) => setSchedule({ ...schedule, end: event.target.value })} /></label>
            <button disabled={busy}>Lưu khung giờ</button>
          </form>
        ) : <button disabled={busy} onClick={() => void run(load)}>Thử tải lại</button>}
      </section>
      <section>
        <h2>Mô phỏng sự kiện</h2>
        <form onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            const result = await request<{ accepted: boolean }>("demo/events", "POST", {
              kind, test_time: testTime || null,
            });
            setAlerts(await request<Alert[]>("alerts"));
            return result.accepted ? "Đã lưu cảnh báo mô phỏng." : "Sự kiện nằm ngoài khung giờ đã lưu.";
          });
        }}>
          <label>Loại sự kiện<select value={kind} disabled={busy}
            onChange={(event) => setKind(event.target.value as Kind)}>
            {Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select></label>
          <label>Giờ thử (bỏ trống để dùng giờ hiện tại)
            <input type="time" value={testTime} disabled={busy} onChange={(event) => setTestTime(event.target.value)} />
          </label>
          <button disabled={busy || !schedule}>Gửi sự kiện</button>
        </form>
        <p role="status">{status}</p>
      </section>
      <section>
        <h2>Lịch sử cảnh báo</h2>
        {alerts.length ? (
          <ul>{alerts.map((alert) => (
            <li key={alert.id}>
              <strong>{labels[alert.kind]}</strong> · {alert.camera} · {formatter.format(new Date(alert.occurred_at))}
            </li>
          ))}</ul>
        ) : <p>Chưa có cảnh báo.</p>}
      </section>
    </main>
  );
}
