#!/bin/sh
set -e
cd "$(dirname "$0")"

echo "Installing frontend dependencies..."
cd frontend && npm install && cd ..

echo "Linking bodaqs_analysis..."
ln -sfn ../../analysis/bodaqs_analysis api/bodaqs_analysis

echo "Installing API dependencies..."
cd api && pip install -r requirements.txt && cd ..

echo ""
echo "Done. Start dev servers with:"
echo "  terminal 1: cd api && uvicorn bodaqs_api.main:app --reload"
echo "  terminal 2: cd frontend && npm run dev"
