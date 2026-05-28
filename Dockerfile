FROM node:22-alpine AS ember_deps
WORKDIR /app/ember
COPY ember/package.json ./
RUN npm install --omit=dev

FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    nodejs \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src ./src
COPY web ./web
COPY ember ./ember
COPY --from=ember_deps /app/ember/node_modules ./ember/node_modules
COPY config.example.yaml ./config.example.yaml

RUN mkdir -p /app/data

ENV CONFIG_PATH=/app/config.yaml
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

COPY scripts/start.sh /start.sh
RUN sed -i 's/\r$//' /start.sh && chmod +x /start.sh

CMD ["/start.sh"]
