# Integrating Compose apps with Harbormaster

If you have a Compose app and you want to make sure it integrates with Harbormaster,
there are a few things you need to do.


## Naming your Compose file

Call your Compose file whatever Compose itself would accept, and Harbormaster will find
it. It looks for `compose.yaml`, `compose.yml`, `docker-compose.yaml` and
`docker-compose.yml`, in that order, and uses the first one in the repository.

If your app needs more than one file, Harbormaster will not guess. It never picks up an
override file such as `compose.override.yaml` on its own, so list every file you want in
[`compose_config`](configuration), in the order Compose should merge them. Do the same
if your file has a name that is not in the list above.


(handling-data-directories)=
## Handling data

Harbormaster keeps your apps' data in two kinds of directory, both under the main
working directory.

**Data** is anything you want to keep. Data directories are never deleted. If you remove
an app later on, its data directory is moved under the `archives/` directory and renamed
to `<appname>-<deletion date>`.

**Cache** is anything you don't care about. When you remove an app from the config, its
cache directory is deleted. Harbormaster does nothing else special with it, the point of
the separation is that you can back up `data/` and skip `caches/`.

There are two ways to point your app's volumes at these directories. Managed volumes are
the recommended one, and are described next. The older approach, which writes
Harbormaster's paths into the Compose file with environment variables, is described
further down, and still works.


(managed-volumes)=
## Managed volumes

Enabling managed volumes is strongly recommended. Add `manage_volumes: true` to the app
in your Harbormaster config file:

```yaml
apps:
  myapp:
    url: https://github.com/someone/myapp.git
    manage_volumes: true
```

Then just declare plain named volumes in your Compose file, the way any Compose app
would:

```yaml
services:
  main:
    image: myapp
    volumes:
      - config:/config
      - cache-transcode:/transcode

volumes:
  config:
  cache-transcode:
```

Harbormaster rewrites each of these volumes so that it is backed by a directory on the
host. `config` will live in `data/myapp/config`, and `cache-transcode` will live in
`caches/myapp/cache-transcode`. Volumes whose name starts with `cache-` go to the cache
directory, everything else goes to the data directory.

The upshot is that your Compose file stays a normal Compose file. You can run `docker
compose logs` (or any other command) in the repository directory without setting any
environment variables first. Your data is still in a plain directory you can back up.
Data directories are archived when you remove the app, and cache directories are
deleted.

Harbormaster leaves alone any volume that declares its own `driver`, `driver_opts`,
`external` or `name` key, so you can still opt individual volumes out.

A managed volume's name is used as a directory name, so it must be a plain name.
Harbormaster refuses to start an app whose managed volume name contains a path
separator, or is `.` or `..`.

### Migrating to managed volumes

If you name a volume the same as the directory you used with `${HM_DATA_DIR}` before, it
points at the same place, so there's nothing to move. These two are equivalent:

```yaml
    volumes:
      - ${HM_DATA_DIR}/config:/config
```

```yaml
    volumes:
      - config:/config
```

### Caveats

`manage_volumes` is off by default, and you should think before turning it on for an app
that is already running with plain named volumes. Docker stores that data in its own
directory, and Harbormaster will not move it for you. Collision checking only happens
against the Docker volume name Harbormaster generates, `hm_<app_id>_<volume>`, so an
ordinary pre-existing Compose volume (Docker names those `<project>_<volume>`) will not
collide: the app starts normally, and the old volume is left behind, unmigrated, with
its data still in Docker's storage, and no warning is issued. Harbormaster only refuses
to start the app if a volume named exactly `hm_<app_id>_<volume>` already exists without
Harbormaster's ownership label. Migrating the data of an old volume into the app's data
directory is something you have to do yourself.

If you move or rename your Harbormaster working directory, the volumes point at the old
location. Harbormaster notices this and repoints them on the next run, by deleting the
stale volume record so that Compose recreates it. Only Docker's own bookkeeping is
rewritten, your files are never touched. Docker refuses to delete a record that a
container still holds, so if the app is still running, Harbormaster stops with an error
telling you to run `docker compose down` in the app's repo directory first.


## Mounting the repository

Sometimes you want the app's repository itself inside the container, for example to read
a file from the repo without copying it into the image. Harbormaster sets
`${HM_REPO_DIR}` to the app's checkout for that:

```yaml
    volumes:
      - ${HM_REPO_DIR}/scripts:/scripts
```

Managed volumes have no equivalent for this, so `${HM_REPO_DIR}` is the way to do it. It
is not needed often.


## The older approach: path variables

Before managed volumes existed, you mounted Harbormaster's directories by writing its
paths into your Compose file with environment variables. This still works, and there are
no plans to remove it, but new apps should use managed volumes instead.

Harbormaster sets these variables when it runs Compose:

* `${HM_DATA_DIR}` - The app's data that you want to persist. Stored in the `data/`
  directory, under the main Harbormaster working directory.
* `${HM_CACHE_DIR}` - Any data you don't want to keep. Stored in the `caches/`
  directory, under the main Harbormaster working directory.
* `${HM_REPO_DIR}` - The app's repository, as described above.

Compose replaces them with the proper directory names (without trailing slashes), so the
`volumes` section of your Compose file looks something like this:

```yaml
volumes:
  - ${HM_DATA_DIR}/my_data:/some_data_dir
  - ${HM_DATA_DIR}/foo:/home/foo
  - ${HM_CACHE_DIR}/my_cache:/some_cache_dir
```

Each mount should be a different subdirectory. You can also mount `${HM_DATA_DIR}`
itself, if the app only needs one directory.

The drawback, and the reason managed volumes exist, is that if you run a Compose command
by hand (e.g. `docker compose logs`), Compose complains that those variables are not
set, and you have to set them yourself, possibly to something meaningless.

:::{admonition} Historical note
:class: warning

Docker Compose v1.x did not support environment variables in its YAML files, so
Harbormaster used something called **replacements**. Replacements were basically
template variables, that looked like `{{ HM_DATA_DIR }}`, and were written into the YAML
file itself, when Harbormaster pulled it into the repo.  Unfortunately, this made the
files incompatible with Compose, and invalid YAML.

When Compose v2 added environment variable support, there was much rejoicing, as this
meant that Harbormaster no longer needs to hackily rewrite the YAML file with values,
and does not need two different lists of variables (environment variables and
replacements variables), we can just use environment variables for everything.

As of this writing, Harbormaster actually supports **both** approaches, and using
replacements will work fine (a variable `FOO` under the `replacements` key is written
into the YAML wherever you put `{{ HM_FOO }}`), even though this documentation only
mentions the "environment variable" approach, as I got too excited about it and decided
to only mention that as the way forward. Do note that the two lists stay separate:
replacements are not added to the environment, so `${FOO}` will not see them.

In reality, however, after trying it for a bit, it appears to be much more awkward than
replacements. With replacements, all the required data is already in the YAML file, and
you can run, for example `docker compose logs` without having to specify any variables
in your environment (the volumes/paths/etc have already been replaced into the YAML
file).

I mention this here because you may find environment variables annoying as well. Instead
of removing replacements completely, I think that, in the future, I will mention both
approaches in the documentation (and their pros/cons), and leave it up to the user to
select one or the other.

Thank you for reading my inane ramblings!

Stavros

*(Later note: managed volumes are the answer to this complaint. The paths are in the
Compose file, as with replacements, but the file stays valid Compose.)*
:::
