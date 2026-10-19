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

### Control Bar Presets

Choose a `Preset` and click `Load`, then click the existing `Set` button to apply it to Hera. Loading alone updates the fields without interrupting Live View. Built-in presets:

| Preset | Spectral | Bands | Avg | Bin | Sampling | Data |
| --- | --- | --- | --- | --- | --- | --- |
| Fluo | Medium | 200 | 2 | None | Uniform lambda | SinglePrecision |
| BF | Extra High | 1500 | 2 | 4x | Uniform lambda | SinglePrecision |

To keep a different combination, edit the six Control Bar fields, click `Save`, and enter a preset name. Saving an existing name asks before replacing it. Presets persist across restarts in `local/control_bar_presets.json` inside the repository; this local file is excluded from Git and independent of the output folder. Exposure, gain, HDR, ROI, sites and reference data are not included or changed. Loading is blocked during acquisition, processing, parameter application or an active site loop/timelapse (including Pause).

## ROI

ROI can be selected in Live View or entered as width/height. `Apply Box` uses the corner fields, `Square` makes a square ROI, and `Clear` returns to full-frame workflow.

The app keeps the user-selected ROI for display/export even when the SDK reports ROI as full-frame or read-only. If the SDK returns a full-frame cube, the app can crop display and ENVI output to match the selected ROI.

With Hera SDK 1.5.2 or newer, the app uses the current HyperCube spectral-sampling API, explicitly enables exposure/frame-count normalization (`NormalizationAll`), and keeps apodization at the SDK default (`-1.0`). These processing settings and the SDK version are written to logs and ENVI descriptions.

## Stage, Saved Sites, And Z

`Saved Sites` stores site number, name, XY, active ROI, and Z when Micro-Manager Z is connected. If Z is unavailable, a dummy `0.000` placeholder is stored and is not treated as a real focus target.

XY/Z movement rejects non-finite values (`NaN`, `inf`, `-inf`); Z safety bounds, Max Jump and tolerance must also be finite when set. Z defaults remain 0 to 11000 um, Max Jump 50 um and tolerance 0.5 um. Normally each Z move checks for an idle device and at least two consecutive in-tolerance position readings across the settling interval (0.2 s). If the device does not arrive within 15 s, the move fails and Stop is requested. Invalid readback, unsafe settings, failed arrival or a cancelled site move pause a running site sequence at the same site instead of consuming retries and skipping it. Fix the hardware/settings before `Resume`; Resume retries that site. Ordinary acquisition retry behavior and disk-full pause remain unchanged.

`Stop Z` no longer waits behind the long-running move request lock. MMCore calls remain serialized, but movement uses short `deviceBusy`/position polls instead of `waitForDevice`. Stop cancels the pending move/site acquisition and checks that the driver reports idle, with up to 2 s for stop confirmation. An unconfirmed stop blocks further Z movement until Stop can be confirmed. A native driver call that itself hangs cannot be preempted by these Python checks; software Stop is not a hardware emergency stop. Do not test by deliberately approaching an objective or travel limit.

For the specifically identified `NikonTI` adapter's `TIZDrive` (verified through MMCore device library/name, not just its configured label), an in-tolerance Z readback can also confirm arrival when Busy remains true, but only after at least four readings spanning 0.5 s with total variation no greater than 0.025 um. The log marks this as `NikonTI stable position (Busy still true)` rather than driver-idle confirmation. This encoder-readback check is a driver-compatibility measure, not an independent physical-motion sensor; verify it on the microscope before long unattended scans. Other adapters retain strict Busy/idle checks.

If this NikonTI device explicitly returns `Unsupported device command (11)` for Stop, the app does not repeatedly send that unsupported command. It cancels the pending action and observes position stability using the same strict 0.5 s / 0.025 um criteria before releasing the software lock. The log says `NikonTI hardware Stop is unsupported` and `Z stationary`, not `stop confirmed`: a hardware braking command was not available. Continued motion, non-finite readback or other errors (including USB failures) keep movement blocked. After updating from a session locked by the old unsupported-Stop behavior, close/restart the app and verify small `Z+`/`Z-` jogs before scanning. A subsequent Stop can also recheck stationary readback; it cannot force an unsupported device to brake.

Hera helper requests are tied to their process session and unique request ID; packets from expired sessions cannot complete a new request. Timeout/failure closes that session, requests process termination and waits up to 3 s for confirmed exit before allowing reconnection/retry. If exit is unconfirmed, the process handle is retained, camera reconnection is blocked and the site sequence pauses without skipping the sample. After resolving the stuck process, `Resume` rechecks termination before any site movement/acquisition. A manual single acquisition can be retried after recovery. Driver/camera recovery may still require restarting the app or power-cycling hardware.

