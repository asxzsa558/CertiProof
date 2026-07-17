FROM python:3.11-slim

RUN pip install --no-cache-dir asyncssh==2.14.0

WORKDIR /app
COPY scripts/e2e_target_service.py /app/e2e_target_service.py

EXPOSE 22 80 443
CMD ["python", "/app/e2e_target_service.py"]
