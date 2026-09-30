FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY server/requirements.txt ./server/requirements.txt
RUN pip install --no-cache-dir -r server/requirements.txt && useradd --create-home --uid 10001 maritime
COPY server/ ./server/
COPY index.html ./index.html
USER maritime
EXPOSE 8000
CMD ["python", "server/run.py"]
