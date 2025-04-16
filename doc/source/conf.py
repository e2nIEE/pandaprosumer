# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

import os
import sys
sys.path.insert(0, os.path.abspath('../../'))

project = 'Pandaprosumer'
copyright = '2024, Uni Kassel, European Institute for Energy Research'
author = 'Uni Kassel, European Institute for Energy Research'
release = '0.1'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = ['sphinx.ext.autodoc',
              'sphinx.ext.autosummary',
              'sphinx.ext.viewcode',
              'sphinxcontrib.bibtex',
              "nbsphinx"]

latex_engine = 'pdflatex'

latex_elements = {
    'papersize': 'a4paper',
    'pointsize': '11pt',
    'preamble': r'''
\usepackage{amsmath,amssymb}
\usepackage{graphicx}
\usepackage{unicode-math}
''',
}

templates_path = ['_templates']
exclude_patterns = []

# Path to the list of references (bibtex file)
bibtex_bibfiles = ['references.bib']


# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
html_css_files = ['custom.css']


autosummary_generate = True

# Custom CSS to handle text overflow
html_css_files = [
    'custom.css',
]