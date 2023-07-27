Configuring Harbormaster
========================

Harbormaster uses a single YAML configuration file to manage the deployment of
Compose apps. Below is an example of a typical configuration file:

```yaml
config:
  prune: true
apps:
  myapp:
    url: https://github.com/someuser/somerepo.git
    branch: main
    environment:
      FOO: bar
      MYVAR: 1
    environment_file: "somefile.txt"
  otherapp:
    url: https://gitlab.com/otheruser/otherrepo.git
    compose_config:
      - docker-compose.yml
      - docker-compose.harbormaster.yml
    environment_file: "somefile.yml"
  oldapp:
    enabled: false
    url: https://gitlab.com/otheruser/otherrepo.git
```

## Configuration directives

- `config`: Top-level configuration options.
  - `prune`: If set to `true`, it prunes all unused system images after a run to save
    space on the host. Be careful, as it will delete unused Docker images on your
    system.
- `apps`: A list of applications to deploy.
  - `myapp`: The name of the application. It can be anything you want.
    - `url`: The git repository URL to clone.
    - `branch`: The branch to deploy.
    - `environment`: The environment variables to run Compose with.
    - `environment_file`: A file to load environment variables from. The file must
      consist of lines in the form of key=value. The filename is relative to the
      Harbormaster config file (this file). The file can also be a YAML file with the
      .yml extension, containing a single YAML collection of string values. Variables in
      the `environment` key take precedence over variables in the file.
  - `otherapp`: Another application to deploy.
    - `compose_config`: The Compose config filename, if it's not `docker-compose.yml`,
      or if you want to use Harbormaster-specific overrides.
    - `environment_file`: A YAML environment file.
  - `oldapp`: An old application that shouldn't be run.
    - `enabled`: If set to `false`, the app will not be run.
    - `url`: The git repository URL to clone. Two apps can use the same repo.

To execute Harbormaster, run `harbormaster run` in the same directory as the
configuration file. Harbormaster will parse the file, automatically download the
repositories mentioned in it and keep them up to date.

**Note:** Ensure that the Compose config in each of the repos does not use the
`container_name` directive, otherwise Harbormaster might not always be able to terminate
your apps when necessary.
