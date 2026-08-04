# Walkthrough Review — Post-Refactoring Audit

Thorough audit of the refactoring performed in the previous session. Three parallel audit agents inspected every deployment script, service Python file, and documentation file for regressions, stale references, and correctness issues.

---

## Audit Summary

| Category | Files Checked | Clean | Issues Found |
|:---|:---:|:---:|:---:|
| Deployment Scripts (`.sh`, `.bat`, `.ps1`, `.service`) | 12 | 12 | 0 |
| Service Python Files (`app.py`, pipeline scripts) | 10 | 8 | 2 |
| Documentation (`.md` files) | 10 | 4 | 6 |
| Config (`.toml`, `.txt`, `.gitignore`) | 3 | 3 | 0 |
| **Total** | **35** | **27** | **8 files with issues** |

---

## 🔴 Bugs Introduced by Refactoring (Fix Required)

### Issue 1 — Duplicate `except` block in plotter (BROKEN CODE)

**File:** [`services/plotter/app.py`](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/services/plotter/app.py) **Lines 35-41**

The `replace_file_content` edit left behind a duplicate `except` block — the second one is unreachable dead code:

```diff
     try:
         cfg = load_config(CONFIG_PATH)
         return resolve_db_dsn(cfg, MODE_PATH)
     except Exception as e:
         print(f"Error loading DSN: {e}")
         return "postgresql://admin:admin@172.21.108.86:5432/daq_db"
-    except Exception as e:
-        print(f"Error loading DSN: {e}")
-        return "postgresql://admin:admin@172.21.108.86:5432/daq_db"
```

---

### Issue 2 — Duplicate section header in README.md

**File:** [`README.md`](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/README.md) **Lines 181-183**

The `replace_file_content` edit produced two consecutive identical `## 4. Configuration Documentation` headers:

```diff
 ## 4. Configuration Documentation
-
-## 4. Configuration Documentation
```

---

### Issue 3 — Duplicate section number `## 6.` in README.md

**File:** [`README.md`](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/README.md) **Line 264**

Both "Project Structure" and "Troubleshooting Tips" use `## 6.`:

```diff
-## 6. Troubleshooting Tips
+## 7. Troubleshooting Tips
```

---

### Issue 4 — 3 stale `USB4716\config.json` paths in DEPLOY_WINDOWS.md

**File:** [`DEPLOY_WINDOWS.md`](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/DEPLOY_WINDOWS.md) **Lines 179, 457, 477**

These were missed during the bulk path update:

```diff
-Edit `USB4716\config.json` to match your environment:
+Edit `services\daq_usb4716\config.json` to match your environment:
```
```diff
-- Verify the DSN in `USB4716\config.json` points to the correct host/port
+- Verify the DSN in `services\daq_usb4716\config.json` points to the correct host/port
```
```diff
-2. Check `DEVICE_DESCRIPTION` in `USB4716\config.json` matches exactly
+2. Check `DEVICE_DESCRIPTION` in `services\daq_usb4716\config.json` matches exactly
```

---

## ⚠️ Stale Documentation References (Should Fix)

### Issue 5 — Stale `plot_service/` paths in plotter DEVELOPMENT.md

**File:** [`services/plotter/DEVELOPMENT.md`](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/services/plotter/DEVELOPMENT.md) **Lines 111, 118**

Two file links still reference old `plot_service/` path:

```diff
-[plot_service/templates/index.html](file:///...plot_service/templates/index.html)
+[services/plotter/templates/index.html](file:///...services/plotter/templates/index.html)

-[plot_service/static/app.js](file:///...plot_service/static/app.js)
+[services/plotter/static/app.js](file:///...services/plotter/static/app.js)
```

---

### Issue 6 — Stale `musashi_II/` in WINDOWS_SETUP.md

**File:** [`services/musashi_ii/WINDOWS_SETUP.md`](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/services/musashi_ii/WINDOWS_SETUP.md) **Line 124**

Directory tree diagram still shows old casing:

```diff
-musashi_II/
+musashi_ii/
```

---

### Issue 7 — Stale `plot_from_db.py` / "Matplotlib" in architecture docs

**Files:**
- [`docs/architecture/context.md`](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/docs/architecture/context.md) **Lines 15, 24**
- [`docs/architecture/sequences/streaming_pipeline.md`](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/docs/architecture/sequences/streaming_pipeline.md) **Line 7**

References `plot_from_db.py` and "Matplotlib Plotter" but the current plotter is `services/plotter/app.py` using Plotly.js.

