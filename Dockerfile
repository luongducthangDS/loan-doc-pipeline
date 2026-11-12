# Review UI (app.py) trên bộ mẫu dev đã commit. Pipeline/eval cần VLM endpoint nên chạy ngoài container.
FROM python:3.11-slim
WORKDIR /app
# Font có dấu cho datagen (giống CI), để chạy được cả test suite trong container
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Kết quả rà soát ghi vào volume, không vào image
ENV REVIEW_DB=/data/review.sqlite
RUN mkdir -p /data && useradd -m app && chown app /data
USER app
EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')"
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
