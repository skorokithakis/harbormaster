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

Harbormaster is a small and simple container orchestrator that lets you easily deploy
multiple Docker-Compose applications on a single host.


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
        url: https://gitlab.com/stavros/harbormaster.git
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
the app. You will notice that Harbormaster has created various directories (``cache``,
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
        url: github.com/yourusername/myapp.git

Harbormaster will look at its config file, clone the ``myapp`` repo, and run ``docker
compose up`` on it. Harbormaster will run periodically, pull the repo, and restart your
Docker containers if there's a change.

**NOTE:** Harbormaster does not provide ingress, you'll need to bring your own. It just
runs your apps.


What about my data, though?
---------------------------

Excellent question, your application has data you want to persist. For tidiness,
Harbormaster provides its own mountpoint where you should persist the data (for more
information on this, see :ref:`the handling data directories section <handling-data-directories>`).

All you need to do, is change your app's Compose file to mount the ``app_data``
directory into the Harbormaster-provided directory instead:

.. code-block:: yaml

    services:
      main:
        build: .
        volumes:
          - ${HM_DATA_DIR}/data:/app_data
        ports:
          - 8080:8080
        restart: unless-stopped

Harbormaster will ensure ``${HM_DATA_DIR}`` expands to ``harbormaster-main/data/myapp``,
so all your apps' data will be stored neatly under ``harbormaster-main/data/myapp/data``.
You don't have to mount the volume under ``/data``, you can mount it directly to
``${HM_DATA_DIR}`` if you want. You can also use as many mounts as you want, just make
sure each is a different subdirectory.

For example:

.. code-block:: yaml

    services:
      main:
        build: .
        volumes:
          - ${HM_DATA_DIR}/data:/app_data
          - ${HM_DATA_DIR}/other_data:/more_data
          - ${HM_CACHE_DIR}/some_cache:/cache1
          - ${HM_CACHE_DIR}/some_other_cache:/cache2
        ports:
          - 8080:8080
        restart: unless-stopped

You can do this with any variable, there's no magic (the variables above just
straight-up expand to a dir name).

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
