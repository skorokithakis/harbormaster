Installation
============

You can run Harbormaster by using just Docker. You need to follow a few simple steps to set
up your configuration and SSH:

* Your `harbormaster.yml` configuration file should be in a git repository. Check that
  repository out into some directory, that we're going to call your "config" directory.
* If you need an SSH key to pull the Harbormaster configuration file and the various
  repositories, copy the private key into your config directory, to a file called
  `ssh_private_key` (make sure it's not protected with a passphrase).
* Make a directory for Harbormaster to work in somewhere. All your apps' data is going
  to reside in that directory.
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
