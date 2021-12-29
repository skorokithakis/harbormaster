Harbormaster
============

[![PyPI](https://img.shields.io/pypi/v/docker_harbormaster)](https://pypi.org/project/docker-harbormaster/)

Harbormaster is a small utility that lets you easily deploy multiple
Docker-Compose applications on a single host.

It does this by taking a list of git repository URLs that contain Docker
Compose files and running the Compose apps they contain. It will also handle
updating/restarting the apps when the repositories change.


## Rationale

Do you have a home server you want to run a few apps on, but don't want everything to
break every time you upgrade the OS? Do you want automatic updates but don't want to buy
an extra 4 servers so you can run Kubernetes?

Do you have a work server that you want to run a few small services on, but don't want
to have to manually manage it? Do you find that having every deployment action be in
a git repo more tidy?

Harbormaster is for you.

At its core, Harbormaster takes a YAML config file with a list of git repository URLs
containing Docker Compose files, clones/pulls them, and starts the services they
describe.

You run Harbormaster on a timer, pointing it to a directory, and it updates all the
repositories in its configuration, and restarts the Compose services if they have
changed. That's it!

It also cleanly stores data for all apps in a single `data/` directory, so you always
have one directory that holds all the state, which you can easily back up and restore.


## Installation

You can run Harbormaster directly from Docker, without installing anything. Skip down to
the [Docker installation](#docker-installation) section.

Installing Harbormaster is simple. You can use `pipx` (recommended):

```
$ pipx install docker-harbormaster
```

Or `pip` (less recommended):

```
$ pip install docker-harbormaster
```

You need to also make sure you have `git` installed on your system.

You can also download a standalone executable for Linux from the [pipelines
page](https://gitlab.com/stavros/harbormaster/-/pipelines).


## Docker installation

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
remote it has), and run the apps in the config.

If you want to run it immediately at some point, you can use the following command:

```bash
$ docker exec -i -t <container id> /usr/bin/run-harbormaster
```


## High-level architecture overview

At its core, Harbormaster works very simply: It takes a YAML file containing a list of
repositories, pulls/clones them as necessary, messes with their `docker-compose.yml`
files in the way you specify, and tells Compose to start, stop, or restart them, as
needed.

That's all it does.


## Usage

Harbormaster uses a single YAML configuration file that's basically a list of
repositories containing `docker-compose.yml` files/apps to deploy:

```yaml
config:
  # Prune *all unused* system images after a run. Good for saving space on the host.
  # Careful, if you run this on a system with other Docker images, it will delete them.
  prune: true
apps:
  myapp:
    # The git repository URL to clone.
    url: https://github.com/someuser/somerepo.git
    # Which branch to deploy.
    branch: main
    # The environment variables to run Compose with.
    environment:
      FOO: bar
      MYVAR: 1
    # A file to load environment variables from. The file must consist of lines
    # in the form of key=value. The filename is relative to the Harbormaster
    # config file (this file). This can also be a YAML file with the .yml extension,
    # containing a single YAML collection of string values.
    # Variables in the `environment` key above take precedence over variables
    # in the file.
    # Make sure all these variable names appear in the `environment` section of the
    # app's `docker-compose.yml` file.
    environment_file: "somefile.txt"
  otherapp:
    url: https://gitlab.com/otheruser/otherrepo.git
    # The Compose config filename, if it's not docker-compose.yml, or if you
    # want to use Harbormaster-specific overrides:
    compose_config:
      - docker-compose.yml
      - docker-compose.harbormaster.yml
    # A dictionary of replacements (see below).
    replacements:
      MYVOLUMENAME: volume
    # A file containing replacements. Works in the exact same way as the
    # `environment_file` above.
    replacements_file: "otherfile.txt"
    # A YAML environment file.
    environment_file: "somefile.yml"
  oldapp:
    # This is an old app, so it shouldn't be run.
    enabled: false
    # Two apps can use the same repo.
    url: https://gitlab.com/otheruser/otherrepo.git
```

Then, just execute `harbormaster run` in the same directory as that configuration file.
Harbormaster will parse the file, automatically download the repositories
mentioned in it (and keep them up to date).

Harbormaster only ever writes to the working directory you specify, and nowhere
else. All the data for each Compose app is under `<workdir>/data/<appname>`, so
you can easily back up the entire data directory in one go.

**WARNING:** Make sure the Compose config in each of the repos does not use the
`container_name` directive, otherwise Harbormaster might not always be able to
terminate your apps when necessary.

If you want to trigger Harbormaster via a webhook (perhaps whenever the config file
repository changes), you can use [Captain
Webhook](https://captain-webhook.readthedocs.io/).


## Testing

When developing Harbormaster-compatible Compose files for our app, you usually need to
test them.  The naive way requires you to write a Harbormaster configuration file,
create a repository for your app, commit the app's Compose file in it, and run
Harbormaster with the configuration file to test.

To make this easier, Harbormaster includes the `harbormaster test` command, which will
create a temporary directory for the data/cache/etc directories, and run the Compose
files directly from your repository, without committing or writing a Harbormaster
configuration file.

Run `harbormaster test --help` to see the available options.


## Recommended deployment

**Note:** The Harbormaster Docker image mentioned in "Docker installation" is still
relatively new, but it's a very convenient way to deploy Harbormaster without installing
anything. That may become the recommended way to deploy Harbormaster in the future.

The recommended way to run Harbormaster is on a timer. You can use systemd, with two
files. Put the Harbormaster configuration YAML in a repository, and clone it somewhere.
Then, use the two files to run Harbormaster in that repository.

**/etc/systemd/system/harbormaster.service**:

```toml
[Unit]
Description=Run the Harbormaster updater
Wants=harbormaster.timer

[Service]
ExecStart=/usr/local/bin/harbormaster run
ExecStartPre=/usr/bin/git pull
WorkingDirectory=<the repository directory>

[Install]
WantedBy=multi-user.target
```

**/etc/systemd/system/harbormaster.timer**:

```toml
[Unit]
Description=Run Harbormaster every few minutes.
Requires=harbormaster.service

[Timer]
Unit=harbormaster.service
OnUnitInactiveSec=5m

[Install]
WantedBy=timers.target
```

Then, run:

```bash
sudo systemctl daemon-reload
sudo systemctl enable harbormaster

# To run Harbormaster immediately:
sudo service harbormaster start

# To check the Harbormaster run logs:
sudo journalctl -fu harbormaster
```

This will run Harbormaster every five minutes, pulling your configuration repository
before the run.


## Recommended repository layout

Usually, you will have one repository per app. However, for small apps, like ones that
already have a Docker container on the Docker Hub (and thus just need a Compose file),
it might be more convenient to store the Compose file(s) in the same repository as the
Harbormaster config, one branch per app.

That way, you can pull the Harbormaster configuration and all the app definitions in the
same way, from the same repository, and specify the branch to load the app from with the
`branch` directive in the config.


## Recommended secrets handling

The recommended way for handling secrets is to add plaintext files to
a `secrets/` subdirectory of the repository (e.g. `secrets/myservice.txt`) and use
[git-crypt](https://github.com/AGWA/git-crypt) to encrypt them. That way, it's easy to
add more secrets to the repository, but also only authorized people and the deployment
server has access to the files.


## Handling data directories

Due to the way Compose files work, you need to do some extra work to properly
tell Harbormaster about your volumes.

Harbormaster provides two kinds of directories: Data and cache.

Data is anything that you want to keep. Data directories will never be deleted,
if you remove an app later on, its corresponding data directory will be moved
under the `archives/` directory and renamed to `<appname>-<deletion date>`.

Cache is anything you don't care about. When you remove an app from the config,
the cache dir is deleted.

Harbormaster will look for a file called `docker-compose.yml` at the root of the
repo, and look for some specific strings (you read more about this in the
"replacements" section below).

The built-in strings to be replaced are:

* `{{ HM_DATA_DIR }}` - The app's data that you want to persist. Will be stored in the
  `data/` directory, under the main Harbormaster working directory.
* `{{ HM_CACHE_DIR }}` - Any data you don't want to keep. Will be stored in the `cache/`
  directory, under the main Harbormaster working directory.
* `{{ HM_REPO_DIR }}` - The app's repository. Use this if you want to mount the app's
  directory itself, for example to access some code that you don't want to copy into the
  container.

They will be replaced with the proper directory names (without trailing
slashes), so the `volumes` section of your Compose file in your repository
should look something like this:

```yaml
volumes:
  - {{ HM_DATA_DIR }}/my_data:/some_data_dir
  - {{ HM_DATA_DIR }}/foo:/home/foo
  - {{ HM_CACHE_DIR }}/my_cache:/some_cache_dir
```


### Replacements

Sometimes, the user needs to give access to paths that already exist on their
system, or specify more parameters in the Dockerfile. This is where replacements
come in.

Replacements are basically custom replacement strings (like the data directory
strings) that you can specify yourself.

For example, if the user needs to specify a directory with their media, you can
ask them to include a replacement called `MEDIA_DIR` in their Harbormaster
config file, and then use the string `{{ HM_MEDIA_DIR }}` in your Compose file
to mount the volume, like so:

```yaml
volumes:
  - {{ HM_MEDIA_DIR }}:/some_container_dir
```

Harbormaster will replace that string wherever in the file it finds it (not
just the `volumes` section, and the user can specify it in their Harbormaster
config like so:


```yaml
someapp:
  url: https://gitlab.com/otheruser/otherrepo.git
  replacements:
    MEDIA_DIR: /media/my_media
```

Keep in mind that if the variable is called `VARNAME`, the string that will end
up being replaced is `{{ HM_VARNAME }}`. If the variable is not found, it will
not be replaced or touched at all. This is to avoid messing with any unrelated
templates in the Compose file.

Also, note that replacements will be written on disk, in the Compose config
file. If, for some reason, you want to avoid that (e.g. if you have secrets you
don't want exposed), try to use environment variables instead.

One experimental feature of replacements is the ability to specify defaults:

```yaml
services:
  app:
    environment:
      HTTP_PORT: {{ HM_PORT:80 }}
      STACK: {{ HM_STACK:"production" }}
```

If you don't specify the `PORT` variable in the Harbormaster config file, the
replacement will be replaced with `80`.

This feature is still experimental and may change.


## Examples

This is an example of the configuration for a Harbormaster-compatible Compose
app that adheres to some best practices.

We'll use two Compose files, mount volumes and pass secrets as environment
variables.

The `docker-compose.yml` file is pretty straighforward, doesn't mount any
volumes and uses an environment variable as a secret.

`docker-compose.yml`:

```yaml
services:
  main:
    command: ./myscript
    image: myapp
    build: .
    stdin_open: true
    tty: true
    restart: unless-stopped
    environment:
      - SOME_SECRET
```

The `docker-compose.harbormaster.yml` file is quite small, it overrides the
command (so the script starts from the `/state` directory) and the volumes, so
the `/state` directory maps to the host's data directory.

`docker-compose.harbormaster.yml`:

```yaml
services:
  main:
    command: bash -c 'cd /state; /code/myscript'
    volumes:
      - {{ HM_DATA_DIR }}:/state/
```

The Harbormaster config file is very straightforward, it specifies a repo URL
and the two Compose configuration files. The `docker-compose.yml` is specified
first, and the Harbormaster override is second, so the command is overridden
properly.

`harbormaster.yml`:

```yaml
apps:
  myapp:
    url: https://github.com/myuser/myrepo.git
    compose_config:
      - docker-compose.yml
      - docker-compose.harbormaster.yml
```

This is a good way to add Harbormaster configuration files with very few lines
of configuration. Keep in mind that you unfortunately cannot override volumes
with this technique, as Docker will complain that the volume has been specified
twice.

It's better to define a different volume and change your command to use that
directory, as we've done above.


## Bundled apps

Harbormaster includes some built-in apps in its repository, for your
convenience. Check out the [apps](apps) directory for the Compose files. You
can include them in your Harbormaster config directly, with no other
configuration.

Here's an example that includes the [Plex media server](https://www.plex.tv/) and
[ZTNCUI](https://github.com/key-networks/ztncui):

```yaml
apps:
  plex:
    url: https://gitlab.com/stavros/harbormaster.git
    compose_config: apps/plex-bridge.yml
    environment:
      ADVERTISE_IP: "<the IP to advertise>"
      TZ: "<your timezone, e.g. Europe/Athens>"
      PLEX_CLAIM: "<your Plex claim code>"
    replacements:
      HOSTNAME: "<your hostname>"
      MEDIA_DIR: "<your video directory on the host>"

  ztncui:
    url: https://gitlab.com/stavros/harbormaster.git
    environment:
      ZTNCUI_PASSWD: "<some password>"
    compose_config: apps/ztncui/docker-compose.harbormaster.yml

  octoprint:
    url: https://gitlab.com/stavros/harbormaster.git
    compose_config: apps/octoprint/docker-compose.harbormaster.yml
```