After installing these safety changes, close the Micro-Manager GUI, restart this app, and confirm `Live Z` after automatic connection (or use `Connect Z`). Jog `Z+`/`Z-` with the existing 0.1 um step and check the recorded `target Z`, `confirmed Z` and `delta`. Run two saved sites with known safe Z values and confirm no unexpected safety pause. For Stop verification, use only a small safe move away from limits; check `Micro-Manager Z stop confirmed`, or the explicitly limited `Z stationary` result for NikonTI with unsupported Stop. A stopped pending site must not start Hera acquisition. Fault/timeout paths are covered by hardware-free simulation tests; a real-device long-run test is still required.

Hardware validation on 2026-10-19: manual Z jogs, saved-Z Go To, a full-frame single acquisition, and a five-cycle/two-site timelapse completed successfully. All ten timelapse acquisitions succeeded on the first attempt; the largest logged Z deviation was 0.075 um. Each cycle used its saved per-site ROI, and the next cycle began 30 s after completion of the preceding cycle, with Live restored during the interval. All ten raw data files matched their expected byte counts. This was a limited test at 10 bands, HDR off, 1 ms exposure and raw-only output, with identical XY coordinates for both sites. It does not validate real XY site-to-site travel, production-sized cubes, HDR/flatfield/normalized output, Stop under a real fault, or a 10-hour unattended run.

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

### Tissue Scan Plan

Open `Stage > Saved Sites > Grid > Tissue Scan Plan` after applying a fixed ROI and starting Live View. The window has three steps:

1. **Field Calibration:** choose a clear landmark that stays visible while moving the stage. Click `Pick A`, then click the landmark in Live View near the image center. Move the stage so the same landmark appears near a side of the image, click `Pick B`, and click it again. Move it in a different direction (for example toward the bottom), then use `Pick C`. Keep the stage stopped for each click and separate captures by at least 15% of the field. The app calculates both Stage XY field vectors, including direction and rotation, and maps preview pixels back to the actual ROI. Use a profile name identifying the objective and magnification, then `Save Calibration` for reuse with unchanged optics, ROI and binning.
2. **Tissue & Focus:** the Cross is reset to the center. Move the leftmost, rightmost, topmost and bottommost tissue boundaries onto this fixed Cross and use the corresponding `Capture`. Left/right/top/bottom refer to the Live View image directions, even when they differ from the Stage axes. With `Capture focused Z` checked, focus the tissue before each Capture; the app records XYZ together. If there is nothing to focus on at an edge, uncheck it to record XY only, then add focused positions within the tissue using `Add Focus Point`. At least three non-collinear real focus readings are needed. Add a center focus point and points at visible tissue height changes. The default edge margin is 5% of one FOV on each side.
3. **Preview:** set `Overlap [%]` in Tissue & Focus, then click `Preview Grid`. The default is 10%; values from 0% up to (but not including) 100% are accepted, including decimals. Adjacent centers are spaced by `FOV * (1 - overlap / 100)` in both calibrated directions. Very high overlap can exceed the 10,000-tile safety limit. The rectangular grid covers the selected tissue bounds with the fixed ROI, including edge tiles, and follows a serpentine path. Click a tile to inspect its XYZ and use `Go To Tile` to check its initial focus. The preview reports tiles beyond the area covered by the measured focus points; those Z values need particular attention. `Generate Saved Sites` replaces the current table after confirmation when it is nonempty.

To exclude empty or unwanted areas, select tiles and click `Delete Tiles`, then confirm once. A normal click selects one tile. Hold Ctrl and click to add/remove individual tiles; drag a box to select tiles whose centers fall inside it, or Ctrl-drag to add a box to the existing selection. Selected tiles are highlighted and the selected count is shown. Remaining tiles keep their XYZ, row/column labels and serpentine order; the tile count and focus warning count update. Keep at least one tile. Selection is cleared after deletion; Go To is available only for a single selected tile. `Export Plan` and `Generate Saved Sites` use only the remaining preview tiles. Changing overlap or edge margin requires a new `Preview Grid`; regeneration creates a fresh complete grid, restoring previously deleted preview tiles. Preview edits do not change already-generated Saved Sites until you generate them again.

