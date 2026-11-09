FROM node:24-alpine AS build

WORKDIR /app/frontend
COPY package.json package-lock.json ./
RUN npm ci

COPY . ./
RUN npm run build

FROM nginx:stable-alpine AS runtime

RUN apk --no-cache upgrade

ENV BACKEND_HOSTNAME=backend:8000 \
    NGINX_ENVSUBST_OUTPUT_DIR=/tmp \
    NGINX_ENVSUBST_FILTER="^BACKEND_HOSTNAME$"

COPY nginx.conf /etc/nginx/templates/nginx.conf.template
COPY --from=build /app/frontend/dist/ /usr/share/nginx/html/

USER nginx
EXPOSE 8080
CMD ["nginx", "-c", "/tmp/nginx.conf", "-g", "daemon off;"]
