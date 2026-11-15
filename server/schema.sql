BEGIN;

CREATE TABLE IF NOT EXISTS users (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  email text NOT NULL UNIQUE CHECK (email = lower(email)),
  name text NOT NULL,
  role text NOT NULL CHECK (role IN ('admin', 'user')),
  password_hash text NOT NULL,
  active boolean NOT NULL DEFAULT true,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash bytea PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_user_idx ON sessions (user_id);
CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions (expires_at);

CREATE TABLE IF NOT EXISTS password_resets (
  token_hash bytea PRIMARY KEY,
  user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at timestamptz NOT NULL
);
CREATE INDEX IF NOT EXISTS resets_user_idx ON password_resets (user_id);
CREATE INDEX IF NOT EXISTS resets_expiry_idx ON password_resets (expires_at);

CREATE TABLE IF NOT EXISTS auth_limits (
  action text NOT NULL,
  identity text NOT NULL,
  bucket bigint NOT NULL,
  attempts integer NOT NULL,
  PRIMARY KEY (action, identity)
);

CREATE TABLE IF NOT EXISTS cameras (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  name text NOT NULL,
  source text NOT NULL CHECK (source IN ('onvif', 'frigate')),
  host text,
  port integer NOT NULL DEFAULT 80 CHECK (port BETWEEN 1 AND 65535),
  username text,
  secret bytea,
  rtsp_secret bytea,
  frigate_name text UNIQUE,
  intrusion_zone text,
  active boolean NOT NULL DEFAULT true,
  status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','connected','error')),
  status_at timestamptz,
  revision bigint NOT NULL DEFAULT 1,
  CHECK ((source = 'onvif' AND host IS NOT NULL AND frigate_name IS NULL)
      OR (source = 'frigate' AND frigate_name IS NOT NULL AND host IS NULL))
);

CREATE TABLE IF NOT EXISTS camera_access (
  user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  camera_id bigint NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, camera_id)
);
CREATE INDEX IF NOT EXISTS camera_access_camera_idx ON camera_access (camera_id);

CREATE TABLE IF NOT EXISTS schedules (
  user_id bigint PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  start_time time NOT NULL DEFAULT '22:00',
  end_time time NOT NULL DEFAULT '06:00',
  enabled boolean NOT NULL DEFAULT true,
  person boolean NOT NULL DEFAULT true,
  motion boolean NOT NULL DEFAULT true,
  intrusion boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS alerts (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  camera_id bigint NOT NULL REFERENCES cameras(id) ON DELETE CASCADE,
  kind text NOT NULL CHECK (kind IN ('person','motion','intrusion')),
  event_key text NOT NULL,
  occurred_at timestamptz NOT NULL,
  snapshot bytea,
  UNIQUE (camera_id, kind, event_key)
);
CREATE INDEX IF NOT EXISTS alerts_camera_time_idx ON alerts (camera_id, occurred_at DESC);

CREATE TABLE IF NOT EXISTS alert_recipients (
  user_id bigint NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  alert_id bigint NOT NULL REFERENCES alerts(id) ON DELETE CASCADE,
  PRIMARY KEY (user_id, alert_id)
);
CREATE INDEX IF NOT EXISTS alert_recipients_alert_idx ON alert_recipients (alert_id);

COMMIT;
