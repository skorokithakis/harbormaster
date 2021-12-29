# Changelog


## Unreleased

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


