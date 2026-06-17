FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install nuclei
RUN wget -qO- https://github.com/projectdiscovery/nuclei/releases/latest/download/nuclei_linux_amd64.zip | unzip -d /usr/local/bin/ - \
    && chmod +x /usr/local/bin/nuclei

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .

EXPOSE 8002

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8002"]
