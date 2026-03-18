FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /app/instance /app/uploads/gpx

EXPOSE 5000
CMD ["sh", "-c", "gunicorn -k gthread -w ${GUNICORN_WORKERS:-2} --threads ${GUNICORN_THREADS:-4} --timeout ${GUNICORN_TIMEOUT:-30} --keep-alive ${GUNICORN_KEEPALIVE:-5} -b 0.0.0.0:5000 run:app"]
