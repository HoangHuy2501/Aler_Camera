"use client";

import { useEffect, useState } from "react";
import { Alert, ApiError, Camera, Kind, Schedule, api, statusLabel, types } from "./api";
import { Notice, useAction } from "./ui";

const formatter = new Intl.DateTimeFormat("vi-VN", {
  dateStyle: "short", timeStyle: "medium", timeZone: "Asia/Ho_Chi_Minh",
});

export function AlertFeed({ onExpired }: { onExpired: () => void }) {
  const [alerts, setAlerts] = useState<Alert[] | null>(null);
  const [cameras, setCameras] = useState<Camera[]>([]);
  const [cameraId, setCameraId] = useState("");
  const [kind, setKind] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function refresh() {
      const query = new URLSearchParams();
      if (cameraId) query.set("camera_id", cameraId);
      if (kind) query.set("kind", kind);
      try {
        const [items, available] = await Promise.all([api<Alert[]>(`alerts?${query}`), api<Camera[]>("cameras")]);
        if (cancelled) return;
        setAlerts(items);
        setCameras(available);
        if (cameraId && !available.some((camera) => String(camera.id) === cameraId)) setCameraId("");
        setError("");
      } catch (failure) {
        if (cancelled) return;
        if (failure instanceof ApiError && failure.status === 401) onExpired();
        else setError(failure instanceof Error ? failure.message : "Không tải được cảnh báo.");
      } finally {
        if (!cancelled) timer = setTimeout(refresh, 5000);
      }
    }
    void refresh();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [cameraId, kind, onExpired]);

  return <>
    <div className="heading"><div><h1>Cảnh báo</h1><p>Tự cập nhật mỗi 5 giây · Giờ Việt Nam</p></div></div>
    <section className="camera-strip" aria-label="Camera được cấp quyền">
      {cameras.map((camera) => <button type="button" key={camera.id} className={cameraId === String(camera.id) ? "camera-tile selected" : "camera-tile"} onClick={() => setCameraId(cameraId === String(camera.id) ? "" : String(camera.id))} aria-pressed={cameraId === String(camera.id)}>
        <strong>{camera.name}</strong><span className={camera.active && statusLabel(camera) === "Đã kết nối" ? "dot online" : "dot"}>{statusLabel(camera)}</span>
      </button>)}
    </section>
    <section className="panel feed" aria-label="Lịch sử cảnh báo">
      <div className="section-head">
        <h2>Lịch sử cảnh báo</h2>
        <div className="filters">
          <select aria-label="Lọc theo camera" value={cameraId} onChange={(event) => { setAlerts(null); setCameraId(event.target.value); }}>
            <option value="">Tất cả camera</option>
            {cameras.map((camera) => <option key={camera.id} value={camera.id}>{camera.name}</option>)}
          </select>
          <select aria-label="Lọc theo sự kiện" value={kind} onChange={(event) => { setAlerts(null); setKind(event.target.value); }}>
            <option value="">Tất cả sự kiện</option>
            {Object.entries(types).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
          </select>
        </div>
      </div>
      <Notice error={error} />
      {alerts === null ? <p className="empty">Đang tải cảnh báo…</p> : alerts.length === 0 ? <p className="empty">Chưa có cảnh báo phù hợp.</p> : (
        <ul className="alerts">{alerts.map((alert) => <li key={alert.id}>
          <div className={`event-icon ${alert.kind}`} aria-hidden="true">
            {alert.kind === "person" ? "◎" : alert.kind === "motion" ? "↝" : "!"}
          </div>
          <div className="details"><strong>{types[alert.kind]}</strong><span>{alert.camera} · <time dateTime={alert.occurred_at}>{formatter.format(new Date(alert.occurred_at))}</time></span></div>
          {alert.has_snapshot ? <a className="snapshot" href={`/api/alerts/${alert.id}/snapshot`} target="_blank" rel="noreferrer">
            {/* The image is private and must use the current session cookie. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/api/alerts/${alert.id}/snapshot`} width={88} height={54} alt={`Ảnh từ ${alert.camera}`} loading="lazy" />
          </a> : <span className="muted">Chưa có ảnh</span>}
        </li>)}</ul>
      )}
    </section>
  </>;
}

export function ScheduleForm({ onExpired }: { onExpired: () => void }) {
  const [schedule, setSchedule] = useState<Schedule | null>(null);
  const [loadError, setLoadError] = useState("");
  const action = useAction();

  useEffect(() => {
    let cancelled = false;
    void api<Schedule>("schedule").then((result) => {
      if (!cancelled) setSchedule(result);
    }).catch((failure) => {
      if (cancelled) return;
      if (failure instanceof ApiError && failure.status === 401) onExpired();
      else setLoadError(failure.message);
    });
    return () => { cancelled = true; };
  }, [onExpired]);

  return <>
    <div className="heading"><div><h1>Lịch cảnh báo</h1><p>Áp dụng cho các camera bạn có quyền xem.</p></div></div>
    <section className="panel form-panel">
      <Notice error={loadError} />
      {schedule ? <form className="stack" onSubmit={(event) => {
        event.preventDefault();
        void action.run(async () => {
          try {
            setSchedule(await api<Schedule>("schedule", "PUT", schedule));
            return "Đã lưu lịch cảnh báo.";
          } catch (failure) {
            if (failure instanceof ApiError && failure.status === 401) onExpired();
            throw failure;
          }
        });
      }}>
        <label className="check"><input type="checkbox" checked={schedule.enabled} onChange={(event) => setSchedule({ ...schedule, enabled: event.target.checked })} /> Bật cảnh báo</label>
        <div className="fields">
          <label>Bắt đầu<input type="time" required value={schedule.start_time.slice(0, 5)} onChange={(event) => setSchedule({ ...schedule, start_time: event.target.value })} /></label>
          <label>Kết thúc<input type="time" required value={schedule.end_time.slice(0, 5)} onChange={(event) => setSchedule({ ...schedule, end_time: event.target.value })} /></label>
        </div>
        <p className="muted">Giờ Việt Nam. Hai mốc bằng nhau áp dụng cả ngày.</p>
        <fieldset><legend>Loại sự kiện</legend>
          {(Object.keys(types) as Kind[]).map((kind) => <label className="check" key={kind}>
            <input type="checkbox" checked={schedule[kind]} onChange={(event) => setSchedule({ ...schedule, [kind]: event.target.checked })} /> {types[kind]}
          </label>)}
        </fieldset>
        <Notice {...action} />
        <button className="fit" disabled={action.busy}>Lưu lịch</button>
      </form> : !loadError && <p>Đang tải lịch…</p>}
    </section>
  </>;
}
