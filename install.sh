#!/usr/bin/env bash
# Quick installation script for Moodle Desktop Calendar & Reminders

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=========================================================="
echo "Installing Moodle Desktop Calendar & Reminders"
echo "=========================================================="

# Check Python 3
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Run python install script
python3 "$SCRIPT_DIR/main.py" --install

echo "=========================================================="
echo "[OK] Installation complete!"
echo "To launch the calendar widget, run:"
echo "   python3 main.py"
echo "Or search for 'Moodle Calendar' in your Ubuntu application menu."
echo "=========================================================="
