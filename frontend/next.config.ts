import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // Dev-only: the app is reached through nginx at this host's public IP
  // (see README "قرار البنية التحتية"), not localhost, so `next dev`'s
  // same-origin check for dev-only resources (HMR, etc.) must be told
  // that origin is expected — otherwise it silently rejects the HMR
  // channel with a console warning (harmless to page load, but noisy
  // and breaks hot-reload for anyone browsing via the public IP).
  allowedDevOrigins: ["154.41.209.222"],
};

export default nextConfig;