---

### Issue 8 — Stale comment in mockup_stream_to_db.py

**File:** [`services/daq_usb4716/mockup_stream_to_db.py`](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/services/daq_usb4716/mockup_stream_to_db.py) **Line 203**

```diff
-        # Session metadata table (mirrors db_setup.sql)
+        # Session metadata table (mirrors scripts/sql/db_setup.sql)
```

---

## 📝 Pre-Existing Issues Discovered (Not Caused by Refactoring)

### Issue 9 — `watchdog.ps1` missing port 8082

**File:** [`deploy/windows/watchdog.ps1`](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/deploy/windows/watchdog.ps1) **Line 18**

`$Ports = @(8080, 8081, 8083, 8084)` — **port 8082 (Musashi II) is missing** from the health check array.

### Issue 10 — Musashi II missing from DEPLOY docs expected output & service tables

- [`DEPLOY_LINUX.md`](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/DEPLOY_LINUX.md) Lines 76-88 (expected output), Lines 155-164 (service table & lsof command)
- [`DEPLOY_WINDOWS.md`](file:///Users/faiisu/projects.nosync/DAQ-USB-4716/DEPLOY_WINDOWS.md) Lines 204-218 (expected output)

All predate the refactoring — Musashi II was added to `run.sh`/`run.bat` but the docs were never updated to include it.

### Issue 11 — DEPLOY_WINDOWS.md shows `venv\Scripts` instead of `.venv\Scripts`

**Line 206**: Expected output says `venv\Scripts\python.exe` but `install_deps.bat` creates `.venv`.

---

## Walkthrough.md Accuracy Assessment

| Walkthrough Claim | Verified? | Notes |
|:---|:---:|:---|
| Services moved under `services/` | ✅ | All 5 services correctly relocated |
| Entrypoints renamed to `app.py` | ✅ | All 4 Flask services renamed |
| `shared/` module created & importable | ✅ | `config.py`, `db.py`, `process_manager.py` all import cleanly |
| `scripts/sql/db_setup.sql` created | ✅ | Proper SQL schema with hypertable |
| Empty dirs `db_setup.sql/` & `web_gui/` removed | ✅ | Confirmed gone |
| Deploy scripts updated | ✅ | `run.sh` and `run.bat` paths correct |
| `.gitignore` updated | ✅ | All 12 service-specific paths updated |
| `py_compile` passed | ✅ | Clean exit code 0 |
| **Missing: plotter has duplicate except block** | ❌ | Not mentioned — introduced by refactoring |
| **Missing: README has duplicate headers** | ❌ | Not mentioned — introduced by refactoring |
| **Missing: several docs still have stale paths** | ❌ | DEPLOY_WINDOWS.md, DEVELOPMENT.md, architecture docs |

> [!WARNING]
> The walkthrough claims the refactoring is complete, but **4 bugs were introduced** and **7 documentation files still contain stale references**. These need to be fixed before the refactoring can be considered done.

---

## Proposed Fix Plan

### Phase 1 — Fix Refactoring Bugs (4 items)
1. Remove duplicate `except` block in `services/plotter/app.py`
2. Remove duplicate `## 4.` header in `README.md`
3. Renumber `## 6. Troubleshooting` → `## 7.` in `README.md`
4. Fix 3 remaining `USB4716\config.json` paths in `DEPLOY_WINDOWS.md`

### Phase 2 — Fix Stale Documentation (4 items)
5. Update `plot_service/` → `services/plotter/` in `DEVELOPMENT.md`
6. Update `musashi_II/` → `musashi_ii/` in `WINDOWS_SETUP.md`
7. Update `plot_from_db.py` / "Matplotlib" refs in `docs/architecture/`
8. Update stale comment in `mockup_stream_to_db.py`

### Phase 3 — Fix Pre-Existing Issues (3 items, optional)
9. Add port 8082 to `watchdog.ps1` health check
10. Add Musashi II to DEPLOY docs expected output & service tables
11. Fix `.venv` vs `venv` in DEPLOY_WINDOWS.md expected output

### Verification
```bash
# Syntax check after fixes
python3 -m py_compile services/plotter/app.py

# Grep for any remaining stale references
grep -rn "USB4716\|musashi_II\|mushashi_IV\|plot_service\|web_gui\.py" \
  --include="*.py" --include="*.md" --include="*.sh" --include="*.bat" --include="*.ps1" .
```
