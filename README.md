Harbormaster
============

Harbormaster is a small utility that lets you easily deploy multiple
Docker-Compose applications.


Installation
------------

Installing Harbormaster is simple. You can use `pipx` (recommended):

```
$ pipx install docker-harbormaster
```

Or `pip` (less recommended):

```
$ pip install docker-harbormaster
```

You need to also make sure you have `git` installed on your system.


Usage
-----

Harbormaster uses a single YAML configuration file that's basically a list of
repositories to deploy:

```
repositories:
  myapp:
    url: https://github.com/someuser/somerepo.git
  otherapp:
    url: https://gitlab.com/otheruser/otherrepo.git
```

Then, just run Harbormaster in the same directory as that configuration file.
Harbormaster will parse the file, automatically download the repositories
mentioned in it (and keep them up to date).

Harbormaster only ever writes to the working directory you specify, and nowhere
else. All the data for each Compose app is under `<workdir>/data/<appname>`, so
you can easily back up the entire data directory in one go.


Handling data directories
-------------------------

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

```
volumes:
  - {{ HM_DATA_DIR }}/my_data:/some_data_dir
  - {{ HM_DATA_DIR }}/foo:/home/foo
  - {{ HM_CACHE_DIR }}/my_cache:/some_cache_dir
```
