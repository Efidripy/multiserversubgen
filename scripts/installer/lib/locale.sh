#!/bin/bash

# Force a sane UTF-8 runtime for installer output regardless of host defaults.
export LANG="${LANG:-C.UTF-8}"
export LC_ALL="${LC_ALL:-C.UTF-8}"
export LANGUAGE="${LANGUAGE:-en_US:en}"
export PYTHONUTF8=1
export PYTHONIOENCODING="${PYTHONIOENCODING:-UTF-8}"

# Installer UI language selection placeholder.
# Supported target languages for future message catalogs:
#   en, ru, es
export INSTALLER_LANG="${INSTALLER_LANG:-en}"
