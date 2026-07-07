# Hyperspectral Scanning Acquisition APP

Windows desktop app for controlling a NIREOS HERA hyperspectral camera, Tango XY stage, and optional Nikon Ti Z through Micro-Manager for site-guided acquisitions, flatfield normalization, and timelapse scans.

The app is designed for software-triggered acquisition. It keeps the Python app logic in the tracked `hera_app/` package and uses the top-level `AppHeraTriggerPython0417.py` only as a launcher.

## Main Capabilities

- Connect to the HERA camera through the Hera SDK and to the Tango XY stage.
- Show a live camera preview with auto contrast, saturation overlay, crosshair profiles, zoom/pan, and ROI selection.
- Apply camera parameters safely by stopping live capture when needed, setting parameters, reading back SDK state, and restarting live view.
- Select an ROI from the live image or by entering width/height, then use that ROI for acquisition, display, and export.
- Save stage sites with per-site ROI, then run one loop or a timed timelapse over selected site numbers.
- Read, jog, and manually move Nikon Ti Z through Micro-Manager; saved sites can store the current Z.
- Acquire/import a flatfield reference and display/export `Raw`, `Flatfield`, and `Normalized` hyperspectral cubes.
- Export ENVI `.hdr`/data-file pairs for `_raw`, `_ref`, and `_nrm`, with HyperLAB-compatible headers.
- Keep background logs and crash/issue summaries for long runs.

## Project Structure

```text
hera-trigger-app/
    AppHeraTriggerPython0417.py   repository launcher
    hera_app/
        app.py                    app state, startup, shutdown, logging, main()
        controllers/
            hera.py               Hera SDK / HeraAPI.dll wrapper
            tango.py              Tango stage DLL wrapper
            micro_z.py            Micro-Manager MMCore Nikon Ti Z wrapper
            nis_z.py              optional local NIS Z bridge client
        tools/
            micromanager_z_probe.py standalone Nikon Ti Z read/move probe
        helpers/
            acquisition_helper.py helper-side acquisition/export logic
            hera_service.py       optional helper service process
            hera_service_client.py
            hera_service_probe.py
        mixins/
            ui_builder.py         UI construction and widget behavior
            device.py             Hera/Tango connection, license, preflight, HDR
            acquisition.py        parameter apply, acquisition, callback, saving
            timelapse.py          loop/site/timelapse worker
            live_view.py          live capture, rendering, zoom/pan/snapshot
            roi.py                ROI selection, coordinate mapping, overlays
            flatfield.py          reference acquisition/import, normalization
            hyperspectral_viewer.py band display and spectrum panel
            export.py             ENVI export, ROI crop, HyperLAB header patching
            stage.py              XY motion and saved sites
            micro_z_mixin.py      Micro-Manager Z polling and controls
            nis_z_mixin.py        optional NIS Z polling/controls
            theme.py              light/dark theme
            utils.py              safe Tk scheduling and async UI helpers
```

The parent-folder launcher at `C:\BIOS DATA\Lina\PYTHON\AppHeraTriggerPython0417.py` delegates to this repository. A separate parent-folder `hera_app` runtime mirror is not required.

## Requirements

- Windows x64.
- Python 3.
- NIREOS Hera SDK installed or `HeraAPI.dll` available.
- Active HERA SDK license on the machine.
- `HERA_DEVICES` configured for the installed HERA device configuration.
- Camera drivers/vendor services installed.
- Tango stage runtime/DLL available when stage control is needed.
- Micro-Manager 2.0 and `pymmcore` when Nikon Ti Z control is needed. The current default config path is `C:\Program Files\Micro-Manager-2.0\NikonTi_Z.cfg`, which should contain only the Ti scope/Z drive and no lamp/shutter device.

## Run

From the repository folder:

```powershell
cd "C:\BIOS DATA\Lina\PYTHON\hera-trigger-app"
python AppHeraTriggerPython0417.py
```

The current default output/log folder is:

```text
C:\BIOS DATA\jiayi\APP
```

## Typical Workflow

1. Launch the app and wait for HERA/Tango connection.
2. Check `Status`, `License`, `Live`, and `Stage` state.
3. Use `Preflight` from `Advanced` when you want to check license, SDK state, export settings, and disk space before a long run.
4. Set camera parameters in `Parameters`: gain, exposure, and `16-bit HDR`.
5. Set spectral options in `Control Bar`: spectral mode, sampling mode, bands, averaging, binning, and data type. Press `Set` after editing these controls.
6. Select or clear ROI in the `ROI` panel. The `Active ROI` line shows width, height, and area.
7. If Nikon Ti Z should be recorded, click `Connect Z` in the `Stage` tab. Then add or update sites in `Saved Sites`; each site stores the current XY, current Z, and active ROI.
8. Choose export folder/name/stamp and select exactly which products to save: `_raw`, `_ref`, and/or `_nrm`.
9. Use `Start Single Acquisition`, `Run One Loop`, or `Run Timelapse`.
10. Watch `Run Status` for Status, Site, Cycle, Next loop, Total run time, and progress. `Total run time` tracks either a running timelapse or the current single acquisition.

