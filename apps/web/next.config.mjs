/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // WHY standalone: produces a self-contained server bundle so the Docker
  // image can run `node server.js` without the full node_modules tree,
  // keeping the web image small.
  output: "standalone",
};

export default nextConfig;
