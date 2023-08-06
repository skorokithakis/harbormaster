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
