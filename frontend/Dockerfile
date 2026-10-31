# The web tier: Next.js on port 3000. The app reads its secrets from Key Vault at run time
# (DIUCS_KEY_VAULT_URL, AZURE_CLIENT_ID), so no secret is baked into the image.
FROM node:22-slim AS build
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
# The image does not run tests, and `next build` type-checks every file the tsconfig includes: drop them.
RUN find . -path ./node_modules -prune -o \( -name "*.test.ts" -o -name "*.test.tsx" \) -print | xargs -r rm -f \
    && rm -rf test e2e playwright.config.ts
RUN pnpm build

FROM node:22-slim
ENV NODE_ENV=production PORT=3000 HOSTNAME=0.0.0.0
RUN corepack enable
WORKDIR /app
COPY --from=build /app /app
USER node
EXPOSE 3000
CMD ["pnpm", "start", "-p", "3000", "-H", "0.0.0.0"]
