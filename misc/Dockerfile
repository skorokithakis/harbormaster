FROM ubuntu:20.04

ENV TZ=Etc/UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN apt-get update && apt-get install -y python3-pip docker.io cron

RUN pip install -U pip poetry
RUN poetry config virtualenvs.create false
RUN mkdir /root/.ssh/
RUN /bin/echo -e "Host *\n\tStrictHostKeyChecking no\n\tIdentityFile /config/ssh_private_key\n" > ~/.ssh/config


RUN mkdir /config /main /hm-src

VOLUME /main
VOLUME /config

# Add the crontab.
COPY misc/crontab /etc/cron.d/harbormaster
RUN chmod 0644 /etc/cron.d/harbormaster && \
    crontab /etc/cron.d/harbormaster

COPY misc/run-harbormaster /usr/bin/
COPY misc/entrypoint /usr/bin/

COPY . /hm-src/

# Install Harbormaster.
RUN pip install /hm-src/

WORKDIR /config
RUN git config --global --add safe.directory /config

CMD ["/usr/bin/entrypoint"]
