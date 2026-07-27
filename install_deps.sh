#!/bin/bash
# See: docs/architecture/context.md
# English comments only

echo "=========================================================="
echo "         MDDP Ingestion Suite - Installing Dependencies"
echo "=========================================================="

# 1. Detect uv or fallback to Python
UV_CMD=""
if command -v uv >/dev/null 2>&1; then
    UV_CMD="uv"
    echo "[SYSTEM] Detected uv package manager: $($UV_CMD --version)"
else
    echo "[SYSTEM] 'uv' not found in PATH. Checking Python fallback..."
    PYTHON_CMD=""
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD="python3"
    elif command -v python >/dev/null 2>&1; then
        PYTHON_CMD="python"
    else
        echo "[ERROR] Neither 'uv' nor Python was found on this system."
        echo "[ERROR] Please install uv (https://docs.astral.sh/uv/) or Python 3.12+."
        exit 1
    fi
    echo "[SYSTEM] Detected Python executable: $PYTHON_CMD ($($PYTHON_CMD --version 2>&1))"
fi

# 2. Set up virtual environment and install dependencies
VENV_DIR=".venv"
if [ -n "$UV_CMD" ]; then
    echo "[SYSTEM] Creating Python virtual environment using uv in ./${VENV_DIR}..."
    $UV_CMD venv $VENV_DIR
    if [ $? -ne 0 ]; then
        echo "[ERROR] Failed to create virtual environment with uv."
        exit 1
    fi
    echo "[SYSTEM] Syncing dependencies using uv..."
    if [ -f "pyproject.toml" ]; then
        $UV_CMD sync
    else
        $UV_CMD pip install -r requirements.txt
    fi
else
    if [ ! -d "$VENV_DIR" ] && [ ! -d "venv" ]; then
        echo "[SYSTEM] Creating Python virtual environment in ./${VENV_DIR}..."
        $PYTHON_CMD -m venv $VENV_DIR
        if [ $? -ne 0 ]; then
            echo "[ERROR] Failed to create virtual environment."
            exit 1
        fi
    fi
    ACT_PATH=""
    if [ -d "$VENV_DIR" ]; then
        ACT_PATH="$VENV_DIR"
    else
        ACT_PATH="venv"
    fi
    if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
        source "$ACT_PATH/Scripts/activate"
    else
        source "$ACT_PATH/bin/activate"
    fi
    echo "[SYSTEM] Installing dependencies using pip fallback..."
    python -m pip install -r requirements.txt
fi

if [ $? -eq 0 ]; then
    echo "=========================================================="
    echo "[SUCCESS] All dependencies installed successfully."
    echo "[SYSTEM] To start the background services, run: ./run.sh"
    echo "=========================================================="
else
    echo "=========================================================="
    echo "[ERROR] Failed to install dependencies."
    echo "=========================================================="
    exit 1
fi
