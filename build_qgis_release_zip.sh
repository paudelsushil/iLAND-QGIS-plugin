#!/bin/bash

#==============================================================================
# Build QGIS Plugin Release ZIP
# Packages iland_qgis_plugin into a clean archive for
# Plugins -> Manage and Install Plugins -> Install from ZIP.
#==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_DIR="$SCRIPT_DIR/iland_qgis_plugin"
METADATA_FILE="$PLUGIN_DIR/metadata.txt"
OUTPUT_DIR="${1:-$SCRIPT_DIR/dist}"
ALLOW_MISSING_NATIVE_RUNTIME="${ALLOW_MISSING_NATIVE_RUNTIME:-0}"
ILANDC_PATH_OVERRIDE="${ILANDC_PATH:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   QGIS Plugin Release Packager${NC}"
echo -e "${BLUE}========================================${NC}"

if [ ! -d "$PLUGIN_DIR" ]; then
    echo -e "${RED}ERROR: Plugin directory not found: $PLUGIN_DIR${NC}"
    exit 1
fi

if [ ! -f "$METADATA_FILE" ]; then
    echo -e "${RED}ERROR: metadata.txt not found: $METADATA_FILE${NC}"
    exit 1
fi

VERSION="$(grep -E '^version=' "$METADATA_FILE" | head -n1 | cut -d'=' -f2- | tr -d '[:space:]')"
PLUGIN_NAME="$(grep -E '^name=' "$METADATA_FILE" | head -n1 | cut -d'=' -f2- | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"

if [ -z "$VERSION" ]; then
    echo -e "${RED}ERROR: Could not parse version from $METADATA_FILE${NC}"
    exit 1
fi

if [ -z "$PLUGIN_NAME" ]; then
    PLUGIN_NAME="iLAND Workbench"
fi

SANITIZED_NAME="$(echo "$PLUGIN_NAME" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/_/g; s/^_+|_+$//g')"
ZIP_NAME="${SANITIZED_NAME}_v${VERSION}_qgis_plugin.zip"

mkdir -p "$OUTPUT_DIR"
ZIP_PATH="$OUTPUT_DIR/$ZIP_NAME"

STAGING_DIR="$(mktemp -d)"
cleanup() {
    rm -rf "$STAGING_DIR"
}
trap cleanup EXIT

echo -e "${YELLOW}Staging plugin files...${NC}"
rsync -a \
    --exclude='.git' \
    --exclude='.DS_Store' \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='*.pyo' \
    --exclude='.pytest_cache' \
    --exclude='.mypy_cache' \
    --exclude='*.swp' \
    "$PLUGIN_DIR/" "$STAGING_DIR/iland_qgis_plugin/"

if [ ! -f "$STAGING_DIR/iland_qgis_plugin/__init__.py" ]; then
    echo -e "${RED}ERROR: __init__.py missing from staged plugin folder${NC}"
    exit 1
fi

if [ ! -f "$STAGING_DIR/iland_qgis_plugin/metadata.txt" ]; then
    echo -e "${RED}ERROR: metadata.txt missing from staged plugin folder${NC}"
    exit 1
fi

# Ship helper build script with plugin runtime payload for macOS users.
mkdir -p "$STAGING_DIR/iland_qgis_plugin/runtime/macos"
cp -f "$SCRIPT_DIR/build_mac_runtime.sh" "$STAGING_DIR/iland_qgis_plugin/runtime/macos/build_mac_runtime.sh"
chmod +x "$STAGING_DIR/iland_qgis_plugin/runtime/macos/build_mac_runtime.sh"

HOST_OS="linux"
case "$(uname -s)" in
    Darwin)
        HOST_OS="macos"
        ;;
    Linux)
        HOST_OS="linux"
        ;;
    MINGW*|MSYS*|CYGWIN*)
        HOST_OS="windows"
        ;;
esac

