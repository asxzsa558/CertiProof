FROM python:3.11-slim

# 使用阿里云 Debian 镜像
RUN echo "deb http://mirrors.aliyun.com/debian/ trixie main contrib non-free non-free-firmware" > /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian/ trixie-updates main contrib non-free non-free-firmware" >> /etc/apt/sources.list && \
    echo "deb http://mirrors.aliyun.com/debian-security/ trixie-security main contrib non-free non-free-firmware" >> /etc/apt/sources.list

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y \
    curl \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 配置 pip 使用阿里云镜像
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set install.trusted-host mirrors.aliyun.com

# 安装 impacket (包含完整的 SMB/Windows 工具集)
RUN pip install --no-cache-dir impacket

# 安装 Python 依赖
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY server.py .

EXPOSE 8014

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8014"]
