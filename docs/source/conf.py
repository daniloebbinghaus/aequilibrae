# -*- coding: utf-8 -*-
#
# Configuration file for the Sphinx documentation builder.
#
# This file does only contain a selection of the most common options. For a
# full list see the documentation:
# http://www.sphinx-doc.org/en/master/config

# -- Path setup --------------------------------------------------------------

# If extensions (or modules to document with autodoc) are in another directory,
# add these directories to sys.path here. If the directory is relative to the
# documentation root, use os.path.abspath to make it absolute, like shown here.

import os
import sys

import sphinx_theme

try:
    from aequilibrae.paths.__version__ import release_version
except ImportError as e:
    sys.path.insert(0, os.path.abspath("../.."))
    from aequilibrae.paths.__version__ import release_version
    import warnings

    warnings.warn(f"It is really annoying to deal with Flake8 sometimes. {e.args}")

#

# -- Project information -----------------------------------------------------

project = "AequilibraE"
copyright = "2018, Pedro Camargo"
author = "Pedro Camargo"

# The short X.Y version
version = release_version
# The full version, including alpha/beta/rc tags
release = "30/07/2018"

# -- General configuration ---------------------------------------------------

# If your documentation needs a minimal Sphinx version, state it here.
#
# needs_sphinx = '1.0'

# Add any Sphinx extension module names here, as strings. They can be
# extensions coming with Sphinx (named 'sphinx.ext.*') or your custom
# ones.
extensions = [
    "nbsphinx",
    "sphinx_gallery.load_style",
    "sphinx_gallery.gen_gallery",
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx.ext.coverage",
    "sphinx.ext.mathjax",
    "sphinx_autodoc_annotation",
    'sphinx.ext.autosummary',
    'sphinx_git',
]

sphinx_gallery_conf = {
    'examples_dirs': ['examples'],  # path to your example scripts
    'gallery_dirs': ['_auto_examples'],  # path to where to save gallery generated output
}

# Add any paths that contain templates here, relative to this directory.
templates_path = ["_templates"]

# The suffix(es) of source filenames.¶
# You can specify multiple suffix as a list of string:
#
# source_suffix = ['.rst', '.md']
source_suffix = ".rst"

# The master toctree document.
master_doc = "index"

# The language for content autogenerated by Sphinx. Refer to documentation
# for a list of supported languages.
#
# This is also used if you do content translation via gettext catalogs.
# Usually you set "language" from the command line for these cases.
language = None

# List of patterns, relative to source directory, that match files and
# directories to ignore when looking for source files.
# This pattern also affects html_static_path and html_extra_path .
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", '*.pyx']

# The name of the Pygments (syntax highlighting) style to use.
pygments_style = "sphinx"
highlight_language = 'none'
# -- Options for HTML output -------------------------------------------------

# The theme to use for HTML and HTML Help pages.  See the documentation for
# a list of builtin themes.
#
# html_theme = "pyramid"
html_theme = "neo_rtd_theme"
html_theme_path = [sphinx_theme.get_html_theme_path(html_theme)]

# html_theme_options = {
#     "body_max_width": '70%',
#     'sidebarwidth': '20%'
# }


# Add any paths that contain custom static files (such as style sheets) here,
# relative to this directory. They are copied after the builtin static files,
# so a file named "default.css" will overwrite the builtin "default.css".
html_static_path = ["_static"]

# -- Options for HTMLHelp output ---------------------------------------------

# Output file base name for HTML help builder.
htmlhelp_basename = "AequilibraEdoc"

# -- Options for LaTeX output ------------------------------------------------

latex_elements = {}

# Grouping the document tree into LaTeX files. List of tuples
# (source start file, target name, title,
#  author, documentclass [howto, manual, or own class]).
latex_documents = [(master_doc, "AequilibraE.tex", "AequilibraE Documentation", "Pedro Camargo", "manual")]

# -- Options for manual page output ------------------------------------------

# One entry per manual page. List of tuples
# (source start file, name, description, authors, manual section).
man_pages = [(master_doc, "aequilibrae", "AequilibraE Documentation", [author], 1)]

# -- Options for Texinfo output ----------------------------------------------

autodoc_default_options = {
    'members': 'var1, var2',
    'member-order': 'bysource',
    'special-members': '__init__',
    'private-members': False,
    'undoc-members': True,
    'exclude-members': '__weakref__',
    'inherited-members': False,
    'show-inheritance': False,
    'autodoc_inherit_docstrings': False
}

autodoc_member_order = 'groupwise'

autoclass_content = "class"  # classes should include both the class' and the __init__ method's docstring

autosummary_generate = True

# Grouping the document tree into Texinfo files. List of tuples
# (source start file, target name, title, author,
#  dir menu entry, description, category)
texinfo_documents = [
    (
        master_doc,
        "AequilibraE",
        "AequilibraE Documentation",
        author,
        "AequilibraE",
        "One line description of project.",
        "Miscellaneous",
    )
]
