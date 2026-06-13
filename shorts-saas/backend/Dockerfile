FROM python:3.11-slim

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    libgl1 \
    libglib2.0-0 \
    curl \
    fonts-liberation \
    fonts-freefont-ttf \
    fontconfig \
    && fc-cache -f \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install torch CPU-only first (smaller, no CUDA)
RUN pip install --no-cache-dir torch==2.4.1 --index-url https://download.pytorch.org/whl/cpu

# Install remaining Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# PYTHONPATH so core modules are importable
ENV PYTHONPATH=/app:/app/core
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Default: run FastAPI (overridden for worker in docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
