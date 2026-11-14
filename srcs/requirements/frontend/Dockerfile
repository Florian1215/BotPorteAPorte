FROM node:22-alpine AS base
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

# --- Development: Vite dev server with hot reload (code bind-mounted) ---
FROM base AS dev
EXPOSE 5173
CMD ["npm", "run", "dev"]

# --- Build static assets ---
FROM base AS build
COPY . .
RUN npm run build

# --- Production: copy the build into the volume served by nginx, then exit ---
FROM alpine:3.20 AS prod
COPY --from=build /app/dist /app/dist
CMD ["sh", "-c", "rm -rf /dist/* && cp -r /app/dist/. /dist/ && echo 'Frontend build copied.'"]
