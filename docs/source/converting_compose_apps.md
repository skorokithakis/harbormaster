# Integrating Compose apps with Harbormaster

If you have a Compose app and you want to make sure it integrates with Harbormaster,
there are a few things you need to do.


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
