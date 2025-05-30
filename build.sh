#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

echo "Starting build process..."

# 1. Install Python dependencies
echo "Installing dependencies..."
pip install -r requirements.txt

# 2. Run Django collectstatic
echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

echo "Build process completed."