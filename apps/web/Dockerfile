FROM node:24-slim AS build
WORKDIR /workspace
RUN corepack enable
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json apps/web/package.json
RUN pnpm install --frozen-lockfile
COPY apps/web apps/web
ARG NEXT_PUBLIC_CASEPILOT_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_CASEPILOT_API_URL=$NEXT_PUBLIC_CASEPILOT_API_URL
RUN pnpm --dir apps/web build

FROM node:24-slim AS runtime
ENV NODE_ENV=production
WORKDIR /workspace/apps/web
COPY --from=build /workspace/node_modules /workspace/node_modules
COPY --from=build /workspace/apps/web/node_modules ./node_modules
COPY --from=build /workspace/apps/web/package.json ./package.json
COPY --from=build /workspace/apps/web/dist ./dist
USER node
EXPOSE 3000
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "node_modules/vinext/dist/cli.js", "start", "--hostname", "0.0.0.0", "--port", "3000"]
