FROM python:3.11-slim

WORKDIR /app

COPY api/requirements.txt ./api/requirements.txt
COPY --from=analysis . ./analysis/
RUN pip install --no-cache-dir -r api/requirements.txt -e ./analysis/
# api/ source is mounted at runtime — not copied here

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
