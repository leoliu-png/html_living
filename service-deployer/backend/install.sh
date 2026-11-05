#!/bin/bash
set -e
cd /Users/hao/Desktop/feedmob/service-deployer-projects/service-deployer/service-deployer/backend
rm -rf .venv
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -e ".[dev]"
echo "=== INSTALL DONE ==="
