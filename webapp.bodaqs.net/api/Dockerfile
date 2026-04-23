FROM python:3.11-slim

WORKDIR /app

# Copy analysis only to run the editable install; the compose mount overlays it at runtime
COPY analysis/ ./analysis/
COPY webapp.bodaqs.net/api/requirements.txt ./api/requirements.txt
RUN pip install --no-cache-dir -r api/requirements.txt -e ./analysis/
# api/ source is mounted at runtime — not copied here

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
