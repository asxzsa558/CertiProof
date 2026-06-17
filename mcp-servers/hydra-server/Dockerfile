FROM python:3.11-slim

# 安装 hydra
RUN apt-get update && \
    apt-get install -y hydra && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 安装 Python 依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY server.py .

# 暴露端口
EXPOSE 8004

# 启动
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8004"]
