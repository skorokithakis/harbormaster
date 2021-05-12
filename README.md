Harbormaster
============

Harbormaster is a small utility that lets you easily deploy multiple
Docker-Compose applications.


## Installation

Installing Harbormaster is simple. You can use `pipx` (recommended):

```
$ pipx install docker-harbormaster
```

Or `pip` (less recommended):

```
$ pip install docker-harbormaster
```

You need to also make sure you have `git` installed on your system.


## Usage

Harbormaster uses a single YAML configuration file that's basically a list of
repositories containing `docker-compose.yml` files/apps to deploy:

```yaml
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
    # config file (this file).
    # Variables in the `environment` key above take precedence over variables
    # in the file.
    environment_file: "somefile.txt"
  otherapp:
    url: https://gitlab.com/otheruser/otherrepo.git
    # The Compose config filename, if it's not docker-compose.yml.
    compose_filename: mydocker-compose.yml
    # A dictionary of replacements (see below).
    replacements:
      MYVOLUMENAME: volume
    # A file containing replacements. Works in the exact same way as the
    # `environment_file` above.
    replacements_file: "otherfile.txt"
  oldapp:
    # This is an old app, so it shouldn't be run.
    enabled: false
    # Two apps can use the same repo.
    url: https://gitlab.com/otheruser/otherrepo.git
```

Then, just run Harbormaster in the same directory as that configuration file.
Harbormaster will parse the file, automatically download the repositories
mentioned in it (and keep them up to date).

Harbormaster only ever writes to the working directory you specify, and nowhere
else. All the data for each Compose app is under `<workdir>/data/<appname>`, so
you can easily back up the entire data directory in one go.

**WARNING:** Make sure the Compose config in each of the repos does not use
`container_name`, otherwise Harbormaster might not always be able to terminate
your apps when necessary.


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
repo, and look for the specific strings `{{ HM_DATA_DIR }}` and
`{{ HM_CACHE_DIR }}` in it. It will replace those strings with the proper
directories (without trailing slashes), so the `volumes` section of your
Compose file in your repository needs to look something like this:

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
