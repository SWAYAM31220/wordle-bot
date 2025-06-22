#!/bin/bash
echo "🔧 Cleaning up environment..."
pip uninstall -y telegram || true
pip install --upgrade pip
pip install -r requirements.txt
