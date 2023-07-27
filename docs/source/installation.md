Installation
============

There are two ways to run Harbormaster: In a Docker container, and on the host system.
The Docker container method is preferable, as it's much easier to get started with.


Docker container
----------------

You can run Harbormaster by using just Docker. You need to follow a few steps to set up
your configuration and SSH:

* Add your `harbormaster.yml` config (plus associated env/secrets files) to a git
  repository, and check it out somewhere on the host. That is your "config" directory.
* If you're going to be using SSH to pull the above repository, as well as any
  app repositories (mentioned in the above `harbormaster.yml`), copy the private SSH key
  into the config directory, and name it `ssh_private_key`.
* Create a directory for Harbormaster to put all the apps' volumes/data into. That is
  your Harbormaster working directory.
* Run the Harbormaster image:
```bash
docker run -d \
    --restart unless-stopped \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v <the path to your config directory>:/config \
    -v <the path to your Harbormaster working directory>:/main \
    stavros/harbormaster
```

Harbormaster will now run every five minutes, pull your config repository (from whatever
remote the repo has as its `origin`), and run the apps in the config.

If you want to run it immediately at some point, you can use the following command:

```bash
$ docker exec -i -t <container id> /usr/bin/run-harbormaster
```

Alternatively you can use `stavros/harbormaster:webhook` which ships with
[webhook](https://github.com/adnanh/webhook) to trigger updates. The image comes with
an example configuration but you should mount a custom one to `/hooks.json` with proper
[rules](https://github.com/adnanh/webhook/blob/master/docs/Hook-Rules.md) for verifying
the source.