Initial Z uses a fitted tilt plane with inverse-distance interpolation of the measured focus residuals. It preserves each measured focus value and can follow sampled local height changes, but is not autofocus and cannot detect unsampled bumps. After generation, use Saved Sites `Go To` and `Update` to refine any tile focus, then export the final table as CSV. Choose the desired data products and use `Run One Loop` to acquire the tissue once.

`Export Plan` in the calibration Preview saves the generated layout as a JSON snapshot containing calibration, boundaries, focus samples, tile row/column labels, XY/Z, ROI, overlap and image-oriented positions in FOV units. These are planned positions, not a list of acquired data files or a ready-to-use Fiji configuration. After manual Saved Site corrections, use `Scan Layout > Save Plan` to save the current associated sites, including changed XYZ, names, per-site ROI and real-Z flags; removed associated sites are omitted. Newly generated tile names are `R001-C001`, etc.; normal acquisition naming and trigger logs associate them with the saved data.

Generating tissue sites also opens `Scan Layout`. Reopen it from `Stage > Saved Sites > Grid > Scan Layout`. The layout stays available independently of the calibration window, including while `Run One Loop` or `Run Timelapse` runs. An orange outline marks the site reported in Run Status, and a green outline shows the current fixed-ROI footprint from the latest Stage XY readback. The footer displays site, app state and reported XY. It reuses existing position polling without extra hardware queries; readback may lag during stage movement. A different ROI/orientation or disconnected stage suppresses the green footprint and displays a notice. Closing the layout cancels its UI refresh timer.

Click a tile in `Scan Layout` to select it (blue outline) and inspect its saved XYZ. Clicking does not move hardware. After generating/restoring Saved Sites, press `Go To` to move to that tile's saved XY/Z and restore its ROI. Once the stage is stopped, adjust focus with the existing Z controls and click `Update Z`. It reads a real Z in the background and updates only that tile's Z and real-Z flag, keeping XY and ROI unchanged. Update is rejected if the stage is not at the selected tile, moves during the read, or returns an unsafe Z. Use `Save Plan` to retain the correction. Go To, Z update and trial scan actions are blocked while acquisition or a site sequence is running.

`Scan Layout > Delete Tiles` supports the same Ctrl-click and box selection and removes all selected tiles in one operation. When generated/restored in this session, their associated Saved Sites are also removed. A loaded plan that has not generated sites does not delete unrelated table entries, even when names match. Manual corrections to remaining associated sites are retained. Numbered `Sites` selections are remapped to the same surviving sites; if none of the selected sites remain, the field becomes `none` and you must select sites again before running. Use `Save Plan` to persist deletions; loading the saved file and using `Generate Sites` will not restore excluded tiles. Go To, Update Z and Run 2x2 Test require a single selected tile. Deletion is blocked during acquisition, site sequences, position reads or Z updates. Deleted areas are intentionally no longer covered by the scan.

For a stitching check, select a tile and click `Run 2x2 Test`. The app finds a complete adjacent 2 x 2 block containing that tile, using inward neighbors at grid edges when necessary, and runs those four Saved Sites once in their existing serpentine order. It uses the normal output folder, selected export products, saved-Z checks, dwell, retries and stop/pause controls. The right-side `Sites` selection is not changed, so a subsequent normal `Run One Loop` still uses the original selection. The trial is unavailable if no complete neighboring block exists or the tiles have not been generated/restored into Saved Sites.

To restore a scan after a restart, open `Grid > Scan Layout`, click `Load Plan`, choose the JSON file, then click `Generate Sites`. The app restores the file's tile order, exact XYZ and per-site ROI without requiring Live View calibration or refitting Z. It validates coordinates, unique site names, real-Z flags and the current Safe Z range before changing the table; existing Saved Sites are replaced only after confirmation. Restore is blocked during acquisition, stage motion or timelapse. Generating sites does not move hardware or start acquisition. Check alignment and focus using Saved Sites `Go To` before selecting data products and starting `Run One Loop`.

`Load Plan` alone only opens the layout, allowing inspection before restoring sites. Within the same session, the layout follows edits or renames of generated/restored Saved Sites. Loading a layout file uses matching Saved Site names for display when available; `Generate Sites` always restores the file's coordinates, rather than coordinates from an existing table with matching names. Previously exported tile names are preserved when loading older plans. CSV export/import remains available for the site table.

Reuse absolute XYZ only when the specimen position and Stage origin are unchanged; after repositioning or rotating the specimen, capture new boundaries/focus or register the old layout before running. Keep the objective, magnification and binning consistent with the saved field calibration. The green `Current ROI` rectangle is the field footprint at the most recently reported Stage XY, while the orange `Active Site` rectangle identifies the running site. Neither is a detected tissue outline.

