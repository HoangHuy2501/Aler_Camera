"use client";

import { FormEvent, useEffect, useState } from "react";
import { Account, CameraSettings, api, statusLabel } from "./api";
import { Notice, useAction } from "./ui";

export function CameraAdmin() {
  const [cameras, setCameras] = useState<CameraSettings[]>([]);
  const [editing, setEditing] = useState<CameraSettings | null | undefined>(undefined);
  const action = useAction();

  async function load() {
    setCameras(await api<CameraSettings[]>("admin/cameras"));
  }

  useEffect(() => { void action.run(load); }, []); // Initial list load.

  return <>
    <div className="heading"><div><h1>Camera</h1><p>{cameras.length}/20 camera</p></div>
      <button onClick={() => setEditing(null)} disabled={cameras.length >= 20}>Thêm camera</button>
    </div>
    <Notice {...action} />
    {editing !== undefined && <CameraForm key={editing?.id ?? "new"} camera={editing} onCancel={() => setEditing(undefined)}
      onSave={async (updated) => {
        setCameras((previous) => editing ? previous.map((camera) => camera.id === updated.id ? updated : camera) : [...previous, updated]);
        setEditing(undefined);
      }} />}
    <section className="panel">
      <div className="section-head"><h2>Danh sách camera</h2><button className="secondary" disabled={action.busy} onClick={() => void action.run(load)}>Làm mới</button></div>
      {cameras.length === 0 ? <p className="empty">{action.busy ? "Đang tải camera…" : "Chưa có camera."}</p> : (
        <ul className="records">{cameras.map((camera) => <li key={camera.id}>
          <div className="details"><strong>{camera.name}</strong><span>{camera.source === "onvif" ? `ONVIF · ${camera.host}:${camera.port} · ID ${camera.id}` : camera.source === "frigate" ? `Frigate · ${camera.frigate_name}` : `Imou Cloud · Kênh ${camera.imou_channel_id} · ID ${camera.id}`}</span></div>
          <span className="badge">{statusLabel(camera)}</span>
          <div className="record-actions">
            <button className="secondary" onClick={() => setEditing(camera)}>Chỉnh sửa</button>
            <button className="danger" disabled={action.busy} onClick={() => {
              if (!window.confirm(`Xóa camera “${camera.name}” và lịch sử cảnh báo của camera này?`)) return;
              void action.run(async () => {
                await api(`admin/cameras/${camera.id}`, "DELETE");
                setCameras((previous) => previous.filter((item) => item.id !== camera.id));
                if (editing?.id === camera.id) setEditing(undefined);
                return "Đã xóa camera.";
              });
            }}>Xóa</button>
          </div>
        </li>)}</ul>
      )}
    </section>
  </>;
}

