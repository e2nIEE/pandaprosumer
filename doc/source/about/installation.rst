.. _installation:

Installation
=====================

Through pip
------------
The easiest way to install pandapipes is through pip:

1. Open a command prompt (e.g. start –> cmd on windows systems)


2. Install pandaprosumer by running::

    pip install pandaprosumer


Without pip
------------

If you don't have internet access on your system or don't want to use pip for some other reason, pandaprosumer can also
be installed without using pip:

    Download and unzip the current pandaprosumer distribution from PyPi under 'Download files'.

    Open a command prompt (e.g. start > cmd on windows systems) and navigate to the folder that contains the setup.py file with the command cd <folder> ::

        cd %path_to_pandaprosumer%\pandaprosumer-x.x.x\

    Install pandaprosumer by running::

        python setup.py install


To install the latest development version of pandaprosumer from github, simply follow these steps:

1. Download and install git.


2. Open a git shell and navigate to the directory where you want to keep your pandaprosumer repository.


3. Run the following git command::

     git clone https://github.com/senergyNets/pandaprosumer.git


4. Navigate inside the repository and check out the develop branch::

      cd pandaprosumer
      git checkout develop

5. Open a command prompt (cmd, git bash or miniconda command prompt) and navigate to the folder where the pandaprosumer files are located. Run::
     
       pip install -e .

Test Installation
==========================

If you want to be really sure that everything works fine, run the pandaprosumer test suite:

Install pytest if it is not yet installed on your system::

      pip install pytest

Run the pandaprosumer test suite::

       import pandaprosumer.test
       pandrosumer.test.run_tests()

If everything is installed correctly, all tests should pass or xfail (expected to fail).



