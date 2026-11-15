export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function api<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api/${path}`, {
      method,
      cache: "no-store",
      headers: method === "GET" ? undefined : { "X-Camera-Request": "1", "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "Không thể kết nối máy chủ.");
  }
  if (!response.ok) {
    const error = await response.json().catch(() => null);
    throw new ApiError(response.status, typeof error?.detail === "string" ? error.detail : "Không thể xử lý yêu cầu.");
  }
  return response.status === 204 ? undefined as T : response.json() as Promise<T>;
}

export const types = {
  person: "Phát hiện người",
  motion: "Chuyển động",
  intrusion: "Xâm nhập",
};

export type Kind = keyof typeof types;
export type Session = { id: number; email: string; name: string; role: "admin" | "user" };
export type Camera = {
  id: number; name: string; source: "onvif" | "frigate"; active: boolean;
  status: "pending" | "connected" | "error"; status_at: string | null;
};
export type CameraSettings = Camera & {
  host: string | null; port: number; username: string | null; has_password: boolean;
  has_rtsp: boolean; frigate_name: string | null; intrusion_zone: string | null;
};
export type Account = Session & { active: boolean; camera_ids: number[] };
export type Schedule = Record<Kind, boolean> & { start_time: string; end_time: string; enabled: boolean };
export type Alert = { id: number; camera_id: number; camera: string; kind: Kind; occurred_at: string; has_snapshot: boolean };

export function statusLabel(camera: Camera) {
  if (!camera.active) return "Đã tắt";
  if (camera.status === "pending") return "Chờ kết nối";
  if (camera.status === "error") return "Mất kết nối";
  if (camera.status_at && Date.now() - Date.parse(camera.status_at) > 180_000) return "Chưa có cập nhật";
  return "Đã kết nối";
}
