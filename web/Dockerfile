# syntax=docker/dockerfile:1
# Next.js standalone image (build context: ./web). Both args are REQUIRED and baked into the rewrite table
# (web/lib/config.ts fails the build loudly otherwise):
#   docker build --build-arg NEXT_PUBLIC_API_BASE=/api --build-arg CONSOLE_API_ORIGIN=http://api:8766 -t actionproof-web web
ARG NODE_IMAGE=node:22-alpine

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --ignore-scripts

FROM ${NODE_IMAGE} AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_BASE
ARG CONSOLE_API_ORIGIN
ARG NEXT_PUBLIC_SITE_URL=
ARG NEXT_PUBLIC_REPO_URL=
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE} CONSOLE_API_ORIGIN=${CONSOLE_API_ORIGIN} NEXT_PUBLIC_SITE_URL=${NEXT_PUBLIC_SITE_URL} NEXT_PUBLIC_REPO_URL=${NEXT_PUBLIC_REPO_URL} NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Standalone output is required for this image. If next.config.ts does not set it yet, inject it for the image build
# only (the source file is untouched); once `output: "standalone"` is in next.config.ts this is a no-op.
RUN grep -q standalone next.config.ts || sed -i 's/reactStrictMode: true,/output: "standalone",\n  reactStrictMode: true,/' next.config.ts
RUN npm run build && test -f .next/standalone/server.js

FROM ${NODE_IMAGE} AS runner
WORKDIR /app
RUN addgroup -S -g 10001 app && adduser -S -u 10001 -G app app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=5173 HOSTNAME=0.0.0.0
COPY --from=build --chown=10001:10001 /app/.next/standalone ./
COPY --from=build --chown=10001:10001 /app/.next/static ./.next/static
USER 10001:10001
EXPOSE 5173
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:'+(process.env.PORT||5173)+'/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server.js"]
