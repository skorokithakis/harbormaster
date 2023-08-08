FROM python:3-alpine

RUN apk add bash docker-cli docker-cli-compose dumb-init git openssh git-crypt && \
    mkdir /main /config

# We need this so git doesn't block us from operations. Hopefully it doesn't enable any
# extra vulnerabilities, but I don't see how it could, since Harbormaster should own
# the repos it touches.
RUN git config --global safe.directory '*'

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
CMD /usr/bin/dumb-init /usr/bin/entrypoint
