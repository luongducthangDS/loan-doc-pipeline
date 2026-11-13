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
# Render/Heroku-style host đặt $PORT; chạy local mặc định 8501
ENV PORT=8501
HEALTHCHECK CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ[\"PORT\"]}/_stcore/health')"
CMD streamlit run app.py --server.address=0.0.0.0 --server.port=$PORT --server.headless=true
