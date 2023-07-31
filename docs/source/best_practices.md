# Best practices

This section includes some best practices, to get you started.


## Recommended repository layout

Usually, you will have one repository per app. However, for small apps, like ones that
already have a Docker container on the Docker Hub (and thus just need a Compose file),
it might be more convenient to store the Compose file(s) in the same repository as the
Harbormaster config, one branch per app.

That way, you can pull the Harbormaster configuration and all the app definitions in the
same way, from the same repository, and specify the branch to load the app from with the
`branch` directive in the config.


## Recommended secrets handling

The recommended way for handling secrets is to add plaintext files to
a `secrets/` subdirectory of the repository (e.g. `secrets/myservice.txt`) and use
[git-crypt](https://github.com/AGWA/git-crypt) to encrypt them. That way, it's easy to
add more secrets to the repository, but also only authorized people and the deployment
server has access to the files.
