# Single entry point of the site: one URL for everything.
#   /api/, /admin/    → Django (backend)
#   /django-static/   → Django admin static files
#   everything else   → React frontend
FROM nginx:1.27-alpine AS base
RUN rm /etc/nginx/conf.d/default.conf
COPY conf/common.conf /etc/nginx/snippets/common.conf
EXPOSE 80

# ---------- Development: Vite (hot reload) and runserver ----------
FROM base AS dev
COPY conf/dev.conf /etc/nginx/conf.d/site.conf

# ---------- Production: gunicorn, React build, static files served by nginx ----------
FROM base AS prod
COPY conf/prod.conf /etc/nginx/conf.d/site.conf
