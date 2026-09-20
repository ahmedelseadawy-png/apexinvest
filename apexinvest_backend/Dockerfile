# ApexInvest — production image (engine + API + desktop UI + mobile web app at /m/).
# Works on any container host (Fly.io, Railway, Cloud Run, a VPS...).  Build context = this folder.
# NOTE: written for portability; the Render deployment in ../render.yaml does not use it.
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 APEX_ENV=production PORT=8000
WORKDIR /app
COPY requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY . .
# Run as an unprivileged user.
RUN useradd --create-home --uid 10001 apex && chown -R apex /app
USER apex
# Secrets are NEVER baked into the image: pass APEX_ACCESS_KEYS / EODHD_API_KEY at run time.
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/v1/health',timeout=4)" || exit 1
CMD ["sh", "-c", "exec uvicorn apexinvest.api.main:app --host 0.0.0.0 --port ${PORT} --workers ${APEX_WORKERS:-1} --proxy-headers --forwarded-allow-ips '*' --no-access-log --no-server-header --timeout-graceful-shutdown 20"]
