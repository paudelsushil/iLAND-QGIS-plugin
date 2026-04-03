# iLAND Runtime Layout

This folder is used for bundled, OS-specific iLAND console runtimes.

Detected locations:
- `runtime/windows/iLANDc.exe`
- `runtime/macos/iLANDc` (or `runtime/macos/ilandc`)
- `runtime/linux/iLANDc` (or `runtime/linux/ilandc`)

For non-Windows platforms, a source snapshot from `iland-model-main/src/ilandc` is included under `runtime/<os>/src/ilandc`.
That snapshot is for reference and does not by itself create a runnable binary.

To run on macOS/Linux, place a native executable named `iLANDc` or `ilandc` in the corresponding OS folder.
