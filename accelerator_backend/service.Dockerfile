# The CWatM points service (an Accelerator interactive routine). Standard library only.
# Build context = the repository root. Start the routine with
#   "interactive_socket": "0.0.0.0:8000", "WDRV_ACCESS": "read-write"
FROM python:3.12-slim

WORKDIR /app
COPY accelerator_backend/award_run.py accelerator_backend/badges.py \
     accelerator_backend/config.py accelerator_backend/event_store.py \
     accelerator_backend/identity.py accelerator_backend/ledger_paths.py \
     accelerator_backend/points_service.py /app/

ENV PORT=8000 LEDGER_DIR=/mnt/wdrv
EXPOSE 8000
CMD ["python", "-u", "points_service.py"]
