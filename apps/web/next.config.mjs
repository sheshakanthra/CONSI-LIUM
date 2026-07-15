/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // WHY standalone: produces a self-contained server bundle so the Docker
  // image can run `node server.js` without the full node_modules tree,
  // keeping the web image small.
  output: "standalone",
  // WHY pin the tracing root: with `output: "standalone"` Next infers the
  // workspace root by walking up for a lockfile. Outside Docker that walk can
  // escape the repo entirely (any stray package-lock.json in a parent — e.g. a
  // developer's home directory — wins), and the traced bundle is then laid out
  // relative to *that* root, producing a mangled nested path and, on Windows, a
  // hard EPERM symlink failure. Pinning it to this app makes the build depend
  // on the repo alone, not on what happens to sit above the checkout.
  outputFileTracingRoot: import.meta.dirname,
};

export default nextConfig;
