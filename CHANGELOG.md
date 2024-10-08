# Changelog


## Unreleased

### Features

* Print a completion message to the console. [Stavros Korokithakis]

* Change the cron interval in the Docker container to 10min. [Stavros Korokithakis]

### Fixes

* Don't try to pull buildable images (fixes #18) [Id an]

* Run the Docker image entrypoint under dumb-init. [Stavros Korokithakis]


## v0.3.4 (2023-07-31)

### Features

* Add the `HM_` vars to the environment so they can be used in Compose v2 files. [Stavros Korokithakis]

### Fixes

* Fix wrong paths when launching Docker Compose. [Stavros Korokithakis]


## v0.3.3 (2023-07-23)

### Fixes

* Add missing crond invocation back. [Stavros Korokithakis]

* Don't complain about the directory if we restart the container. [Stavros Korokithakis]


## v0.3.2 (2023-07-23)

### Fixes

* Fix tests. [Stavros Korokithakis]

* Fix the Harbormaster Docker container. [Stavros Korokithakis]

* Fix issue with the Harbormaster Docker image not being able to find the data dir. [Stavros Korokithakis]

* Add docker-cli-compose to the Dockerfile. [Stavros Korokithakis]


## v0.3.1 (2023-07-22)

### Features

* Add git-crypt to the Docker image. [Stavros Korokithakis]

### Fixes

* Change Compose filename. [Stavros Korokithakis]

* Don't restart apps when their configuration hasn't been updated. [葛上昌司]

* Move the --version command to the right place. [Stavros Korokithakis]


## v0.3.0 (2023-03-01)

### Features

* Add docker image with webhook support. [Jonas Seydel]

### Fixes

* Upgrade Click (fixes #9) [Stavros Korokithakis]

* Be more defensive when loading the config. [Stavros Korokithakis]

* Fix the configuration directory having the wrong relative path base (fixes #12) [Stavros Korokithakis]


## v0.2.1 (2022-06-28)

### Features

* Implement test mode. [Stavros Korokithakis]

### Fixes

* Remove what looks like leftover debugging code but whose importance nobody can be sure of. [Stavros Korokithakis]

* Improve compatibility with earlier Docker versions. [Stavros Korokithakis]

* Remove the need for passing the data path to the HM container. [Stavros Korokithakis]

* Forward environment variables from the host to the Dockerized HM instance. [Stavros Korokithakis]


## v0.1.20 (2021-11-14)

### Features

* Restart an app if its environment vars change. [Stavros Korokithakis]

* Add image pruning config option. [Stavros Korokithakis]

* Allow Docker-supported installations. [Stavros Korokithakis]

### Fixes

* Fix wrong volume path when Harbormaster is deployed inside Docker. [Stavros Korokithakis]


## v0.1.19 (2021-10-09)

### Features

* Add YAML environment files. [Stavros Korokithakis]

* Add n8n app. [Stavros Korokithakis]

* Add default values to templates. [Stavros Korokithakis]

* Add Octoprint app config. [Stavros Korokithakis]

* Add executable building. [Stavros Korokithakis]

### Fixes

* Don't try to stop an app if its repo dir doesn't exist. [Stavros Korokithakis]

* Fix changelog display. [Stavros Korokithakis]


## v0.1.18 (2021-09-19)

### Features

* Add ztncui app. [Stavros Korokithakis]

### Fixes

* Don't pull disabled apps, no good can come of it. [Stavros Korokithakis]


## v0.1.17 (2021-09-13)

### Fixes

* Streamline repository updates and improve change detection (fixes #3) [Stavros Korokithakis]

* Do not pull disabled apps. [Stavros Korokithakis]

* Fail gracefully if no configuration is specified. [Stavros Korokithakis]


## v0.1.16 (2021-08-12)

### Fixes

* Fix Compose variables not getting rendered in some cases. [Stavros Korokithakis]


## v0.1.15 (2021-06-21)

### Features

* Change `compose_filename` to `compose_config` [Stavros Korokithakis]

* Retry git operations on failure. [Ali Piccioni]

* Add bundled apps. [Stavros Korokithakis]


## v0.1.14 (2021-05-19)

### Fixes

* Exit with a 1 if any of the apps failed to deploy. [Stavros Korokithakis]


## v0.1.13 (2021-05-18)

### Fixes

* Pull images before starting app. [Stavros Korokithakis]


## v0.1.12 (2021-05-18)

### Features

* Add the HM_REPO_DIR variable. [Stavros Korokithakis]

### Fixes

* Improve starting/stopping of apps. [Stavros Korokithakis]


## v0.1.10 (2021-05-13)

### Features

* Show better error messages. [Stavros Korokithakis]

### Fixes

* Fix erroneous overwriting of replacements. [Stavros Korokithakis]

* Fix error when environment variables are not strings. [Stavros Korokithakis]

* Build containers when starting. [Stavros Korokithakis]


## v0.1.9 (2021-05-12)

### Features

* Allow retrieving replacements and env vars from files. [Stavros Korokithakis]


## v0.1.8 (2021-05-10)

### Fixes

* Stop containers properly. [Stavros Korokithakis]


## v0.1.7 (2021-05-10)

### Features

* Add "enabled" flag. [Stavros Korokithakis]


## v0.1.6 (2021-05-10)

### Fixes

* Gracefully stop containers most of the time. [Stavros Korokithakis]

* Reset repository more forcefully when pulling. [Stavros Korokithakis]

* Rename the default config file. [Stavros Korokithakis]


## v0.1.5 (2021-05-10)

### Features

* Add replacements feature. [Stavros Korokithakis]


## v0.1.4 (2021-05-09)

### Features

* Add environment variables to the config. [Stavros Korokithakis]


## v0.1.3 (2021-05-06)

### Features

* Add the "branch" and "compose_filename" config keys. [Stavros Korokithakis]


## v0.1.2 (2021-04-26)

### Fixes

* Support Python 3.6 and up. [Stavros Korokithakis]


## v0.1.1 (2021-04-25)

### Features

* Add version command-line option. [Stavros Korokithakis]

* Add directories. [Stavros Korokithakis]

### Fixes

* Fetch before trying to check for changes. [Stavros Korokithakis]


