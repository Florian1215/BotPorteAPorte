FROM nginx:1.27-alpine

ARG NGINX_CONF=prod.conf

RUN apk add --no-cache openssl \
    && rm -f /etc/nginx/conf.d/default.conf

COPY conf/${NGINX_CONF} /etc/nginx/conf.d/default.conf
COPY conf/proxy_params.conf /etc/nginx/snippets/proxy_params.conf
COPY tools/gen-cert.sh /docker-entrypoint.d/05-gen-cert.sh
RUN chmod +x /docker-entrypoint.d/05-gen-cert.sh

EXPOSE 80 443
