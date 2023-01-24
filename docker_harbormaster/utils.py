import sys
from pathlib import Path
from typing import Dict
from typing import Tuple

import attr

ARCHIVES_DIR_NAME = "archives"
REPOS_DIR_NAME = "repos"
CACHES_DIR_NAME = "caches"
DATA_DIR_NAME = "data"

# We use a single cache file in the root of the base directory. It's a JSON file
# containing hashes of various user-provided files, and we use it to check if the files
# have changed since the previous run.
CACHE_FILE_NAME = ".harbormaster.cache"


@attr.s(auto_attribs=True)
class Paths:
    """
    The relevant working paths for this specific configuration run.

    This class is a singleton containing the paths for the entire run (ie there isn't
    one class instance per app).
    """

    workdir: Path
    # The directory the configuration file is located in.
    config_dir: Path
    archives_dir: Path
    repos_dir: Path
    caches_dir: Path
    data_dir: Path
    cache_file: Path

    def create_directories(self):
        """Create all the necessary directories."""
        for directory in (
            self.archives_dir,
            self.repos_dir,
            self.caches_dir,
            self.data_dir,
        ):
            directory.mkdir(exist_ok=True)

    @classmethod
    def for_workdir(cls, workdir: Path, config_dir: Path):
        """Derive the working paths from a base workdir path."""
        return cls(
            workdir=workdir,
            config_dir=config_dir,
            data_dir=workdir / DATA_DIR_NAME,
            archives_dir=workdir / ARCHIVES_DIR_NAME,
            repos_dir=workdir / REPOS_DIR_NAME,
            caches_dir=workdir / CACHES_DIR_NAME,
            cache_file=workdir / CACHE_FILE_NAME,
        )


@attr.s(auto_attribs=True)
class AppPaths:
    workdir: Path
    repo_dir: Path
    cache_dir: Path
    data_dir: Path
    config_dir: Path

    @classmethod
    def from_paths(cls, paths: "Paths", app_id: str) -> "AppPaths":
        """Create an AppPaths instance for a specific app."""
        return cls(
            workdir=paths.workdir,
            repo_dir=paths.repos_dir / app_id,
            cache_dir=paths.caches_dir / app_id,
            data_dir=paths.data_dir / app_id,
            config_dir=paths.config_dir,
        )


def options_to_dict(options: Tuple[str]) -> Dict[str, str]:
    """
    Turn a Click-provided tuple of options into a dictionary.

    The tuple that Click provides looks like `("FOO=bar", "BAZ=hey")`, and we turn it
    into {"FOO": "bar", "BAZ": "hey"}.
    """
    options_dict = {}
    for option in options:
        if "=" not in option:
            sys.exit(
                "Invalid environment or replacement parameter specified, (missing `=`)."
            )
        key, value = option.split("=", 1)
        options_dict[key] = value
    return options_dict
