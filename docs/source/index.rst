Harbormaster documentation
==========================

Do you have apps you want to deploy to a server, but Kubernetes is way too much?
Harbormaster is for you.

Harbormaster is a small and simple container orchestrator that lets you easily deploy
multiple Docker-Compose applications on a single host.

It does this by taking a list of git repository URLs that contain Docker
Compose files and running the Compose apps they contain. It will also handle
updating/restarting the apps when the repositories change.


.. toctree::
   :maxdepth: 2
   :caption: Contents:

   installation.md



Indices and tables
==================

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
