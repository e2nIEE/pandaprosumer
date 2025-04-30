.. _const_profile_controller:

=========================
Const Profile Controller
=========================

Controller Data
==================

.. autoclass:: pandaprosumer.controller.data_model.const_profile.ConstProfileControllerData
    :members:

Controller
==============

This controller is made for the use with the time series module to read data from a DataSource and write it to the prosumer.
The controller can write the values to the any input of a controller in the same prosumer.

.. autoclass:: pandaprosumer.controller.const_profile.ConstProfileController
    :members:


Period Handling
================

A period needs to be defined to use the `ConstProfileController`.

If no period is explicitly set for the controller, it will try to detect a `period` column in the DataFrame provided by the DataSource.
If this column exists, a default period will automatically be created and used.

If neither a period is defined nor a `period` column is present in the DataFrame, an error will be raised.