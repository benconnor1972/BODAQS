#!/bin/sh
set -e
cd "$(dirname "$0")"

echo "Installing frontend dependencies..."
cd frontend && npm install && cd ..

echo "Installing API dependencies..."
cd api && pip install -r requirements.txt && cd ..

echo ""
echo "Done. Start all services with:"
echo "  vercel dev -L"
