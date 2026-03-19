FROM python:3.11-slim

# Empêche Python de générer des .pyc
ENV PYTHONDONTWRITEBYTECODE=1
# Empêche Python de bufferiser les logs
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Installer les dépendances système si ton bot en a besoin
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]
