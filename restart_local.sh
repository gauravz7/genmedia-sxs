#!/bin/bash

# Terminate existing uvicorn backends running on port 8011 to free it up
echo "Stopping any running backend server..."
pkill -f "uvicorn main:app" || true

# Give the OS a second to free the port
sleep 2

# Start the uvicorn API backend in the background
echo "Starting local Python backend server..."
cd backend
source venv/bin/activate
uvicorn main:app --host 0.0.0.0 --port 8011 --reload &
echo "Local server is successfully running at http://localhost:8011 ! 🚀"
