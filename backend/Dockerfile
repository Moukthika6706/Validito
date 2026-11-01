# Validito API / worker image. The same image runs uvicorn (api) and celery (worker);
# docker-compose picks the command.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# libgl / glib for OpenCV (pulled in by EasyOCR); netcat for the DB wait loop
# INSTALL_LIBREOFFICE=true adds LibreOffice (~400 MB) so DOCX uploads render as pages in the
# review screen; without it DOCX falls back to highlighting within the extracted text.
ARG INSTALL_LIBREOFFICE=false
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 netcat-openbsd curl \
    && if [ "$INSTALL_LIBREOFFICE" = "true" ]; then apt-get install -y --no-install-recommends libreoffice-writer; fi \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# CPU-only torch first so EasyOCR does not pull the multi-GB CUDA build.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision
COPY requirements.txt requirements-ocr.txt .
RUN pip install -r requirements.txt -r requirements-ocr.txt \
    && python -m spacy download en_core_web_sm

# Pre-fetch the EasyOCR English models so the first scanned upload is not slow.
RUN python -c "import easyocr; easyocr.Reader(['en'], gpu=False, verbose=False)"

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["api"]