ensure_native_runtime_for_staging() {
    if [ "$HOST_OS" = "windows" ]; then
        return 0
    fi

    local runtime_dir="$STAGING_DIR/iland_qgis_plugin/runtime/$HOST_OS"
    local target_runtime="$runtime_dir/iLANDc"
    local source_runtime=""

    mkdir -p "$runtime_dir"

    # 1) Already bundled in repository plugin folder
    if [ -x "$PLUGIN_DIR/runtime/$HOST_OS/iLANDc" ]; then
        source_runtime="$PLUGIN_DIR/runtime/$HOST_OS/iLANDc"
    elif [ -x "$PLUGIN_DIR/runtime/$HOST_OS/ilandc" ]; then
        source_runtime="$PLUGIN_DIR/runtime/$HOST_OS/ilandc"
    fi

    # 2) User override path
    if [ -z "$source_runtime" ] && [ -n "$ILANDC_PATH_OVERRIDE" ] && [ -f "$ILANDC_PATH_OVERRIDE" ] && [ -x "$ILANDC_PATH_OVERRIDE" ]; then
        source_runtime="$ILANDC_PATH_OVERRIDE"
    fi

    # 3) Resolve from PATH
    if [ -z "$source_runtime" ]; then
        local which_ilandc=""
        which_ilandc="$(command -v iLANDc 2>/dev/null || true)"
        if [ -z "$which_ilandc" ]; then
            which_ilandc="$(command -v ilandc 2>/dev/null || true)"
        fi
        if [ -n "$which_ilandc" ] && [ -f "$which_ilandc" ] && [ -x "$which_ilandc" ]; then
            source_runtime="$which_ilandc"
        fi
    fi

    if [ -n "$source_runtime" ]; then
        cp -f "$source_runtime" "$target_runtime"
        chmod +x "$target_runtime"
        echo -e "${GREEN}✓ Staged native runtime for $HOST_OS: $source_runtime${NC}"
        return 0
    fi

    if [ "$ALLOW_MISSING_NATIVE_RUNTIME" = "1" ]; then
        echo -e "${YELLOW}WARNING: No native runtime found for $HOST_OS; creating plugin ZIP without bundled runtime (ALLOW_MISSING_NATIVE_RUNTIME=1).${NC}"
        return 0
    fi

    echo -e "${RED}ERROR: No native iLANDc runtime found for $HOST_OS.${NC}"
    echo -e "${YELLOW}Fix one of the following, then run this script again:${NC}"
    echo -e "  1) Build and publish runtime into plugin folder with: ./build_mac_runtime.sh"
    echo -e "  2) Provide explicit runtime path for packaging: ILANDC_PATH=/absolute/path/to/iLANDc ./build_qgis_release_zip.sh"
    echo -e "  3) If you intentionally want ZIP without runtime: ALLOW_MISSING_NATIVE_RUNTIME=1 ./build_qgis_release_zip.sh"
    exit 1
}

ensure_native_runtime_for_staging

rm -f "$ZIP_PATH"

echo -e "${YELLOW}Creating archive...${NC}"
(
    cd "$STAGING_DIR"
    zip -rq "$ZIP_PATH" "iland_qgis_plugin"
)

if [ ! -f "$ZIP_PATH" ]; then
    echo -e "${RED}ERROR: ZIP archive was not created${NC}"
    exit 1
fi

echo -e "${YELLOW}Validating archive contents...${NC}"
ZIP_FILE_LIST="$(unzip -Z1 "$ZIP_PATH")"

if ! printf '%s\n' "$ZIP_FILE_LIST" | grep -Fxq 'iland_qgis_plugin/metadata.txt'; then
    echo -e "${RED}ERROR: metadata.txt not found inside archive${NC}"
    exit 1
fi
if ! printf '%s\n' "$ZIP_FILE_LIST" | grep -Fxq 'iland_qgis_plugin/__init__.py'; then
    echo -e "${RED}ERROR: __init__.py not found inside archive${NC}"
    exit 1
fi

if [ "$HOST_OS" = "macos" ] || [ "$HOST_OS" = "linux" ]; then
    if [ "$ALLOW_MISSING_NATIVE_RUNTIME" != "1" ] && ! printf '%s\n' "$ZIP_FILE_LIST" | grep -Fxq "iland_qgis_plugin/runtime/$HOST_OS/iLANDc"; then
        echo -e "${RED}ERROR: Native runtime iland_qgis_plugin/runtime/$HOST_OS/iLANDc missing from archive${NC}"
        exit 1
    fi
fi

ZIP_SIZE="$(du -h "$ZIP_PATH" | awk '{print $1}')"

echo -e "${GREEN}✓ Release ZIP created successfully${NC}"
echo -e "  Name: ${BLUE}$ZIP_NAME${NC}"
echo -e "  Path: ${BLUE}$ZIP_PATH${NC}"
echo -e "  Size: ${BLUE}$ZIP_SIZE${NC}"
echo -e ""
echo -e "${GREEN}Install test in QGIS:${NC}"
echo -e "  Plugins -> Manage and Install Plugins -> Install from ZIP -> select this file"