## Camera And Spectral Settings

The camera `Parameters` panel controls exposure, gain, and `16-bit HDR`.

`16-bit HDR` calls the Hera SDK HDR setting before acquisition. The authoritative HDR state for saved data should be taken from the SDK data/cube HDR flags, which the app logs and writes into export metadata when available.

The `Control Bar` includes:

- `Spectral`: scan mode.
- `Sampling`: `Uniform lambda` or `Uniform nu`, when supported by the installed SDK.
- `Bands`: requested number of spectral bands. `0` lets the SDK use its recommended/default value.
- `Avg`, `Bin`, and `Data`: averaging, binning, and export data type.

Some SDK versions or camera configurations may not support every setting. Unsupported/read-only settings are logged instead of stopping the whole app.

## ROI

ROI can be set by clicking two opposite corners in Live View or by editing width/height in the ROI panel. `Apply Box` uses the four corner fields, `Square` creates a square ROI from the selected box, and `Clear` returns to full-frame workflow.

The app keeps the selected export/display ROI separate from SDK ROI readback because some HERA configurations report ROI as read-only or full-frame even when ROI-limited acquisition/export is working.

When the SDK returns a full-frame hypercube, the app can still crop the ENVI output and Hyperspectral View to the selected ROI so display and saved files match.

## Stage, XY Control, And Saved Sites

The `Stage` tab shows stage connection status, live XY coordinates, and optional live Nikon Ti Z. `XY Control` can move to a target XY position or jog by the selected step size. `Z Control` connects to Micro-Manager, reads live Z, jogs Z, or moves to a typed target Z.

`Saved Sites` stores:

- Site number.
- Site name.
- X/Y position.
- Z position when Micro-Manager Z is connected, otherwise a dummy placeholder.
- Active ROI at the time the site was added or updated.

Timelapse Z auto-move is currently disabled for safety. Saved sites keep real Z values after `Connect Z`, and manual `Go To Z` is available, but timelapse movement remains XY-only unless Z auto-move is explicitly enabled later.

The timelapse `Sites` field accepts `all`, comma-separated site numbers, and ranges such as `1-5`.

## Acquisition And Timelapse

`Start Single Acquisition` acquires the current position/ROI once.

`Run One Loop` runs the selected sites once.

`Run Timelapse` repeats selected-site loops. The `Interval (min)` value is the wait time from the end of one loop to the start of the next loop; `0` starts the next loop immediately. The app also waits the configured `Dwell (s)` after moving to a site before starting acquisition.

`Pause` pauses between acquisition steps and can be pressed again to resume. `Stop Timelapse` requests the timelapse worker to stop after the current safe point. `Abort Acquisition` is for the active HERA acquisition.

## Flatfield

`Flatfield Acquire` acquires a reference cube from the current ROI/position and stores it in memory as the active flatfield. `Import Ref` loads an already saved reference for later normalization. `Clear` removes the active flatfield.

After a compatible flatfield is active:

- Hyperspectral View can display `Normalized`, `Raw`, or `Flatfield`.
- `_raw` saves the sample cube.
- `_ref` saves the active matching reference.
- `_nrm` saves sample divided by the matching reference.

Export choices are independent of the current Hyperspectral View display mode. If a product is not selected, it is not saved.

## Export And Logs

The `Export` panel controls saving folder, file name, optional timestamp, data products, and notes. Notes are written into ENVI descriptions/metadata; they are not shown as a separate image overlay.

The app writes logs in the selected/default output folder:

```text
hera_background_status.log
hera_last_issues.log
hera_fatal_crash.log
helper_cache\
```

Use `Open Log` in `Run Status` to open the short issue summary. The full background log is useful for timing acquisition, computing, saving, movement, retry, and SDK callback events.

`Open in HyperLAB` opens every `.hdr` that was actually saved in the most recent export, for example `_raw`, `_ref`, and `_nrm` when all three were selected and successfully written. If there is no remembered export from the current session, it falls back to the newest export header in the output folder.

## Local-Only Files

The following are private/local working materials and are intentionally ignored by Git:

- `NIS-Z-Bridge/`
- `design_previews/`
- `AGENDA.md`
- `local/`
- runtime caches such as `__pycache__/`
- output data and logs

Keep generated ENVI data outside the Git repository, normally in `C:\BIOS DATA\jiayi\APP`.

## Development Notes

- Keep app logic in `hera_app/`; do not add logic to the launcher.
- Prefer editing the relevant mixin/controller directly.
- Preserve user data and local-only folders.
- For Python code changes, run `python -m py_compile` on touched Python files.
- For UI/hardware changes, verify manually in the app and inspect `hera_background_status.log`.

## GitHub Workflow

For normal maintenance:

```powershell
cd "C:\BIOS DATA\Lina\PYTHON\hera-trigger-app"
git status
git add <changed-files>
git commit -m "<area>: <summary>"
git push
```

## License

No open-source license file has been added yet. Add one before distributing the code for reuse outside the project.
