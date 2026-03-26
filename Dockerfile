FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates
COPY static ./static

ENV ARK_HOST=0.0.0.0
ENV ARK_PORT=8000

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host ${ARK_HOST} --port ${ARK_PORT}"]
