# macOS Runtime

Expected executable path for auto-detection:
- `runtime/macos/iLANDc` (preferred)
- `runtime/macos/ilandc`

Included source snapshot:
- `runtime/macos/src/ilandc`

Notes:
- The source snapshot comes from `iland-model-main/src/ilandc` and is not a runnable runtime by itself.
- Place a native macOS `iLANDc` binary in this folder for the plugin to run simulations.
- If you build via repository script `build_mac_runtime.sh`, the script now copies the built binary here automatically.
- Release ZIP now also ships `runtime/macos/build_mac_runtime.sh` for convenience.
- The build script auto-detects Qt/qmake and asks permission before installing missing dependencies via Homebrew.
