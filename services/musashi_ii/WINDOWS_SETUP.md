# 🪟 MUSASHI Super Σ CMII — Windows Setup Guide

## Prerequisites

1. **Python 3.9+** — Download from [python.org](https://www.python.org/downloads/)
   - ⚠️ During installation, check **"Add Python to PATH"**
2. **USB-to-RS232 adapter driver** — Install the driver for your USB-Serial adapter
   - FTDI: [ftdichip.com/drivers](https://ftdichip.com/drivers/)
   - Prolific: [prolific.com.tw/US/ShowProduct.aspx?p_id=225&pcid=41](http://www.prolific.com.tw/US/ShowProduct.aspx?p_id=225&pcid=41)
   - CH340: [wch-ic.com/downloads/CH341SER_EXE.html](https://www.wch-ic.com/downloads/CH341SER_EXE.html)

---

## Quick Start (Automatic)

1. Copy this project folder to your Windows PC
2. Double-click **`install_windows.bat`** — This will:
   - Create a Python virtual environment (`.venv`)
   - Install all dependencies (`pyserial`, `psycopg2-binary`)
   - Run a verification test in mock mode
3. Double-click **`run_musashi.bat`** to start the service

---

## Finding Your COM Port

1. Connect the USB-to-RS232 adapter to your PC
2. Open **Device Manager** (Win+X → Device Manager)
3. Expand **"Ports (COM & LPT)"**
4. Look for your adapter, e.g., `USB Serial Device (COM3)`
5. Update `config.windows.json`:

```json
{
  "serial": {
    "port": "COM3"
  }
}
```

> **Tip:** You can also run `.\run_musashi.ps1 -ListPorts` in PowerShell to list detected COM ports.

---

## Running the Service

### Option A: Batch File (Simplest)
Double-click `run_musashi.bat` and select a mode from the menu.

### Option B: PowerShell (Advanced)
```powershell
# Interactive menu
.\run_musashi.ps1

# Direct commands
.\run_musashi.ps1 -Mode mock                     # Mock mode
.\run_musashi.ps1 -Mode real -Port COM4           # Specific COM port
.\run_musashi.ps1 -Mode real -Once                # Single read
.\run_musashi.ps1 -ListPorts                      # Show available COM ports
```

### Option C: Command Line
```cmd
# Activate virtual environment first
.venv\Scripts\activate

# Run with Windows config
python read_musashi.py --config config.windows.json

# Run in mock mode
python read_musashi.py --mock

# Run with specific port
python read_musashi.py --port COM4

# Single read
python read_musashi.py --port COM3 --once
```

---

## Running Tests

```cmd
.venv\Scripts\activate
python -m pytest test_read_musashi.py -v
```

Or without pytest:
```cmd
python -m unittest test_read_musashi.py -v
```

---

## Troubleshooting

### "Python is not recognized"
- Reinstall Python and check **"Add Python to PATH"**
- Or add manually: `System Properties → Environment Variables → Path → Add Python directory`

### "Access denied" on COM port
- Close other programs using the COM port (e.g., PuTTY, Arduino IDE)
- Run Command Prompt as Administrator

### "No COM ports detected"
- Check USB cable connection
- Install the correct USB-Serial driver (see Prerequisites)
- Try a different USB port

### "psycopg2 installation failed"
- Install `psycopg2-binary` instead (already in `requirements.txt`)
- If it still fails on Windows, install [Visual C++ Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/)

### PowerShell script won't run
- Run: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser`
- Then retry: `.\run_musashi.ps1`

---

## File Structure

```
musashi_ii/
├── read_musashi.py         # Main application (cross-platform)
├── database_handler.py     # Database operations (cross-platform)
├── config.json             # macOS/Linux config
├── config.windows.json     # Windows config (COM port)
├── requirements.txt        # Python dependencies
├── test_read_musashi.py    # Unit tests
├── run_musashi.bat         # Windows batch launcher
├── run_musashi.ps1         # Windows PowerShell launcher
├── install_windows.bat     # One-click Windows setup
└── WINDOWS_SETUP.md        # This guide
```
