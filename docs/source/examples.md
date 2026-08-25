# Examples

This is an example of the configuration for a Harbormaster-compatible Compose
app that adheres to some best practices.

We'll use two Compose files, a main one (for local development) and
a Harbormaster-specific one, mount a volume, and pass secrets as environment variables.

The main `docker-compose.yml` file is pretty straighforward, doesn't mount any volumes
and uses an environment variable as a secret.

`docker-compose.yml`:

```yaml
services:
  main:
    command: ./myscript
    image: myapp
    build: .
    restart: unless-stopped
    environment:
      - SOME_SECRET
```

The Harbormaster-specific `docker-compose.harbormaster.yml` file is small, it overrides
the command (so the script starts from the `/state` directory) and declares the volume
that holds the app's state.

`docker-compose.harbormaster.yml`:

```yaml
services:
  main:
    command: bash -c 'cd /state; /code/myscript'
    volumes:
      - state:/state/

volumes:
  state:
```

The Harbormaster config file is very straightforward, it specifies a repo URL, turns on
managed volumes, and lists the two Compose configuration files. The `docker-compose.yml`
is specified first, and the Harbormaster override is second, so the command is
overridden properly.

`harbormaster.yml`:

```yaml
apps:
  myapp:
    url: https://github.com/myuser/myrepo.git
    manage_volumes: true
    compose_config:
      - docker-compose.yml
      - docker-compose.harbormaster.yml
```

Because `manage_volumes` is on, Harbormaster backs the `state` volume with the directory
`data/myapp/state` in its working directory, so the app's state is a plain directory on
the host that you can back up.

This is a good way to add Harbormaster configuration files with very few lines of
configuration. Compose merges the `volumes` of a service by the path inside the
container, so a later file that mounts something else at `/state` would replace the
earlier mount rather than add to it. That works, but it makes the two files harder to
read together, so it's better to define a different volume and change your command to
use that directory, as we've done above.
