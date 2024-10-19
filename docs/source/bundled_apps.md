# Bundled apps

Harbormaster includes some built-in apps in its repository, for your
convenience. Check out the
[apps](https://github.com/skorokithakis/harbormaster/-/tree/master/apps) directory for the
Compose files. You can include them in your Harbormaster config directly, with no other
configuration.

Here's an example that includes the [Plex media server](https://www.plex.tv/) and
[ZTNCUI](https://github.com/key-networks/ztncui):

```yaml
apps:
  plex:
    url: https://github.com/skorokithakis/harbormaster.git
    compose_config: apps/plex-bridge.yml
    environment:
      ADVERTISE_IP: "<the IP to advertise>"
      TZ: "<your timezone, e.g. Europe/Athens>"
      PLEX_CLAIM: "<your Plex claim code>"
    replacements:
      HOSTNAME: "<your hostname>"
      MEDIA_DIR: "<your video directory on the host>"

  ztncui:
    url: https://github.com/skorokithakis/harbormaster.git
    environment:
      ZTNCUI_PASSWD: "<some password>"
    compose_config: apps/ztncui/docker-compose.harbormaster.yml

  octoprint:
    url: https://github.com/skorokithakis/harbormaster.git
    compose_config: apps/octoprint/docker-compose.harbormaster.yml
```
