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
Z connects automatically during app startup after the HERA and Tango connection attempts. The Z connection button remains available for manual disconnect or recovery.

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
7. If using Z, confirm `Live Z` after automatic connection, focus each site, then `Add New` or `Update` in `Saved Sites`.
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

With Hera SDK 1.5.2 or newer, the app uses the current HyperCube spectral-sampling API, explicitly enables exposure/frame-count normalization (`NormalizationAll`), and keeps apodization at the SDK default (`-1.0`). These processing settings and the SDK version are written to logs and ENVI descriptions.

## Stage, Saved Sites, And Z

`Saved Sites` stores site number, name, XY, active ROI, and Z when Micro-Manager Z is connected. If Z is unavailable, a dummy `0.000` placeholder is stored and is not treated as a real focus target.

Use `Export` to save the complete Saved Sites table as CSV and `Import` to restore it. The CSV preserves XY, Z, real-Z state, and per-site ROI, allowing large wafer layouts to survive an app restart and be reviewed outside the app.

`Wafer Grid` generates the centered 52-chip layout `4/6/8/8/8/8/6/4`. Align the same chip landmark for `R4-C4`, `R4-C5`, and `R5-C4` with the Live View cross and capture their stage coordinates; the app derives the rotated row/column vectors, applies the configured landmark-to-center XY offset, replaces Saved Sites, and orders the generated sites in a serpentine scan. The current ROI and Z are copied to every generated site.

`Dual-Die Grid` preserves the original grid tool and adds a 23-carrier layout `3/5/7/5/3`. Capture the top-left corner of `R3-C4`, `R3-C5`, and `R4-C3`; the app maps the measured 14.9 x 16 mm carrier vectors to two 10 x 6.5 mm dies per carrier and creates a centered five-point `2/1/2` sampling pattern in each die. The four outer points use `X = +/-2 mm` and `Y = +/-1 mm`, giving 4 mm horizontal and 2 mm vertical spacing around the center point. It generates 230 named sites in serpentine order and copies the current ROI and Z.

### 7 x 9 Well Mesh Workflow

`7 x 9 Well Mesh` generates 63 sites for a 7-row by 9-column section of 150 um wells at nominal 300 um center-to-center pitch. It uses three measured well centers to account for sample translation and rotation, and three focused Z values to interpolate the sample plane.

1. Connect the Tango stage and Micro-Manager Z, then set and apply the acquisition ROI. Keep this ROI unchanged throughout calibration and scanning.
2. Enable `Cross` in Live View and click `Center`. The Cross must remain at the same position relative to the ROI for all three calibration points.
3. Open `Stage > Saved Sites > Grid > 7 x 9 Well Mesh`.
4. Move to the top-left well of the intended mesh. Align that well's center with the Cross, focus Z, and click `Capture` for `R1-C1`.
5. Move to the top-right well in the same row, align and focus it in the same way, then capture `R1-C9`.
6. Move to the bottom-left well in the same column as the first point, align and focus it, then capture `R7-C1`.
7. Leave `Stage Y offset [mm]` at `-0.018000` for the measured setup, or enter a newly measured value. This is a global Tango Stage Y correction, not an offset along the rotated mesh row direction.
8. Click `Generate 63 Sites` and confirm replacement of the current Saved Sites. Export an existing Saved Sites table first if it must be retained.
9. Verify the generated grid with `Go To` at `R01-C01`, `R01-C09`, `R07-C01`, and center site `R04-C05` before starting a full acquisition.
10. Export the verified Saved Sites table as CSV so the calibrated grid can be restored later.

Capture the calibration points while the well center is on the Cross; do not manually apply the Y correction before Capture. The app applies the offset after interpolation to every generated position. For example, a captured Stage Y of `-9.696 mm` becomes a generated Stage Y of `-9.714 mm` with the default `-0.018 mm` offset. X, interpolated Z, mesh rotation, and the measured row/column spacing are unchanged.

