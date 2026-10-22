FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY omp_live ./omp_live
RUN pip install --no-cache-dir .
# A clean demo, seeded at build time from public AI Disclosures Project notes. The fixture carries each memory's
# search embedding, so nothing is embedded at boot. Machines start from this copy every time they wake.
COPY aidp-memories.json ./
RUN omp-sync --root demo seed aidp-memories.json
ENV OMP_HOST=0.0.0.0 PYTHONUNBUFFERED=1
EXPOSE 8700
CMD ["omp-sync", "--root", "demo", "demo", "--no-browser"]
