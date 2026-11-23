FROM node:24-alpine AS web
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM caddy:2.11.4-alpine
COPY --from=web /app/dist /srv/alkocop
