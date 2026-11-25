FROM mirror.gcr.io/library/python:3.13-slim
WORKDIR /srv/text-stats
COPY requirements.txt .
# pip is only needed at build time; removing it drops its vendored packages from the image
RUN pip install --no-cache-dir -r requirements.txt && pip uninstall -y pip
COPY service service
RUN useradd --system --uid 10001 textstats
USER 10001
ARG RELEASE=dev
ENV RELEASE=${RELEASE}
EXPOSE 5000
# ponytail: one worker because prometheus_client counters are per process; multiprocess mode if more are needed
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "1", "--threads", "8", "--access-logfile", "-", "service.web:app"]
