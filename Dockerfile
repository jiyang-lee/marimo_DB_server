FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

ARG SERVICE_DIR
ARG REQUIREMENTS_FILE

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

COPY ${REQUIREMENTS_FILE} ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY ${SERVICE_DIR}/ .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
