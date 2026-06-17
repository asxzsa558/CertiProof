FROM python:3.11-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY server.py .

# 暴露端口
EXPOSE 9000

# 启动
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9000"]
