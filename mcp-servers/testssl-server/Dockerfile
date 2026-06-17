FROM python:3.11-slim

# 安装依赖
RUN apt-get update && \
    apt-get install -y git curl bsdmainutils && \
    rm -rf /var/lib/apt/lists/*

# 安装 testssl.sh
RUN git clone --depth 1 https://github.com/drwetter/testssl.sh.git /testssl

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY server.py .

# 暴露端口
EXPOSE 8002

# 启动
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8002"]