function CameraForm({ camera, onSave, onCancel }: {
  camera: CameraSettings | null; onSave: (camera: CameraSettings) => Promise<void>; onCancel: () => void;
}) {
  const [source, setSource] = useState(camera?.source || "onvif");
  const action = useAction();
  const sameSource = camera?.source === source;

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const value = (name: string) => String(data.get(name) ?? "").trim() || null;
    const password = data.get("password");
    const payload = {
      name: value("name"), source, active: data.has("active"),
      host: value("host"), port: Number(data.get("port") || 80), username: value("username"),
      password: data.has("clear_password") ? "" : password || null,
      rtsp_url: data.has("clear_rtsp") ? "" : value("rtsp_url"),
      frigate_name: value("frigate_name"), intrusion_zone: value("intrusion_zone"),
      imou_device_id: value("imou_device_id"), imou_channel_id: value("imou_channel_id"),
    };
    void action.run(async () => {
      await onSave(await api<CameraSettings>(camera ? `admin/cameras/${camera.id}` : "admin/cameras", camera ? "PUT" : "POST", payload));
    });
  }

  return <section className="panel"><h2>{camera ? "Chỉnh sửa camera" : "Thêm camera"}</h2>
    <form className="stack" onSubmit={submit}>
      <div className="fields">
        <label>Tên hiển thị<input name="name" defaultValue={camera?.name} required maxLength={100} /></label>
        <label>Nguồn sự kiện<select value={source} onChange={(event) => setSource(event.target.value as CameraSettings["source"])}>
          <option value="onvif">ONVIF trực tiếp</option><option value="frigate">Frigate cục bộ</option><option value="imou">Imou Cloud</option>
        </select></label>
      </div>
      {source === "onvif" ? <>
        <div className="fields">
          <label>IP hoặc tên máy<input name="host" placeholder="192.168.1.25" defaultValue={camera?.host ?? ""} required /></label>
          <label>Cổng ONVIF<input name="port" type="number" min={1} max={65535} defaultValue={sameSource ? camera?.port : 80} required /></label>
        </div>
        <div className="fields">
          <label>Tên đăng nhập camera<input name="username" autoComplete="off" defaultValue={camera?.username ?? ""} maxLength={128} /></label>
          <label>Mật khẩu camera<input name="password" type="password" autoComplete="new-password" maxLength={256} placeholder={sameSource && camera?.has_password ? "Giữ mật khẩu đã lưu" : undefined} /></label>
        </div>
        {sameSource && camera?.has_password && <label className="check"><input type="checkbox" name="clear_password" /> Xóa mật khẩu camera đã lưu</label>}
      </> : source === "frigate" ? <div key="frigate-fields" className="fields">
        <label>Tên camera trong Frigate<input name="frigate_name" defaultValue={camera?.frigate_name ?? ""} required maxLength={80} /></label>
        <label>Vùng xâm nhập<input name="intrusion_zone" defaultValue={camera?.intrusion_zone ?? ""} maxLength={80} placeholder="Ví dụ: san_truoc" /></label>
      </div> : <div key="imou-fields" className="fields">
        <label>Số serial camera<input name="imou_device_id" defaultValue={camera?.imou_device_id ?? ""} required maxLength={100} /></label>
        <label>Kênh camera<input name="imou_channel_id" defaultValue={camera?.imou_channel_id ?? "0"} required pattern="[0-9]{1,4}" /></label>
      </div>}
      {source !== "imou" && <label>Địa chỉ RTSP lấy ảnh dự phòng<input key={source} name="rtsp_url" type="password" autoComplete="new-password" maxLength={2048} placeholder={sameSource && camera?.has_rtsp ? "Giữ địa chỉ đã lưu" : "rtsp://…"} /></label>}
      {source !== "imou" && sameSource && camera?.has_rtsp && <label className="check"><input type="checkbox" name="clear_rtsp" /> Xóa địa chỉ RTSP đã lưu</label>}
      <label className="check"><input type="checkbox" name="active" defaultChecked={camera?.active ?? true} /> Bật camera</label>
      <Notice {...action} />
      <div className="record-actions"><button disabled={action.busy}>Lưu camera</button><button type="button" className="secondary" disabled={action.busy} onClick={onCancel}>Hủy</button></div>
    </form>
  </section>;
}

