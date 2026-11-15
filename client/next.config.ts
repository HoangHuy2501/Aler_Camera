import type { NextConfig } from "next";

const config: NextConfig = {
  async rewrites() {
    const api = (process.env.CAMERA_API_URL || "http://127.0.0.1:8000").replace(/\/$/, "");
    return [
      { source: "/api/schedule", destination: `${api}/schedule` },
      { source: "/api/alerts", destination: `${api}/alerts` },
      { source: "/api/demo/events", destination: `${api}/demo/events` },
    ];
  },
};

export default config;