Changing ROI, live-frame geometry or binning invalidates the current setup. Recalibrate after changing objective or magnification. A saved field calibration can be reused for another tissue with unchanged optics, but capture new boundaries and focus points after repositioning the specimen. The well-mesh `-0.018 mm` Y offset does not apply to Tissue Scan.

Before a full scan, acquire a small 2 x 2 area and check the actual saved-image overlap and orientation. The selected overlap percentage is nominal; positioning/calibration error still needs to be checked on hardware. Tissue capture and generation messages appear in `hera_background_status.log` with the prefix `Tissue Scan`.

### Live View Detail

With NumPy installed, Live View retains every spatial pixel returned by the SDK instead of reducing full frames to a 480-pixel preview. `Fit` fits the whole image into the window; `1:1` displays one source pixel per Tk image pixel. Use the zoom buttons or wheel and right-button drag to inspect other areas. At high zoom only the visible viewport is rendered. Preview updates are throttled to at most 10 per second; skipped SDK frame handles are still released.

With NumPy, the latest SDK frame is copied into an owned raw-intensity buffer. The display ROI is selected first; Auto Contrast uses its original-precision min/max, Gamma acts on that mapping, and only the final image is quantized to 8-bit. This preserves low-signal 12/16-bit variations that would otherwise be lost by reducing to 8-bit before contrast stretching. Auto still uses min/max (not percentiles); resizing and HDR switching behavior are unchanged. With Auto off, the SDK-derived effective bit depth supplies the fixed display range. Constant-valued frames use that same fixed range rather than dividing by zero. Saturation highlighting still compares raw pixels with the SDK threshold. The horizontal/vertical profiles retain their existing fixed 8-bit intensity scale and are not Auto/Gamma-stretched.

This changes only Live display and `Snap`, not camera exposure, binning, hyperspectral acquisition, saved cube data, or Tissue Scan coordinates. `Snap` uses the same original-precision mapping and saves a full-spatial-resolution 8-bit RGB PNG of the active ROI, not raw 12/16-bit data. Without NumPy, the old reduced-resolution/8-bit compatibility preview remains available and `1:1` is unavailable. The background log records `Live preview intensity mapping: raw range=..., display range=...; Auto/Gamma applied before 8-bit conversion` for the first rendered frame of a Live session. The separate `Live profile 8-bit range` log describes the fixed-scale profiles, not the raw-precision display contrast range.

After Live starts or the HDR setting changes, the status shows `HDR verifying` until at least three consecutive processed frames report the requested SDK HDR flag across a stable window of at least 0.5 seconds. A first-frame disagreement is recorded as a pending detail, not an immediate warning. Successful confirmation logs `Live HDR verified`, with `(recovered)` if an earlier flag disagreed or was unavailable. While frames continue arriving, an unresolved verification lasting five seconds produces one `Live HDR verification warning` and shows `HDR mismatch` or `HDR unverified`; unavailable flags are never assumed to mean off. Later recovery is logged, and a new disagreement after verification starts another verification window. Restarting/stopping Live resets this state. This uses the existing frame-level SDK readback without extra camera configuration or polling calls; it verifies Live flags only, not the HDR status of a hyperspectral acquisition, which must still be checked using `dataHDR`/`cubeHDR`.

Saved Tissue Scan field calibrations remain reusable across the preview-resolution upgrade when optics, ROI, rotation and binning are unchanged. Confirm unchanged optics when loading; a different objective or magnification still requires recalibration.

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

Helper direct-save (used by compatible `Run One Loop`/timelapse acquisitions) uses NumPy for blocked normalization when available. It retains the previous float64 `sample / ref` calculation, writes float32 BSQ, and writes zero when `abs(ref) <= 1e-12` or the reference is NaN. SDK acquisition, ROI alignment, wavelength order and ENVI metadata are unchanged. Reusable block buffers avoid copying entire SDK bands or loading a whole reference cube; the reference file is opened once per export. `_ref` also uses block reads/writes without converting its bytes. Incomplete references are rejected and temporary output cleanup remains enabled on failure. Without NumPy, the Python normalization fallback remains available.

After restarting the app, run a small scan with the same ROI/bands/reference and `_nrm` selected. In `hera_background_status.log`, check `Helper normalized export: NumPy float64 division -> float32 BSQ` and compare the `direct_save` value in `Helper performance timing`. This optimization targets normalization/saving, not the SDK acquisition or hypercube computing time.

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
