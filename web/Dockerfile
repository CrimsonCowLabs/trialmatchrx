# The TrialMatch Rx web app (production Next build), as compose.yaml runs it. Built from the
# repo root:
#
#   docker build -f web/Dockerfile .
#
# NEXT_PUBLIC_API_URL is inlined into the client bundle at build time. It defaults to "" here,
# so the browser calls the API by relative path (`/api/...`) on whatever host served the page,
# and the same image works behind any hostname.

FROM node:22.22.0-slim AS build

# corepack reads the pnpm version from package.json's packageManager, so the lock is read the way
# it was written.
RUN corepack enable

WORKDIR /app/web

COPY web/package.json web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY web ./
ARG NEXT_PUBLIC_API_URL=""
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL \
    NEXT_TELEMETRY_DISABLED=1
RUN pnpm build


FROM node:22.22.0-slim

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    HOSTNAME=0.0.0.0 \
    PORT=3045

WORKDIR /app

# The standalone server carries only the node_modules it traces; static assets and public/
# are copied beside it, where server.js looks for them.
COPY --from=build --chown=node:node /app/web/.next/standalone ./
COPY --from=build --chown=node:node /app/web/.next/static ./.next/static
COPY --from=build --chown=node:node /app/web/public ./public

USER node

EXPOSE 3045

CMD ["node", "server.js"]
