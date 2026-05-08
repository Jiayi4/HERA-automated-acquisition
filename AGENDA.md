# Agenda

## Immediate — NIS PC (do this before the next GET Z test)

These steps are needed because a broken macro run left the `current_getz` slot stuck with an incomplete response (`OK 56` instead of `OK 56.000000`).

### Step 1 — Clear the stuck slot

Open PowerShell on the NIS PC and run:

```powershell
Remove-Item -LiteralPath "E:\Jiayi\NISZBridge\commands\current_getz.txt" -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "E:\Jiayi\NISZBridge\state\current_getz.id" -ErrorAction SilentlyContinue
Remove-Item -LiteralPath "E:\Jiayi\NISZBridge\responses\current_getz_response.txt" -ErrorAction SilentlyContinue
```

### Step 2 — Pull the corrected macro

```powershell
cd E:\Jiayi\NISZBridge
Invoke-WebRequest `
  -Uri "https://raw.githubusercontent.com/LinaGross/hera-trigger-app/main/NIS-Z-Bridge/nis_z_local_text_bridge_watcher.mac" `
  -OutFile ".\nis_z_local_text_bridge_watcher.mac"
```

The current GitHub version (commit `d3fd5b0`) has `strlen(response) * 2` in every WriteFile response call, which is required for NIS-Elements to write the full decimal value.

### Step 3 — Reload the macro in NIS-Elements

Close and reopen `nis_z_local_text_bridge_watcher.mac` in the NIS-Elements macro editor.

### Verify

Press GET Z on HERA, then check:

```powershell
Get-Content E:\Jiayi\NISZBridge\nis_z_sync.log -Tail 20
```

You should see:

```
Forwarded shared command ... into slot current_getz
Published local response ... -> ...
```

The response file should contain `OK 7234.123456` (full decimal value).

---

## One-time cleanup — stale NAS command files

Previous GET Z timeouts left hundreds of orphan command files in the shared NAS `commands\` folder. They are ignored by the sync script (older than 180 s) but clutter the directory.

Run once on the NIS PC:

```powershell
$root = "\\sti-nas1.rcp.epfl.ch\bios\bios-raw\backups\visible\cell\Jiayi_bios-raw\Z control shared"
$cutoff = (Get-Date).AddSeconds(-180)
Get-ChildItem -LiteralPath "$root\commands" -Filter "*.txt" |
  Where-Object { $_.LastWriteTime -lt $cutoff } |
  Remove-Item -Force
```

The HERA app (commit `1cf8139`) now deletes the command file on timeout, so this will not accumulate again.

---

## Near-term — verify GET Z end-to-end

After completing the steps above:

1. Start the sync script on the NIS PC.
2. Start the hotkey runner on the NIS PC.
3. Press GET Z on HERA.
4. Confirm the Z value appears with a full decimal (e.g., `5726.40 um`).
5. Press GET Z a second time to confirm it works on repeat (processed-slot collision was also fixed in commit `1cf8139`).

---

## Future — Z integration

- Display Z next to XY everywhere XY is shown in the HERA UI.
- Support arbitrary Z moves (user-typed target, not only fixed increments).
- Include X, Y, and Z in acquisition loops (move to XYZ, acquire, repeat).
- After each hyperspectral image, return the stage to the correct XYZ position.
