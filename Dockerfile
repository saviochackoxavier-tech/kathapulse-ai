# KathaPulse AI — production image.
#
#   docker build -t kathapulse .
#   docker run -p 8000:8000 -e KATHA_VISION_API_KEY=... kathapulse
#
# The container needs no volume, no writable layer and no database: every
# upload is processed in RAM and discarded with the request. That is a design
# property (DPDP Act 2023), not a deployment convenience — see README.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

WORKDIR /app

# Dependencies first, so a source edit does not invalidate the install layer.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY static ./static

# Unprivileged runtime user. Optional local OCR would also need tesseract-ocr
# installed here; the vision tier needs nothing beyond the three env vars.
RUN useradd --create-home --uid 10001 katha
USER katha

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PORT\", \"8000\")}/health', timeout=2)"

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers"]
