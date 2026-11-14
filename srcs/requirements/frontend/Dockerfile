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

# --- Production: static server for the build (behind the nginx service) ---
FROM nginx:1.27-alpine AS prod
RUN rm /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