The app checks that the calibration spans are approximately 2.4 mm from `R1-C1` to `R1-C9` and 1.8 mm from `R1-C1` to `R7-C1`, then stores the fixed ROI with every site and orders the sites in a serpentine scan. Recalibrate after changing the ROI or Cross position, repositioning or rotating the sample, changing the Tango origin, or changing the optical alignment that produced the Y offset.

### Tissue Scan Plan With 10% Overlap

Open `Stage > Saved Sites > Grid > Tissue Scan Plan (10% Overlap)` after applying a fixed ROI and starting Live View. The window has three steps:

1. **Field Calibration:** choose a clear landmark that stays visible while moving the stage. Click `Pick A`, then click the landmark in Live View near the image center. Move the stage so the same landmark appears near a side of the image, click `Pick B`, and click it again. Move it in a different direction (for example toward the bottom), then use `Pick C`. Keep the stage stopped for each click and separate captures by at least 15% of the field. The app calculates both Stage XY field vectors, including direction and rotation, and maps preview pixels back to the actual ROI. Use a profile name identifying the objective and magnification, then `Save Calibration` for reuse with unchanged optics, ROI and binning.
2. **Tissue & Focus:** the Cross is reset to the center. Move the leftmost, rightmost, topmost and bottommost tissue boundaries onto this fixed Cross and use the corresponding `Capture`. Left/right/top/bottom refer to the Live View image directions, even when they differ from the Stage axes. With `Capture focused Z` checked, focus the tissue before each Capture; the app records XYZ together. If there is nothing to focus on at an edge, uncheck it to record XY only, then add focused positions within the tissue using `Add Focus Point`. At least three non-collinear real focus readings are needed. Add a center focus point and points at visible tissue height changes. The default edge margin is 5% of one FOV on each side.
3. **Preview:** click `Preview Grid`. Adjacent centers are spaced by 90% of the calibrated field width/height, giving nominal 10% overlap in both directions. The rectangular grid covers the selected tissue bounds with the fixed ROI, including edge tiles, and follows a serpentine path. Click a tile to inspect its XYZ and use `Go To Tile` to check its initial focus. The preview reports tiles beyond the area covered by the measured focus points; those Z values need particular attention. `Generate Saved Sites` replaces the current table after confirmation when it is nonempty.

Initial Z uses a fitted tilt plane with inverse-distance interpolation of the measured focus residuals. It preserves each measured focus value and can follow sampled local height changes, but is not autofocus and cannot detect unsampled bumps. After generation, use Saved Sites `Go To` and `Update` to refine any tile focus, then export the final table as CSV. Choose the desired data products and use `Run One Loop` to acquire the tissue once.

`Export Plan` in the calibration Preview saves the generated layout as a JSON snapshot containing calibration, boundaries, focus samples, tile row/column labels, XY/Z, ROI, overlap and image-oriented positions in FOV units. These are planned positions, not a list of acquired data files or a ready-to-use Fiji configuration. After manual Saved Site corrections, use `Scan Layout > Save Plan` to save the current associated sites, including changed XYZ, names, per-site ROI and real-Z flags; removed associated sites are omitted. Newly generated tile names are `R001-C001`, etc.; normal acquisition naming and trigger logs associate them with the saved data.

Generating tissue sites also opens `Scan Layout`. Reopen it from `Stage > Saved Sites > Grid > Scan Layout`. The layout stays available independently of the calibration window, including while `Run One Loop` or `Run Timelapse` runs. An orange outline marks the site reported in Run Status, and a green outline shows the current fixed-ROI footprint from the latest Stage XY readback. The footer displays site, app state and reported XY. It reuses existing position polling without extra hardware queries; readback may lag during stage movement. A different ROI/orientation or disconnected stage suppresses the green footprint and displays a notice. Closing the layout cancels its UI refresh timer.

