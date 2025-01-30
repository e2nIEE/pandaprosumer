# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys
from sphinx_pyproject import SphinxConfig
sys.path.insert(0, os.path.abspath('../../'))

project = 'Pandaprosumer'
copyright = '2024, Uni Kassel, European Institute for Energy Research'
author = 'Uni Kassel, European Institute for Energy Research'
release = '0.1'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration
config = SphinxConfig("../../pyproject.toml")

extensions = ['sphinx_rtd_theme',  'sphinx.ext.intersphinx', 'sphinx.ext.mathjax', 'sphinx.ext.autodoc', 'numpydoc',
              'sphinx.ext.autosummary', 'sphinxcontrib.bibtex']

# Path to the list of references (bibtex file)
bibtex_bibfiles = ['references.bib']

# Add any paths that contain templates here, relative to this directory.
templates_path = ['_templates']
exclude_patterns = ['_build', '**.ipynb_checkpoints']



# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']

autosummary_generate = True

