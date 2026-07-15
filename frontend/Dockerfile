FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM python:3.11-slim

WORKDIR /app

# Install aiohttp for async static file serving
RUN pip install --no-cache-dir aiohttp

# Copy frontend assets built inside Docker
COPY --from=builder /app/dist/ /app/static/

# Copy server script
COPY serve.py /app/

EXPOSE 80

CMD ["python", "serve.py"]
