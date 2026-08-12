FROM node:20-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

FROM node:20-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY --from=build /app/dist ./dist

# Real data lives here: the SQLite database (every student record), uploaded
# student documents (citizenship, marksheets, IELTS certificates), and the
# JWT signing secret.
#
# THIS MUST BE BACKED BY A PERSISTENT VOLUME IN PRODUCTION. Without one, this
# directory is wiped on every redeploy/restart — every student record and
# every uploaded document is permanently lost, and a new JWT secret is
# generated each time (logging out every staff session). See
# docker-compose.yml, which wires this correctly.
VOLUME ["/app/data"]

EXPOSE 3001

CMD ["node", "dist/server.js"]
