Introduction
============

Do you have apps you want to deploy to a server, but Kubernetes is way too much?
Harbormaster is for you.

Harbormaster is a small and simple container orchestrator that lets you easily deploy
multiple Docker-Compose applications on a single host.

Note that Harbormaster does not provide ingress, you'll need to bring your own. It just
runs your apps.


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

What about my data, though?
---------------------------

Excellent question, your application has data you want to persist. For tidiness,
Harbormaster provides its own mountpoint where you should persist the data. All you need
to do, is change your app's Compose file to mount the ``app_data`` directory into the
Harbormaster-provided directory instead::

    services:
      main:
        build: .
        volumes:
          - ${HM_DATA_DIR}:/app_data
        ports:
          - 8080:8080
        restart: unless-stopped

Now all your apps' data will be stored neatly under ``harbormaster-main/data/myapp/``.

That's it!

Now you can read on about :doc:`how to install Harbormaster <installation>`.


.. toctree::
   :hidden:
   :maxdepth: 2
   :caption: Contents:

   index
   installation
