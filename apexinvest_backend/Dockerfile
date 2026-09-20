# ApexInvest — production image (engine + API + desktop UI + mobile web app at /m)
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
# Secrets are NEVER baked into the image: pass EODHD_API_KEY / APEX_ACCESS_KEYS at run time.
ENV PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn apexinvest.api.main:app --host 0.0.0.0 --port ${PORT} --workers 2 --proxy-headers --forwarded-allow-ips='*'"]
