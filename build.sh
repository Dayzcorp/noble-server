#!/usr/bin/env bash

# Upgrade essential tools first
python -m pip install --upgrade pip setuptools wheel

# Then install project dependencies
pip install -r requirements.txt
