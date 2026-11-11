<p align="center"><img src="PacingCalculator.png" width="96" alt=""></p>

# Pacing Calculator

A small Windows app for video editors, voice actors and scriptwriters. Enter any two of
**Word Count**, **Duration** and **Speech Pace (WPM)** and it solves for the third.

- Duration is entered in minutes and seconds; 60+ seconds roll over into minutes automatically
- A pace gauge shows where the WPM sits: Slow / Audiobook (<130), Conversational (130–160), Fast / Energetic (>160)
- **Workspace** tab: paste or type a script and see its word count and read time update live at your WPM
- Press **Enter** to calculate, **Esc** to close
- Updates itself from this repo's GitHub Releases (on launch, or via **Check for updates**)

## Download

Grab `PacingCalculator.exe` from the [latest release](../../releases/latest).
Windows may warn that the app is unsigned: right-click the file → **Properties** → tick **Unblock**.

## Publishing an update

1. Make your changes.
2. Bump the number in `version.py` (e.g. `1.0.0` → `1.0.1`).
3. Commit and push to `main`.

GitHub Actions builds the `.exe` on Windows and publishes release `v1.0.1`.
Installed copies see the update the next time they start (or via **Check for updates**).
Pushing a tag such as `v1.0.1` works too.

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
