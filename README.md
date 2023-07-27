Harbormaster
============

Do you have apps you want to deploy to a server, but Kubernetes is way too much?
Harbormaster is for you.

Harbormaster is a small and simple container orchestrator that lets you easily deploy
multiple Docker-Compose applications on a single host.

It does this by taking a list of git repository URLs that contain Docker
Compose files and running the Compose apps they contain. It will also handle
updating/restarting the apps when the repositories change.

Please [visit the documentation](https://harbormaster.readthedocs.io/en/latest/) for
more details.


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

See more details in [the documentation](https://harbormaster.readthedocs.io/en/latest/).
