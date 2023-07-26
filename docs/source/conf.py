from typing import List

# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html
# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = "Harbormaster"
copyright = "2023, Stavros Korokithakis"
author = "Stavros Korokithakis"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions: List[str] = ["myst_parser"]

templates_path: List[str] = ["_templates"]
exclude_patterns: List[str] = []


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "sphinx_rtd_theme"

myst_enable_extensions = [
    "colon_fence",
    "fieldlist",
    "html_admonition",
    "linkify",
    "replacements",
    "smartquotes",
    "strikethrough",
    "tasklist",
]


html_theme_options = {
    "collapse_navigation": False,
    "navigation_depth": 2,
}
