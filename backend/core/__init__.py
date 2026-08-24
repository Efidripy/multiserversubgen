"""Production backend composition helpers.

Modules are imported explicitly by the application composition root.  Keeping
this package initializer side-effect free prevents dormant framework modules
from being loaded whenever a live ``core.*`` module is imported.
"""
