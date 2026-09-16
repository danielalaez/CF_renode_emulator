# Optional thin meta-image for this repo.

# Prefer host scripts:
#   ./scripts/bootstrap.sh
#   RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh
#
# Runtime Mono image used by DOCKER=1 runs:
#   docker/Dockerfile.runner  →  renode-cf-runner:22.04

FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates python3 docker.io \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /renode_test
COPY README.md MVP.md ./
COPY sensors ./sensors
COPY resc ./resc
COPY scripts ./scripts
COPY docker ./docker
RUN chmod +x scripts/*.sh
CMD ["bash", "-lc", "echo Use host: ./scripts/bootstrap.sh && RENODE_MONITOR_PORT=9999 DOCKER=1 ./scripts/run_first_test.sh"]
