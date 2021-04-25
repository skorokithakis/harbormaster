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
