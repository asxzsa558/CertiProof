FROM python:3.11-slim

# 使用阿里云 Debian 镜像
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list 2>/dev/null || true

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y \
    curl \
    wget \
    unzip \
    bsdmainutils \
    procps \
    hydra \
    nmap \
    && rm -rf /var/lib/apt/lists/*

# 安装 testssl.sh
RUN curl -fsSL https://ghfast.top/https://github.com/drwetter/testssl.sh/archive/refs/heads/3.2.tar.gz | tar xz -C /opt && \
    mv /opt/testssl.sh-3.2 /testssl && \
    chmod +x /testssl/testssl.sh

# 安装 nuclei (arm64)
RUN wget -q https://ghfast.top/https://github.com/projectdiscovery/nuclei/releases/download/v3.3.0/nuclei_3.3.0_linux_arm64.zip -O /tmp/nuclei.zip && \
    unzip /tmp/nuclei.zip -d /usr/local/bin/ && \
    chmod +x /usr/local/bin/nuclei && \
    rm /tmp/nuclei.zip

# 安装 Python 依赖
WORKDIR /app
COPY requirements.txt .
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY server.py .

EXPOSE 8010

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8010"]
