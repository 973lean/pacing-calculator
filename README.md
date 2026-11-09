<p align="center"><img src="PacingCalculator.png" width="96" alt=""></p>

# Pacing Calculator

A small Windows app for video editors, voice actors and scriptwriters. Enter any two of
**Word Count**, **Duration** and **Speech Pace (WPM)** and it solves for the third.

- Duration shows a live `Xm YYs` conversion
- A pace gauge shows where the WPM sits: Slow / Audiobook (<130), Conversational (130–160), Fast / Energetic (>160)
- Press **Enter** to calculate, **Esc** to close
- Updates itself from this repo's GitHub Releases (on launch, or via **Check for updates**)

## Download

Grab `PacingCalculator.exe` from the [latest release](../../releases/latest).
Windows may warn that the app is unsigned: right-click the file → **Properties** → tick **Unblock**.

## Publishing an update

1. Commit your changes.
2. Tag and push a new version:
   ```bash
   git tag v1.0.1
   git push origin v1.0.1
   ```
3. GitHub Actions builds the `.exe` on Windows and attaches it to a new release.
   Installed copies see the update the next time they start.

The version shown in the app comes from the tag; `version.py` is only the fallback for local builds.

## Build locally

Requires Python 3.10+ (standard library only) and PyInstaller:

```bash
pip install pyinstaller
build.bat
```

Or run from source with `python app.py`.

## Files

| File | Purpose |
| --- | --- |
| `app.py` | The app (tkinter UI and calculations) |
| `updater.py` | Checks GitHub Releases, downloads and swaps in the new `.exe` |
| `version.py` | Current version |
| `.github/workflows/release.yml` | Builds and publishes releases on version tags |
