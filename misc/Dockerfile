FROM ubuntu:20.04

RUN apt-get update && apt-get install -y python3-pip docker.io cron

RUN pip install poetry
RUN poetry config virtualenvs.create false
RUN mkdir /root/.ssh/
RUN /bin/echo -e "Host *\n\tStrictHostKeyChecking no\n\tIdentityFile /config/ssh_private_key\n" > ~/.ssh/config


RUN mkdir /config
RUN mkdir /main

VOLUME /main
VOLUME /config

# Install Harbormaster.
RUN pip install docker-harbormaster==IMAGE_VERSION

# Add the crontab.
COPY misc/crontab /etc/cron.d/harbormaster
RUN chmod 0644 /etc/cron.d/harbormaster && \
    crontab /etc/cron.d/harbormaster

COPY misc/entrypoint.sh /usr/bin/

WORKDIR /config

CMD ["cron", "-f"]
