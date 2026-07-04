FROM python:3.11-slim

# 使用阿里云 Debian 镜像
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g| /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g| /etc/apt/sources.list 2>/dev/null || true

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y \
    snmp \
    onesixtyone \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 创建 SNMP 字典文件
RUN mkdir -p /usr/share/wordlists && \
    echo -e "public\nprivate\ncommunity\nsnmp\nmonitor\nadmin\nmanager\ndefault\nread\nwrite" > /usr/share/wordlists/snmp-common.txt

# 安装 Python 依赖
WORKDIR /app
COPY requirements.txt .
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY server.py .

EXPOSE 8013

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8013"]
