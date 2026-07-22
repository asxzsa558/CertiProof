FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends openssl snmpd && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir asyncssh==2.14.0

WORKDIR /app
COPY scripts/e2e_target_service.py /app/e2e_target_service.py
COPY docker/e2e-target/snmpd.conf /app/snmpd.conf

EXPOSE 22 80 161/udp 443 1521 3306 6379 11211 27017
CMD ["python", "/app/e2e_target_service.py"]
