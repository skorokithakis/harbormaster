# Examples

This is an example of the configuration for a Harbormaster-compatible Compose
app that adheres to some best practices.

We'll use two Compose files, a main one (for local development) and
a Harbormaster-specific one, mount volumes, and pass secrets as environment variables.

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
the command (so the script starts from the `/state` directory) and the volumes, so the
`/state` directory maps to the host's data directory.

`docker-compose.harbormaster.yml`:

```yaml
services:
  main:
    command: bash -c 'cd /state; /code/myscript'
    volumes:
      - ${HM_DATA_DIR}:/state/
```

The Harbormaster config file is very straightforward, it specifies a repo URL
and the two Compose configuration files. The `docker-compose.yml` is specified
first, and the Harbormaster override is second, so the command is overridden
properly.

`harbormaster.yml`:

```yaml
apps:
  myapp:
    url: https://github.com/myuser/myrepo.git
    compose_config:
      - docker-compose.yml
      - docker-compose.harbormaster.yml
```

This is a good way to add Harbormaster configuration files with very few lines of
configuration. Keep in mind that you unfortunately cannot override volumes with this
technique, as Docker will complain that the volume has been specified twice.

It's better to define a different volume and change your command to use that directory,
as we've done above.
