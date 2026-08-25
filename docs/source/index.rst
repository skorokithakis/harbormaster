Introduction
============


.. raw:: html

   <img
     class="align-right"
     src="_static/logo.jpg"
     alt="A vector graphics man in naval uniform."
     style="min-width: 120px; width: 40vw; max-width: 200px;"
   >

Do you have apps you want to deploy to a server, but Kubernetes is way too heavy?
Harbormaster is for you.

Harbormaster is a small container orchestrator that lets you run multiple Docker Compose
applications on a single host, with automatic deploys/restarts, simply by pushing to a
git repo.

If you want an LLM to set up your Harbormaster app for you, point it at
https://harbormaster.readthedocs.io/en/latest/llms.txt. That file is a single-page
guide to everything an agent needs to write your configuration and convert your
Compose app.


Running your first app
----------------------

Here's how to get started with Harbormaster:

Create a new directory somewhere, and ``cd`` into it:

.. code-block:: bash

    $ mkdir mydir
    $ cd mydir

Create a file in it called ``harbormaster.yml``, with these contents:

.. code-block:: yaml

    apps:
      hello_world:
        url: https://github.com/skorokithakis/harbormaster.git
        compose_config:
        - apps/hello_world/docker-compose.yml

This is the configuration file that tells Harbormaster what to run. This will run the
"Hello world" app from the Harbormaster repository itself.

Then, run Harbormaster (no need to have it installed beforehand):

.. code-block:: bash

    $ docker run \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -v (pwd):/config \
        -v (pwd):/main \
        stavros/harbormaster

You should see Docker pull down the Harbormaster container, start it, and then
Harbormaster will look at its configuration file, pull the repo, and run the Compose app
inside.

Now, visit http://localhost:8000, and Harbormaster will greet you.

You can press Ctrl-C to stop Harbormaster, and ``docker stop <container id>`` to stop
the app. You will notice that Harbormaster has created various directories (``caches``,
``data``, ``repos``) in your directory. That's where Harbormaster stores everything.


How does it work?
-----------------

Let's say you have a bog-standard Compose-packaged app in a git repository:

.. code-block:: yaml

    services:
      main:
        build: .
        volumes:
          - ./data:/app_data
        ports:
          - 8080:8080
        restart: unless-stopped

You want this deployed onto some server, but you want something that can check your repo
every so often, see if there are any changes, and deploy/restart your app if so.

That's what Harbormaster does. You run its Docker container on the server, and give it
a config file:

.. code-block:: yaml

    apps:
      myapp:
        url: https://github.com/yourusername/myapp.git

Harbormaster will look at its config file, clone the ``myapp`` repo, and run ``docker
compose up`` on it. Harbormaster will run periodically, pull the repo, and restart your
Docker containers if there's a change.

**NOTE:** Harbormaster does not provide ingress, you'll need to bring your own. It just
runs your apps.


What about my data, though?
---------------------------

Excellent question, your application has data you want to persist. Harbormaster
provides its own directories for that, and it can manage the named volumes in your
Compose file so that they are stored there.

Declare plain named volumes, the way any Compose app would:

.. code-block:: yaml

    services:
      main:
        build: .
        volumes:
          - app-data:/app_data
        ports:
          - 8080:8080
        restart: unless-stopped

    volumes:
      app-data:

Then set ``manage_volumes: true`` for the app in your Harbormaster config file:

.. code-block:: yaml

    apps:
      myapp:
        url: https://github.com/yourusername/myapp.git
        manage_volumes: true

Harbormaster backs the ``app-data`` volume with the directory
``data/myapp/app-data``, inside its working directory, so all your apps' data ends up
neatly under a single directory that you can back up. A volume whose name starts with
``cache-`` goes under ``caches/`` instead, which is where you put data you don't need
to keep. You can declare as many volumes as you want.

Your Compose file stays an ordinary Compose file, so running ``docker compose logs``
(or any other Compose command) by hand in the repository directory works with nothing
extra to set up.

Enabling ``manage_volumes`` is strongly recommended. There is also an older approach,
which writes ``${HM_DATA_DIR}`` into the Compose file itself; it still works, but new
apps should not use it. Both are described in :ref:`the handling data section
<handling-data-directories>`.

Now you can read on about :doc:`how to install Harbormaster <installation>`.


.. toctree::
   :hidden:
   :maxdepth: 2
   :caption: Contents:

   index
   installation
   configuration
   converting_compose_apps
   best_practices
   testing
   examples
   bundled_apps
