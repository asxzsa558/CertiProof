FROM python:3.11-slim

# 使用阿里云 Debian 镜像
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g| /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g| /etc/apt/sources.list 2>/dev/null || true

# 安装系统依赖
RUN apt-get update && \
    apt-get install -y \
    gobuster \
    ffuf \
    curl \
    procps \
    git \
    perl \
    && rm -rf /var/lib/apt/lists/*

# 内置轻量目录字典，避免 gobuster/ffuf 因默认字典缺失而空跑
RUN mkdir -p /usr/share/wordlists/dirb && \
    printf '%s\n' \
      admin api assets backup backups config css dashboard data db debug docs download downloads images img js login logout manager old private public robots.txt server-status static test upload uploads user users vendor webadmin wp-admin wp-content wp-includes \
      > /usr/share/wordlists/dirb/common.txt

# 安装 nikto (从 GitHub)
RUN git clone --depth 1 https://github.com/sullo/nikto.git /opt/nikto && \
    ln -s /opt/nikto/program/nikto.pl /usr/local/bin/nikto && \
    chmod +x /opt/nikto/program/nikto.pl

# 安装 sqlmap (从 GitHub)
RUN git clone --depth 1 https://github.com/sqlmapproject/sqlmap.git /opt/sqlmap && \
    ln -s /opt/sqlmap/sqlmap.py /usr/local/bin/sqlmap && \
    chmod +x /opt/sqlmap/sqlmap.py

# 安装 Python 依赖
WORKDIR /app
COPY requirements.txt .
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY server.py .

EXPOSE 8012

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8012"]
