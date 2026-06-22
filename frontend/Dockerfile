FROM python:3.11-slim

WORKDIR /app

# Install aiohttp for async static file serving
RUN pip install --no-cache-dir aiohttp

# Copy built frontend assets
COPY dist/ /app/static/

# Copy server script
COPY serve.py /app/

EXPOSE 80

CMD ["python", "serve.py"]
