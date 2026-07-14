# Hyperspectral Scanning Acquisition APP

Windows desktop app for controlling a NIREOS HERA hyperspectral camera, Tango XY stage, and optional Nikon Ti Z through Micro-Manager. It supports site-guided hyperspectral acquisition, flatfield normalization, ENVI export, and long timelapse scans.

The top-level `run_app.py` is only a launcher. The app logic lives in the tracked `hera_app/` package.

## Main Features

- HERA camera connection, live preview, HDR, exposure/gain, ROI, and hyperspectral acquisition.
- Tango XY stage control with saved sites, per-site ROI, and selected-site loops/timelapse.
- Nikon Ti Z control through Micro-Manager, including saved Z, safe Z range, and max-jump protection.
- Flatfield reference acquire/import, plus `Raw`, `Flatfield`, and `Normalized` display/export.
- ENVI export for `_raw`, `_ref`, and `_nrm`, with HyperLAB-compatible headers.
- Background logs, issue summaries, trigger logs, and helper-service acquisition for longer runs.

## Requirements

- Windows x64 and Python 3.
- NIREOS Hera SDK / `HeraAPI.dll`, valid SDK license, HERA device configuration, and camera drivers.
- Tango stage DLL/runtime when XY stage control is needed.
- Micro-Manager 2.0 and `pymmcore` when Nikon Ti Z control is needed.

Current default Micro-Manager config:

```text
C:\Program Files\Micro-Manager-2.0\NikonTi_Z.cfg
```

This config should contain only the Ti scope/Z drive, without lamp or shutter devices.

## Run

From the repository folder:

```powershell
cd "C:\BIOS DATA\Lina\PYTHON\hera-trigger-app"
python run_app.py
```

Default output/log folder:

```text
C:\BIOS DATA\jiayi\APP
```

## Code Structure

```text
hera-trigger-app/
    run_app.py                    launcher
    hera_app/
        app.py                    main Tk app and shared state
        controllers/              HERA, Tango, Micro-Manager, NIS-Z wrappers
        helpers/                  HERA helper service/process logic
        mixins/                   UI and feature modules
```

Important mixins:

- `ui_builder.py`: UI construction and widget behavior.
- `device.py`: HERA/Tango connection, license, preflight, helper service.
- `acquisition.py`: parameter apply, acquisition, callbacks, saving.
- `timelapse.py`: one-loop/timelapse worker, site retries, trigger log.
- `stage.py`: XY motion, saved sites, per-site ROI/Z.
- `micro_z_mixin.py`: Nikon Ti Z connection, moves, safe range, max jump.
- `flatfield.py`: reference acquire/import and normalization.
- `live_view.py`, `roi.py`, `hyperspectral_viewer.py`, `export.py`: display, ROI, viewer, and ENVI/HyperLAB export.

## Typical Workflow

1. Launch the app and connect HERA/Tango.
2. Check `Status`, `License`, `Live`, and `Stage`.
3. Use `Preflight` before long runs to check SDK/license/export folder/disk space.
4. Set camera `Parameters`: gain, exposure, and `16-bit HDR`.
5. Set `Control Bar` options: spectral mode, sampling, bands, averaging, binning, and data type.
6. Select ROI, or clear ROI for full-frame workflow.
7. If using Z, click `Connect Z`, focus each site, then `Add New` or `Update` in `Saved Sites`.
8. Choose export folder/name/stamp and selected products: `_raw`, `_ref`, `_nrm`.
9. Run `Start Single Acquisition`, `Run One Loop`, or `Run Timelapse`.

## Camera And Spectral Settings

- `Exposure` and `Gain` apply when you press `Enter`, click away from the field, or press `Set`.
- `16-bit HDR` calls the SDK HDR setting before acquisition. Saved-data HDR status should be verified from SDK data/cube HDR flags when available.
- `Control Bar` settings should be applied with `Set`.
- `Bands = 0` lets the SDK use its recommended/default band count.
- `Sampling` can be `Uniform lambda` or `Uniform nu` when supported by the installed SDK.
- Unsupported or read-only settings are logged instead of silently ignored.

## ROI

ROI can be selected in Live View or entered as width/height. `Apply Box` uses the corner fields, `Square` makes a square ROI, and `Clear` returns to full-frame workflow.

The app keeps the user-selected ROI for display/export even when the SDK reports ROI as full-frame or read-only. If the SDK returns a full-frame cube, the app can crop display and ENVI output to match the selected ROI.

## Stage, Saved Sites, And Z

`Saved Sites` stores site number, name, XY, active ROI, and Z when Micro-Manager Z is connected. If Z is unavailable, a dummy `0.000` placeholder is stored and is not treated as a real focus target.

Saved Z movement is always enabled for `Run One Loop` and `Run Timelapse`:

- Micro-Manager Z must be connected.
- Every selected site must have a real saved Z.
- Saved Z must be inside `Safe Z` range. Default: `0 - 11000 um`.
- Single Z moves must be within `Max Jump`. Default: `50 um`.
- Each site runs `XY -> saved Z -> dwell -> HERA acquisition`.

`Go To` also moves to the saved Z when a real saved Z exists and Z is connected.

The timelapse `Sites` field accepts `all`, comma-separated site numbers, and ranges such as `1-5`.

## Acquisition And Timelapse

- `Start Single Acquisition`: acquire the current position/ROI once.
- `Run One Loop`: run selected sites once.
- `Run Timelapse`: repeat selected-site loops.
- `Interval (min)`: wait time from the end of one loop to the start of the next loop. `0` starts the next loop immediately.
- During interval waiting, the app restarts live view when possible so focus can be checked.
- `Pause` pauses between safe steps and can be pressed again to resume.
- `Stop Timelapse` stops after the current safe point.
- `Abort Acquisition` aborts the active HERA acquisition.

Trigger logs include site, cycle, XY, target Z, confirmed Z, Z delta, ROI, export path, and status.

## Flatfield

`Flatfield Acquire` acquires a reference cube from the current ROI/position and stores it as the active flatfield. `Import Ref` loads a saved reference. `Clear` removes the active flatfield.

With a compatible flatfield:

- Hyperspectral View can display `Normalized`, `Raw`, or `Flatfield`.
- `_raw` saves the sample cube.
- `_ref` saves the active matching reference.
- `_nrm` saves sample divided by reference.

Export choices are independent of the current display mode.

## Export, HyperLAB, And Logs

The `Export` panel controls folder, name, optional timestamp, product selection, and notes. Notes are written into ENVI metadata/descriptions.

`Open in HyperLAB` opens every `.hdr` saved in the most recent export. If no export is remembered from the current session, it falls back to the newest export header in the output folder.

Main log files in the output folder:

```text
hera_background_status.log
hera_last_issues.log
hera_fatal_crash.log
helper_cache\
```

Use `Open Log` for the issue summary. Use `hera_background_status.log` for detailed timing, SDK callbacks, movement, retry, and saving events.

## Local Files And Development

Private/local materials are ignored by Git, including:

- `NIS-Z-Bridge/`
- `design_previews/`
- `local/`
- runtime caches such as `__pycache__/`
- output data and logs

For code changes:

```powershell
python -m py_compile <touched-python-files>
git status
git add <changed-files>
git commit -m "<area>: <summary>"
git push
```

For UI or hardware changes, verify manually in the app and inspect `hera_background_status.log`.

## License

No open-source license file has been added yet. Add one before distributing the code outside the project.
