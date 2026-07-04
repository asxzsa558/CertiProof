FROM python:3.11-slim

# 使用阿里云 Debian 镜像
RUN echo "deb http://mirrors.aliyun.com/debian/ trixie main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian/ trixie-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian-security/ trixie-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y \
    redis-tools \
    netcat-openbsd \
    default-mysql-client \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖
WORKDIR /app
COPY requirements.txt .
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY server.py .

# 复制工具脚本（包括 Oracle TNS 检测等）
COPY tools/ /app/tools/
RUN chmod +x /app/tools/*.py

EXPOSE 8015

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8015"]
