FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libpq-dev curl && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn gevent
COPY . .
RUN mkdir -p /app/logs
EXPOSE 5050 8000
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD curl -f http://localhost:5050/api/health || exit 1
CMD ["gunicorn", "-w", "4", "-k", "gevent", "-b", "0.0.0.0:5050", "--timeout", "120", "app:create_app()"]
