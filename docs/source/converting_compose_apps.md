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
## Handling data directories

Due to the way Compose files work, you need to do some extra work to properly
tell Harbormaster about your volumes.

Harbormaster provides two kinds of directories: Data and cache.

**Data** is anything that you want to keep. Data directories will never be deleted,
if you remove an app later on, its corresponding data directory will be moved
under the `archives/` directory and renamed to `<appname>-<deletion date>`.

**Cache** is anything you don't care about. When you remove an app from the config,
the cache dir is deleted.

Harbormaster provides some environment variables you can use in your Compose file to
allow mounting these directories as volumes.

* `${HM_DATA_DIR}` - The app's data that you want to persist. Will be stored in the
  `data/` directory, under the main Harbormaster working directory.
* `${HM_CACHE_DIR}` - Any data you don't want to keep. Will be stored in the `cache/`
  directory, under the main Harbormaster working directory. Harbormaster doesn't do
  anything special with this directory, the separation between `data/` and `cache/` is
  just in case you want to separate data into a directory you want to back up and one
  you don't.
* `${HM_REPO_DIR}` - The app's repository. Use this if you want to mount the app's
  directory itself, for example to access some of the repo's files that you don't want
  to copy into the container.

Compose will replace them with the proper directory names (without trailing slashes), so
the `volumes` section of your Compose file in your repository should look something like
this:

```yaml
volumes:
  - ${HM_DATA_DIR}/my_data:/some_data_dir
  - ${HM_DATA_DIR}/foo:/home/foo
  - ${HM_CACHE_DIR}/my_cache:/some_cache_dir
```

One issue here might be that, if you try to run a Compose command (e.g. `docker compose
logs`), Compose might complain that those variables are not set. In that case, you will
have to set them yourself (possibly to something generic, since they don't always
matter).


(managed-volumes)=
## Managed volumes

If you don't want to sprinkle `${HM_DATA_DIR}` all over your Compose file, Harbormaster
can manage your named volumes for you instead. Add `manage_volumes: true` to the app in
your Harbormaster config file:

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
host, exactly like the bind mounts above. `config` will live in
`data/myapp/config`, and `cache-transcode` will live in `caches/myapp/cache-transcode`.
Volumes whose name starts with `cache-` go to the cache directory, everything else goes
to the data directory.

The upshot is that your Compose file stays a normal Compose file. You can run `docker
compose logs` (or any other command) without setting any environment variables, and the
data is still in a plain directory you can back up, exactly as before. Data directories
are archived when you remove the app, and cache directories are deleted, just like with
`${HM_DATA_DIR}` and `${HM_CACHE_DIR}`.

Harbormaster leaves alone any volume that declares its own `driver`, `driver_opts`,
`external` or `name` key, so you can still opt individual volumes out.

### Migrating to managed volumes

If you name a volume the same as the directory you used before, it points at the same
place, so there's nothing to move. These two are equivalent:

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
location. Harbormaster notices this and repoints them on the next run. This only rewrites
Docker's own bookkeeping, your files are never touched.

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
replacements will work fine (Harbormaster just inserts all the replacements variables
into the enviroment as well), even though this documentation only mentions the
"environment variable" approach, as I got too excited about it and decided to only
mention that as the way forward.

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
:::
