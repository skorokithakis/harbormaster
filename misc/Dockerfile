FROM python:3-alpine

RUN apk add bash docker-cli dumb-init git openssh && \
    mkdir /main /config && \
    git config --global --add safe.directory /config

COPY docker_harbormaster /src/docker_harbormaster
# Required for pip to install the package.
COPY pyproject.toml README.md /src/

RUN pip install /src

COPY misc/ssh_config /etc/ssh/ssh_config
COPY misc/crontab /var/spool/cron/crontabs/root
COPY misc/run-harbormaster misc/entrypoint /usr/bin/

VOLUME /main
VOLUME /config

ENTRYPOINT ["/usr/bin/dumb-init", "--"]
CMD ["/usr/bin/entrypoint"]
