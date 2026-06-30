# Agent Notes: HERA App And NIS Z Bridge

This repo controls the HERA camera/stage app and the NIS-Elements Z-axis bridge. Work carefully, make small changes, and keep GitHub as the source of truth.

## Repo Rules

- Preserve user changes. Do not reset or revert the repo unless the user explicitly asks.
- Keep meaningful fixes committed/pushed to GitHub when the user asks to publish or when NIS-side files need deployment.
- `AppHeraTriggerPython0417.py` is only the launcher. Do not put app logic there.
- After every code change, tell the user exactly how to verify it: concrete app actions, expected results, and logs/files to inspect. If hardware testing was not possible locally, say that clearly.

## App Structure

Most logic lives under `hera_app/`.

```text
hera_app/
    app.py                        HeraTriggerApp init, state, logging, shutdown, main()
    controllers/
        hera.py                   Hera SDK / HeraAPI.dll wrapper
        tango.py                  Tango stage / Tango_DLL.dll wrapper
        nis_z.py                  NIS Z shared-folder bridge client
    mixins/
        ui_builder.py             UI construction and widget behavior
        device.py                 Hera/Tango connection, license, preflight, HDR
        acquisition.py            parameter apply, acquisition, callback worker, saving
        timelapse.py              cycle/site/timelapse worker
        live_view.py              live capture, rendering, zoom/pan/snapshot
        roi.py                    ROI selection, coordinate mapping, overlays
        flatfield.py              flatfield reference, normalization helpers
        hyperspectral_viewer.py   band display and spectrum panel
        export.py                 ENVI export, ROI crop, HyperLAB header patching
        stage.py                  stage motion and saved positions
        nis_z_mixin.py            NIS Z polling and controls
        theme.py                  light/dark theme
        utils.py                  safe Tk scheduling and async UI helpers
```

Open the relevant mixin/controller directly before editing. Use search if a method location is unclear.

## Core App Invariants

- The active UI is a three-pane layout: left status/exposure/ROI/XYZ/saved positions/NIS Z, center spectral/live/hyperspectral views, right acquisition/timelapse/export controls. Add controls to the correct pane and avoid duplicate ROI or saved-position controls.
- UI controls should be immediate where safe: buttons/checkbuttons focus and invoke on Enter, entries commit on Enter or changed FocusOut, and connected camera option variables auto-apply with debounce. Do not add generic Apply buttons for camera parameters or ROI fields.
- Keep camera parameter apply off the Tk main thread. Stop live capture in a worker when needed, apply settings, then schedule UI updates/live restart back on Tk.
- Background logging is always on. Keep the Tk/Python/thread exception hooks and the `Open Log` button wired to `hera_last_issues.log`; the full log is `hera_background_status.log`.
- Light/dark mode uses `theme_mode`, `theme_button_var`, `_configure_theme`, and `toggle_theme_mode`. New widgets should use `self.theme[...]` colors where practical.

## ROI And Saved Positions

- Live ROI is display-driven: two clicks on the rendered live image are inverse-mapped to Hera live-frame pixels and copied into ROI fields.
- Keep the user-selected export ROI separate from camera ROI readback. Hera can report ROI as read-only/full-frame even when the user selected a smaller region.
- ROI can be edited by corners, size fields, or area helper, but Hera ultimately receives rectangular `x, y, width, height`. Normalize corner edits back to rectangular ROI fields and update `roi_selection_active` / `selected_export_roi`.
- Saved positions include per-site ROI in `SavedPosition.roi`. Adding/updating/saving a site captures the active ROI; selecting a site restores it.
- Manual site runs, `Run First 2 Sites`, and timelapse use the saved ROI for each site, falling back to the timelapse-start ROI only when the site has no saved ROI.
- The saved positions list starts empty. Do not seed a default `Start` or `0,0` position.
- If NIS Z is unavailable, save `dummy_z_position` (`0.000`) so XY sites remain usable.

## Hyperspectral, Export, And HyperLAB

