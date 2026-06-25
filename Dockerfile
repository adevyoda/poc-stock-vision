FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5001 \
    HOST=0.0.0.0

WORKDIR /app

COPY requirements-server.txt .
RUN pip install --no-cache-dir -r requirements-server.txt

COPY sap_config.py server.py ./
COPY dashboard/ ./dashboard/

EXPOSE 5001

CMD ["python", "server.py"]
