# CONSILIUM web image. Multi-stage: build with full deps, run the slim
# standalone output (see next.config.mjs `output: "standalone"`).
FROM node:22-slim AS deps
WORKDIR /app
# corepack (bundled with node:22) provides pnpm per CLAUDE.md package-
# management rule. Node 22 is required because current pnpm needs node:sqlite.
RUN corepack enable
COPY package.json .npmrc ./
# No lockfile committed in the scaffold yet, so resolve fresh. Once a
# pnpm-lock.yaml exists, prefer `pnpm install --frozen-lockfile`.
#
# WHY the three-step dance: pnpm 11 refuses (exit 1) to run a dependency's
# native build script (here sharp, pulled in by Next.js) until it's approved,
# and — as of 11.9.0 — the declarative `onlyBuiltDependencies` allowlist is
# not honoured from package.json or pnpm-workspace.yaml. The reliable
# non-interactive escape hatch is: install once (populates node_modules, exits
# 1 on the unapproved build), approve all pending build scripts, then install
# again cleanly. Revisit once pnpm honours the declarative allowlist again.
RUN pnpm install || true \
    && pnpm approve-builds --all \
    && pnpm install

FROM node:22-slim AS builder
WORKDIR /app
RUN corepack enable
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Invoke Next's binary directly rather than via `pnpm run build`. pnpm 11 wraps
# every `run` with a deps-status check that shells out to `pnpm install`, which
# in this stage re-trips the unapproved-sharp-build error (the approval state
# lives in pnpm's config, not in the node_modules copied from deps). Calling the
# bin skips that check and builds against the already-complete node_modules.
RUN ./node_modules/.bin/next build

FROM node:22-slim AS runner
WORKDIR /app
ENV NODE_ENV=production
# Copy only the standalone server + static assets.
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
