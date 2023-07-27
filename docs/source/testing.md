Testing your Compose apps
=========================

When converting a Compose app to work with Harbormaster, it's sometimes useful to test
it locally first. The naive way would be to write a Harbormaster configuration file,
create a repository for your app, commit the app's Compose file into it, and run
Harbormaster with the configuration file.

To make this much, *much* easier, Harbormaster includes a `harbormaster test` command.


## The `test` command

The `harbormaster test` command creates a temporary directory for data/cache/etc
directories, and runs the Compose files directly from your local directory. This
eliminates the need to commit to your app, or to write a Harbormaster configuration
file for testing purposes.

To view the available options, run `harbormaster test --help`.
