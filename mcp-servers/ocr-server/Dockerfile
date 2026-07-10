FROM python:3.11-slim

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip install --no-cache-dir -r requirements.txt
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 && \
    rm -rf /var/lib/apt/lists/*

# 复制代码
COPY server.py .

# 暴露端口
EXPOSE 8005

# 启动
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8005"]
