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


How does it work?
-----------------

Let's say you have a bog-standard Compose-packaged app in a git repository::


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
a config file::

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
directory into the Harbormaster-provided directory instead::

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

For example::

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
