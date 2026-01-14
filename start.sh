#!/bin/bash

# OpenMP Compiler Quick Start Script
# This script sets up and runs the OpenMP online compiler

set -e  # Exit on error

echo "🔧 OpenMP Online Compiler - Quick Start"
echo "========================================"
echo ""

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

echo "✓ Python found: $(python3 --version)"

# Check if GCC is installed
if ! command -v gcc &> /dev/null; then
    echo "❌ GCC is not installed."
    echo "Install it with:"
    echo "  Ubuntu/Debian: sudo apt install gcc"
    echo "  macOS: brew install gcc"
    exit 1
fi

echo "✓ GCC found: $(gcc --version | head -n1)"

# Check OpenMP support
echo ""
echo "Testing OpenMP support..."
cat > /tmp/test_openmp.c << 'EOF'
#include <omp.h>
#include <stdio.h>
int main() {
    #pragma omp parallel
    {
        printf("Thread %d\n", omp_get_thread_num());
    }
    return 0;
}
EOF

if gcc -fopenmp /tmp/test_openmp.c -o /tmp/test_openmp 2>/dev/null; then
    echo "✓ OpenMP is supported!"
    /tmp/test_openmp > /dev/null 2>&1
    rm -f /tmp/test_openmp /tmp/test_openmp.c
else
    echo "❌ OpenMP is not supported by your GCC installation."
    echo "Please install a version of GCC with OpenMP support."
    exit 1
fi

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
if [ -f "requirements.txt" ]; then
    pip3 install -q -r requirements.txt
    echo "✓ Dependencies installed"
else
    echo "❌ requirements.txt not found!"
    exit 1
fi

# Check if files exist
echo ""
echo "Checking project files..."
if [ ! -f "app.py" ]; then
    echo "❌ app.py not found!"
    exit 1
fi
echo "✓ app.py found"

if [ ! -f "index.html" ]; then
    echo "❌ index.html not found!"
    exit 1
fi
echo "✓ index.html found"

# Start the backend
echo ""
echo "========================================"
echo "🚀 Starting the backend server..."
echo "========================================"
echo ""
echo "Backend will run on: http://localhost:5000"
echo "Open index.html in your browser to use the compiler"
echo ""
echo "Press Ctrl+C to stop the server"
echo ""

python3 app.py
