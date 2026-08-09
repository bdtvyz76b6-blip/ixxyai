FROM python:3.10-slim

# Устанавливаем Tesseract и русский языковой пакет
RUN apt-get update && \
    apt-get install -y tesseract-ocr tesseract-ocr-rus && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["python", "main.py"]