- Hyperspectral ROI is enforced after SDK acquisition when needed. The SDK may return a full-frame hypercube even for a selected ROI.
- For post-export ROI, export a temporary full-frame ENVI cube, scale the live-frame ROI into returned hypercube dimensions, crop binary/header on disk, remove temp files, and crop displayed bands so the viewer matches saved files.
- Do not crop a returned smaller hypercube with unscaled 3200x3200 live-frame coordinates.
- Export options must respect the right-side Export panel. `_raw` is always possible; `_ref` and `_nrm` require a loaded, compatible flatfield and are still checked at save time.
- ENVI exports must stay HyperLAB-friendly: keep `file type = ENVI Standard` and `data file = <matching data filename>` in headers after SDK export, ROI crop, or normalized export.
- Export naming uses `export_name_var` and `export_append_time_var`; saving notes use `saving_notes_var` and go into ENVI descriptions.
- HyperLAB opening uses `hyperlab_shortcut_var`, default `C:\Users\Public\Desktop\Nireos HyperLAB.lnk`. Resolve it to `HyperLAB.exe`, pass the selected/latest `.hdr`, and copy the path to clipboard. If `last_export_path` is empty, search output for the newest `_raw`, `_ref`, or `_nrm` `.hdr`.

## Flatfield

- Flatfield follows the Hera Acquisition App model: acquire a white diffuse/reference surface with `Acquire`, store it in `flatfield_hypercube_handle`, and use it until the user acquires a new flatfield, clears it, disconnects Hera, or closes the app.
- Compatible sample cubes display/export normalized data as `sample / flatfield`.
- Compatibility currently requires matching source size, displayed ROI coverage, band count, and data type.
- Hyperspectral View has `Normalized`, `Raw`, and `Flatfield` modes. `Normalized` shows the current sample divided by the compatible flatfield, `Raw` shows the native sample cube, and `Flatfield` shows the stored reference cube.
- Keep selected/cursor spectra tied to the active display mode, with a separate flatfield spectrum for comparison when showing a sample cube.
- Flatfield saving uses the same right-side `Export` button and shared output folder/name/stamp controls. Do not reintroduce a separate `Save Flatfield Ref` button. A pending flatfield acquisition saves as `_ref`.

## Live View

- Live cursor coordinates are display-only. The live preview is presentation-rotated with `live_display_rotation_degrees = 90` so Tango right/left motion is horizontal in the display.
- Inverse-map cursor, crosshair, ROI overlay, ROI clicks, and snapshots through the same live-frame orientation helpers. Do not reintroduce pixel-scale, invert-axis, or swap-axis controls unless the user explicitly asks.
- Live exposure helpers are display-only: `Auto Contrast`, `Gamma`, `Show Saturation`, `Cross`, and `Snapshot` must not alter camera exposure, gain, ROI, or acquisition data.
- `Live View HDR` is a live-preview aid, not a guaranteed hyperspectral HDR acquisition mode. Record SDK-reported raw/cube HDR flags in logs/export descriptions instead of assuming HDR cubes were saved.
- Keep the live cursor readout compact and stable in the left Status panel.

## Local-Only NIS And Design Files

NIS Z bridge files and UI design preview HTML files are private/local working materials and must not be tracked or pushed to GitHub. Keep local copies in ignored folders such as `NIS-Z-Bridge/` and `design_previews/`, or under the workspace `archive/`.

## Validation

- For Python-only changes, at minimum run `python -m py_compile` on touched Python files.
- For UI/hardware behavior, give the user a manual validation recipe with exact buttons/actions and expected state/log/output.
- For NIS bridge changes, include NIS PC startup/update steps when relevant.

## Commit Template

Use this template unless the user asks for a different format:

```text
<area>: <short imperative summary>

Why:
- <user-visible problem or goal>

What changed:
- <main code/UI behavior change>
- <important side effect or compatibility note>

Validation:
- <command or manual test performed>
- <hardware/app test the user should perform, if not run locally>
```
