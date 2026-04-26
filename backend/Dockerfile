FROM python:3.12-slim

WORKDIR /app

# System deps for cryptography (bcrypt, JWT) and aiohttp wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# sns-message-validator==0.0.1 pins cryptography==2.6.1 which cannot build on
# Python 3.12.  Install with --no-deps so pip skips the broken transitive dep;
# cryptography is already satisfied by python-jose[cryptography].
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir --no-deps sns-message-validator==0.0.1

COPY app ./app
COPY worker ./worker

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