export function UserAdmin() {
  const [accounts, setAccounts] = useState<Account[]>([]);
  const [cameras, setCameras] = useState<CameraSettings[]>([]);
  const [creating, setCreating] = useState(false);
  const [selected, setSelected] = useState<Account>();
  const action = useAction();

  useEffect(() => {
    void action.run(async () => {
      const [users, available] = await Promise.all([api<Account[]>("admin/users"), api<CameraSettings[]>("admin/cameras")]);
      setAccounts(users);
      setCameras(available);
    });
  }, []); // Initial account and camera list load.

  return <>
    <div className="heading"><div><h1>Người dùng</h1><p>Quản lý tài khoản và quyền xem camera.</p></div><button onClick={() => setCreating(!creating)}>Tạo tài khoản</button></div>
    <Notice {...action} />
    {creating && <section className="panel form-panel"><h2>Tài khoản mới</h2>
      <form className="stack" onSubmit={(event) => {
        event.preventDefault();
        const body = Object.fromEntries(new FormData(event.currentTarget));
        void action.run(async () => {
          const account = await api<Account>("admin/users", "POST", body);
          setAccounts((previous) => [account, ...previous]);
          setCreating(false);
          setSelected(account);
          return "Đã tạo tài khoản. Chọn camera để cấp quyền.";
        });
      }}>
        <label>Họ và tên<input name="name" required maxLength={100} /></label>
        <label>Email<input name="email" type="email" required /></label>
        <label>Mật khẩu ban đầu<input name="password" type="password" minLength={10} maxLength={128} autoComplete="new-password" required /></label>
        <p className="muted">Mật khẩu có ít nhất 10 ký tự.</p>
        <button className="fit" disabled={action.busy}>Tạo người dùng</button>
      </form>
    </section>}
    <section className="panel"><h2>Danh sách người dùng</h2>
      {accounts.length === 0 ? <p className="empty">{action.busy ? "Đang tải người dùng…" : "Chưa có người dùng."}</p> :
        <ul className="records">{accounts.map((account) => <li key={account.id}>
          <div className="details"><strong>{account.name}</strong><span>{account.email}</span></div>
          <span className="badge">{account.active ? "Đang hoạt động" : "Đã khóa"}</span>
          <button className="secondary" onClick={() => setSelected(account)}>Quản lý</button>
        </li>)}</ul>}
    </section>
    {selected && <AccountSettings key={selected.id} account={selected} cameras={cameras} onChange={(updated) => {
      setAccounts((previous) => previous.map((account) => account.id === updated.id ? updated : account));
      setSelected(updated);
    }} onClose={() => setSelected(undefined)} />}
  </>;
}

function AccountSettings({ account, cameras, onChange, onClose }: {
  account: Account; cameras: CameraSettings[]; onChange: (account: Account) => void; onClose: () => void;
}) {
  const access = useAction();
  const password = useAction();
  return <section className="panel">
    <div className="section-head"><h2>{account.name}</h2><button className="secondary" onClick={onClose}>Đóng</button></div>
    <div className="fields settings-columns">
      <form className="stack" onSubmit={(event) => {
        event.preventDefault();
        const data = new FormData(event.currentTarget);
        const body = { active: data.has("active"), camera_ids: data.getAll("camera_ids").map(Number) };
        void access.run(async () => {
          await api(`admin/users/${account.id}/access`, "PUT", body);
          onChange({ ...account, ...body });
          return "Đã lưu quyền truy cập.";
        });
      }}>
        <label className="check"><input name="active" type="checkbox" defaultChecked={account.active} /> Tài khoản hoạt động</label>
        <fieldset><legend>Quyền xem camera</legend>
          {cameras.length === 0 && <p className="muted">Chưa có camera để cấp quyền.</p>}
          {cameras.map((camera) => <label className="check" key={camera.id}>
            <input type="checkbox" name="camera_ids" value={camera.id} defaultChecked={account.camera_ids.includes(camera.id)} /> {camera.name}
          </label>)}
        </fieldset>
        <Notice {...access} />
        <button className="fit" disabled={access.busy}>Lưu quyền</button>
      </form>
      <form className="stack" onSubmit={(event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const value = new FormData(form).get("password");
        void password.run(async () => {
          await api(`admin/users/${account.id}/password`, "POST", { password: value });
          form.reset();
          return "Đã đổi mật khẩu và kết thúc các phiên cũ.";
        });
      }}>
        <label>Mật khẩu mới<input type="password" name="password" required minLength={10} maxLength={128} autoComplete="new-password" /></label>
        <Notice {...password} />
        <button className="fit secondary" disabled={password.busy}>Đổi mật khẩu</button>
      </form>
    </div>
  </section>;
}