Click a tile in `Scan Layout` to select it (blue outline) and inspect its saved XYZ. Clicking does not move hardware. After generating/restoring Saved Sites, press `Go To` to move to that tile's saved XY/Z and restore its ROI. Once the stage is stopped, adjust focus with the existing Z controls and click `Update Z`. It reads a real Z in the background and updates only that tile's Z and real-Z flag, keeping XY and ROI unchanged. Update is rejected if the stage is not at the selected tile, moves during the read, or returns an unsafe Z. Use `Save Plan` to retain the correction. Go To, Z update and trial scan actions are blocked while acquisition or a site sequence is running.

For a stitching check, select a tile and click `Run 2x2 Test`. The app finds a complete adjacent 2 x 2 block containing that tile, using inward neighbors at grid edges when necessary, and runs those four Saved Sites once in their existing serpentine order. It uses the normal output folder, selected export products, saved-Z checks, dwell, retries and stop/pause controls. The right-side `Sites` selection is not changed, so a subsequent normal `Run One Loop` still uses the original selection. The trial is unavailable if no complete neighboring block exists or the tiles have not been generated/restored into Saved Sites.

To restore a scan after a restart, open `Grid > Scan Layout`, click `Load Plan`, choose the JSON file, then click `Generate Sites`. The app restores the file's tile order, exact XYZ and per-site ROI without requiring Live View calibration or refitting Z. It validates coordinates, unique site names, real-Z flags and the current Safe Z range before changing the table; existing Saved Sites are replaced only after confirmation. Restore is blocked during acquisition, stage motion or timelapse. Generating sites does not move hardware or start acquisition. Check alignment and focus using Saved Sites `Go To` before selecting data products and starting `Run One Loop`.

`Load Plan` alone only opens the layout, allowing inspection before restoring sites. Within the same session, the layout follows edits or renames of generated/restored Saved Sites. Loading a layout file uses matching Saved Site names for display when available; `Generate Sites` always restores the file's coordinates, rather than coordinates from an existing table with matching names. Previously exported tile names are preserved when loading older plans. CSV export/import remains available for the site table.

Reuse absolute XYZ only when the specimen position and Stage origin are unchanged; after repositioning or rotating the specimen, capture new boundaries/focus or register the old layout before running. Keep the objective, magnification and binning consistent with the saved field calibration. The green `Current ROI` rectangle is the field footprint at the most recently reported Stage XY, while the orange `Active Site` rectangle identifies the running site. Neither is a detected tissue outline.

Changing ROI, live-frame geometry or binning invalidates the current setup. Recalibrate after changing objective or magnification. A saved field calibration can be reused for another tissue with unchanged optics, but capture new boundaries and focus points after repositioning the specimen. The well-mesh `-0.018 mm` Y offset does not apply to Tissue Scan.

Before a full scan, acquire a small 2 x 2 area and check the actual saved-image overlap and orientation. The specified 10% is nominal; positioning/calibration error still needs to be checked on hardware. Tissue capture and generation messages appear in `hera_background_status.log` with the prefix `Tissue Scan`.

Enabling `Cross` places it at the center pixel of the current live image. Click within Live View to pin it elsewhere, or use `Center` to restore the current full-frame/ROI image center.

Saved Z movement is always enabled for `Run One Loop` and `Run Timelapse`:

- Micro-Manager Z must be connected.
- Every selected site must have a real saved Z.
- Saved Z must be inside `Safe Z` range. Default: `0 - 11000 um`.
- Single Z moves must be within `Max Jump`. Default: `50 um`.
- Each site runs `XY -> saved Z -> dwell -> HERA acquisition`.

`Go To` also moves to the saved Z when a real saved Z exists and Z is connected.

The timelapse `Sites` field accepts `all`, comma-separated site numbers, and ranges such as `1-5`. While a timelapse is running, press Enter or leave the field after editing it; the valid new selection is applied when the next cycle starts, without changing the current cycle.

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
