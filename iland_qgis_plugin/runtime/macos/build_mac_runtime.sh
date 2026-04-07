#!/bin/bash

#==============================================================================
# iLand Build Script for macOS
# This script builds the iLand console application (ilandc) from source
#==============================================================================

set -euo pipefail  # Exit on any error, undefined variable, or failed pipe segment

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}   iLand Build Script for macOS${NC}"
echo -e "${BLUE}========================================${NC}"

#==============================================================================
# STEP 0: Configuration - EDIT THESE PATHS IF NEEDED
#==============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Allow running this script from either repository root or plugin runtime folder.
if [ -d "$SCRIPT_DIR/iland_qgis_plugin" ]; then
    PLUGIN_DIR="$SCRIPT_DIR/iland_qgis_plugin"
elif [ -f "$SCRIPT_DIR/../../metadata.txt" ]; then
    PLUGIN_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
else
    echo -e "${RED}ERROR: Could not resolve plugin directory from script location: $SCRIPT_DIR${NC}"
    echo -e "${YELLOW}Run from repo root or from iland_qgis_plugin/runtime/macos.${NC}"
    exit 1
fi

PLUGIN_RUNTIME_DIR="$PLUGIN_DIR/runtime/macos"
PLUGIN_RUNTIME_TARGET="$PLUGIN_RUNTIME_DIR/iLANDc"
PLUGIN_RUNTIME_ALIAS="$PLUGIN_RUNTIME_DIR/ilandc"

AUTO_INSTALL_DEPS="${AUTO_INSTALL_DEPS:-0}"
FORCE_REBUILD="${FORCE_REBUILD:-0}"
PREFER_EXISTING_RUNTIME="${PREFER_EXISTING_RUNTIME:-1}"
QMAKE_DETECTED_VERSION=""

# Behavior flags:
#   AUTO_INSTALL_DEPS=1        -> non-interactive dependency installation prompts accepted
#   PREFER_EXISTING_RUNTIME=1  -> reuse already built native ilandc when possible (default)
#   FORCE_REBUILD=1            -> always rebuild from source, even if runtime already exists

ask_permission() {
    local prompt="$1"
    if [ "$AUTO_INSTALL_DEPS" = "1" ]; then
        return 0
    fi
    printf "%b" "${YELLOW}${prompt} [y/N]: ${NC}"
    read -r reply
    case "$reply" in
        [yY]|[yY][eE][sS]) return 0 ;;
        *) return 1 ;;
    esac
}

find_qmake() {
    local candidates=()

    if [ -n "${QMAKE_PATH:-}" ]; then
        candidates+=("$QMAKE_PATH")
    fi

    local qmake6_bin=""
    qmake6_bin="$(command -v qmake6 2>/dev/null || true)"
    if [ -n "$qmake6_bin" ]; then
        candidates+=("$qmake6_bin")
    fi

    local qmake_bin=""
    qmake_bin="$(command -v qmake 2>/dev/null || true)"
    if [ -n "$qmake_bin" ]; then
        candidates+=("$qmake_bin")
    fi

    candidates+=(
        "/opt/homebrew/opt/qt@6/bin/qmake"
        "/usr/local/opt/qt@6/bin/qmake"
        "/opt/homebrew/bin/qmake6"
        "/usr/local/bin/qmake6"
    )

    # Common online-installer layout (e.g. /Applications/Qt/6.x.x/macos/bin/qmake)
    local qt_app
    for qt_app in /Applications/Qt/*/macos/bin/qmake; do
        if [ -x "$qt_app" ]; then
            candidates+=("$qt_app")
        fi
    done

    local candidate
    local qt_version
    local qt_major
    local best_path=""
    local best_version=""
    local fallback_path=""
    local fallback_version=""

    for candidate in "${candidates[@]}"; do
        if [ -z "$candidate" ] || [ ! -x "$candidate" ]; then
            continue
        fi

        qt_version="$($candidate -query QT_VERSION 2>/dev/null || true)"
        if [ -z "$qt_version" ]; then
            continue
        fi

        if [ -z "$fallback_path" ]; then
            fallback_path="$candidate"
            fallback_version="$qt_version"
        fi

        qt_major="${qt_version%%.*}"
        if [[ "$qt_major" =~ ^[0-9]+$ ]] && [ "$qt_major" -ge 6 ]; then
            if [ -z "$best_version" ] || [ "$(printf '%s\n%s\n' "$best_version" "$qt_version" | sort -V | tail -n1)" = "$qt_version" ]; then
                best_path="$candidate"
                best_version="$qt_version"
            fi
        fi
    done

    if [ -n "$best_path" ]; then
        QMAKE_DETECTED_VERSION="$best_version"
        echo "$best_path"
        return 0
    fi

    if [ -n "$fallback_path" ]; then
        QMAKE_DETECTED_VERSION="$fallback_version"
        echo "$fallback_path"
        return 0
    fi

    return 1
}

# You can override ILAND_SOURCE_DIR when invoking the script:
#   ILAND_SOURCE_DIR=/path/to/iland-model ./build_mac_runtime.sh
ILAND_SOURCE_DIR="${ILAND_SOURCE_DIR:-$HOME/Documents/iland-model}"
BUILD_LOG="$ILAND_SOURCE_DIR/build.log"
HOST_ARCH="$(uname -m)"

# Detect Mac architecture
if [[ $(uname -m) == "arm64" ]]; then
    echo -e "${GREEN}Detected Apple Silicon Mac${NC}"
    HOMEBREW_PREFIX="/opt/homebrew"
else
    echo -e "${GREEN}Detected Intel Mac${NC}"
    HOMEBREW_PREFIX="/usr/local"
fi

is_native_runtime_candidate() {
    local candidate="$1"
    if [ ! -f "$candidate" ] || [ ! -x "$candidate" ]; then
        return 1
    fi

    if ! command -v file >/dev/null 2>&1; then
        return 0
    fi

    local file_info
    file_info="$(file "$candidate" 2>/dev/null || true)"
    if [ -z "$file_info" ]; then
        return 0
    fi

    case "$HOST_ARCH" in
        arm64|aarch64)
            [[ "$file_info" == *"arm64"* || "$file_info" == *"aarch64"* || "$file_info" == *"universal"* ]] || return 1
            ;;
        x86_64)
            [[ "$file_info" == *"x86_64"* || "$file_info" == *"universal"* ]] || return 1
            ;;
    esac

    return 0
}

find_existing_runtime() {
    local candidates=()
    local path_runtime=""

    candidates+=("$PLUGIN_RUNTIME_TARGET")
    candidates+=("$PLUGIN_RUNTIME_ALIAS")
    candidates+=("$ILAND_SOURCE_DIR/src/ilandc/ilandc")
    candidates+=("$HOME/Documents/iland-model/src/ilandc/ilandc")
    candidates+=("$HOME/Documents/iland-model-main/src/ilandc/ilandc")

    path_runtime="$(command -v ilandc 2>/dev/null || true)"
    if [ -n "$path_runtime" ]; then
        candidates+=("$path_runtime")
    fi
    path_runtime="$(command -v iLANDc 2>/dev/null || true)"
    if [ -n "$path_runtime" ]; then
        candidates+=("$path_runtime")
    fi

    local candidate
    for candidate in "${candidates[@]}"; do
        if [ -z "$candidate" ]; then
            continue
        fi
        if is_native_runtime_candidate "$candidate"; then
            echo "$candidate"
            return 0
        fi
    done

    return 1
}

publish_runtime() {
    local source_runtime="$1"
    if [ ! -f "$source_runtime" ]; then
        echo -e "${RED}ERROR: Runtime source not found: $source_runtime${NC}"
        return 1
    fi

    if ! is_native_runtime_candidate "$source_runtime"; then
        echo -e "${RED}ERROR: Runtime source is not a compatible native executable: $source_runtime${NC}"
        return 1
    fi

    rm -f "$PLUGIN_RUNTIME_TARGET" "$PLUGIN_RUNTIME_ALIAS"
    install -m 755 "$source_runtime" "$PLUGIN_RUNTIME_TARGET"

    if [ ! -x "$PLUGIN_RUNTIME_TARGET" ]; then
        echo -e "${RED}ERROR: Published runtime is not executable: $PLUGIN_RUNTIME_TARGET${NC}"
        return 1
    fi

    echo -e "${GREEN}✓ Runtime published to plugin:${NC}"
    echo -e "  ${BLUE}$PLUGIN_RUNTIME_TARGET${NC}"
    echo -e "  ${YELLOW}(alias skipped on macOS to avoid case-insensitive symlink collisions)${NC}"
    return 0
}

#==============================================================================
# STEP 1: Install Dependencies (Homebrew, Qt6, FreeImage)
#==============================================================================

echo -e "\n${YELLOW}STEP 1: Checking Dependencies...${NC}"

# Check if Homebrew is installed
if ! command -v brew &> /dev/null; then
    if ask_permission "Homebrew not found. Install Homebrew now?"; then
        echo -e "${YELLOW}Installing Homebrew...${NC}"
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    else
        echo -e "${RED}Homebrew is required for dependency installation. Aborting.${NC}"
        exit 1
    fi
else
    echo -e "${GREEN}✓ Homebrew is installed${NC}"
fi

# Ensure Qt6 / qmake is available
QMAKE_PATH="$(find_qmake || true)"
if [ -z "$QMAKE_PATH" ]; then
    if ask_permission "Qt6/qmake not found. Install qt@6 with Homebrew now?"; then
        echo -e "${YELLOW}Installing Qt6 (qt@6)...${NC}"
        brew install qt@6
        QMAKE_PATH="$(find_qmake || true)"
        if [ -z "$QMAKE_PATH" ]; then
            echo -e "${RED}ERROR: Qt6 installation completed but qmake was not found.${NC}"
            exit 1
        fi
    else
        echo -e "${RED}Qt6/qmake is required to build runtime. Aborting.${NC}"
        exit 1
    fi
fi

if [ -z "$QMAKE_DETECTED_VERSION" ]; then
    QMAKE_DETECTED_VERSION="$($QMAKE_PATH -query QT_VERSION 2>/dev/null || true)"
fi
QMAKE_MAJOR="${QMAKE_DETECTED_VERSION%%.*}"
if ! [[ "$QMAKE_MAJOR" =~ ^[0-9]+$ ]] || [ "$QMAKE_MAJOR" -lt 6 ]; then
    echo -e "${RED}ERROR: Detected qmake is Qt ${QMAKE_DETECTED_VERSION:-unknown}. Qt6 is required.${NC}"
    echo -e "${YELLOW}Set QMAKE_PATH explicitly or install qt@6 and retry.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Qt qmake detected: $QMAKE_PATH (Qt $QMAKE_DETECTED_VERSION)${NC}"

# Install FreeImage
if brew list freeimage &> /dev/null; then
    echo -e "${GREEN}✓ FreeImage is installed${NC}"
else
    if ask_permission "FreeImage not found. Install freeimage with Homebrew now?"; then
        echo -e "${YELLOW}Installing FreeImage...${NC}"
        brew install freeimage
    else
        echo -e "${RED}FreeImage is required to build runtime. Aborting.${NC}"
        exit 1
    fi
fi

#==============================================================================
# STEP 2: Set Up Environment
#==============================================================================

echo -e "\n${YELLOW}STEP 2: Setting up environment...${NC}"

# Set Qt paths from detected qmake (works for Homebrew and non-Homebrew Qt6 installs)
QT_BIN_DIR="$(dirname "$QMAKE_PATH")"
QT_INSTALL_PREFIX="$($QMAKE_PATH -query QT_INSTALL_PREFIX 2>/dev/null || true)"
if [ -z "$QT_INSTALL_PREFIX" ]; then
    QT_INSTALL_PREFIX="$(cd "$QT_BIN_DIR/.." && pwd)"
fi

export PATH="$QT_BIN_DIR:$PATH"
export LDFLAGS="-L$QT_INSTALL_PREFIX/lib -L$HOMEBREW_PREFIX/lib"
export CPPFLAGS="-I$QT_INSTALL_PREFIX/include -I$HOMEBREW_PREFIX/include"
export PKG_CONFIG_PATH="$QT_INSTALL_PREFIX/lib/pkgconfig"

# For FreeImage
export LIBRARY_PATH="$HOMEBREW_PREFIX/lib:${LIBRARY_PATH:-}"
export CPLUS_INCLUDE_PATH="$HOMEBREW_PREFIX/include:${CPLUS_INCLUDE_PATH:-}"

# Verify we're using the correct qmake (NOT Anaconda!)
echo -e "Using qmake: ${BLUE}$QMAKE_PATH${NC}"

if [[ "$QMAKE_PATH" == *"anaconda"* ]] || [[ "$QMAKE_PATH" == *"conda"* ]]; then
    echo -e "${RED}ERROR: Still using Anaconda's qmake!${NC}"
    echo -e "${RED}Please run: conda deactivate${NC}"
    echo -e "${RED}Then run this script again.${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Environment configured${NC}"

#==============================================================================
# STEP 3: Verify Source Directory
#==============================================================================

echo -e "\n${YELLOW}STEP 3: Verifying source directory...${NC}"

if [ ! -d "$ILAND_SOURCE_DIR" ]; then
    echo -e "${RED}ERROR: iLand source directory not found at $ILAND_SOURCE_DIR${NC}"
    echo -e "${YELLOW}Please clone the repository first:${NC}"
    echo -e "  git clone https://github.com/edfm-tum/iland-model.git $ILAND_SOURCE_DIR"
    exit 1
fi

echo -e "${GREEN}✓ Source directory found: $ILAND_SOURCE_DIR${NC}"

if [ ! -d "$PLUGIN_DIR" ]; then
    echo -e "${RED}ERROR: Plugin directory not found at $PLUGIN_DIR${NC}"
    echo -e "${YELLOW}Run this script from the iLAND-QGIS-plugin repository root.${NC}"
    exit 1
fi

mkdir -p "$PLUGIN_RUNTIME_DIR"
echo -e "${GREEN}✓ Plugin runtime directory ready: $PLUGIN_RUNTIME_DIR${NC}"

#==============================================================================
# STEP 3A: Reuse Existing Runtime (if available)
#==============================================================================

if [ "$FORCE_REBUILD" != "1" ] && [ "$PREFER_EXISTING_RUNTIME" = "1" ]; then
    echo -e "\n${YELLOW}STEP 3A: Checking for existing native runtime...${NC}"
    EXISTING_RUNTIME="$(find_existing_runtime || true)"
    if [ -n "$EXISTING_RUNTIME" ]; then
        echo -e "${GREEN}✓ Reusing existing runtime:${NC} ${BLUE}$EXISTING_RUNTIME${NC}"
        publish_runtime "$EXISTING_RUNTIME"
        echo -e "${GREEN}Runtime ready. Skipping rebuild (set FORCE_REBUILD=1 to force compile).${NC}"
        exit 0
    fi
    echo -e "${YELLOW}No reusable native runtime found; continuing with source build.${NC}"
fi

#==============================================================================
# STEP 4: Add C++17 to all .pro files (required for std::is_same_v)
#==============================================================================

echo -e "\n${YELLOW}STEP 4: Patching .pro files for C++17 support...${NC}"

# Function to add C++17 if not already present
add_cpp17_to_pro() {
    local pro_file="$1"
    if [ -f "$pro_file" ]; then
        if ! grep -q "CONFIG += c++17" "$pro_file" && ! grep -q "CONFIG+=c++17" "$pro_file"; then
            echo -e "  Adding C++17 to: ${BLUE}$(basename $pro_file)${NC}"
            # Add after the first line
            sed -i '' '1a\
CONFIG += c++17
' "$pro_file"
        else
            echo -e "  ${GREEN}✓${NC} C++17 already in: $(basename $pro_file)"
        fi
    fi
}

# Patch plugin .pro files
add_cpp17_to_pro "$ILAND_SOURCE_DIR/src/plugins/fire/fire.pro"
add_cpp17_to_pro "$ILAND_SOURCE_DIR/src/plugins/wind/wind.pro"
add_cpp17_to_pro "$ILAND_SOURCE_DIR/src/plugins/barkbeetle/barkbeetle.pro"

# Patch main ilandc.pro
add_cpp17_to_pro "$ILAND_SOURCE_DIR/src/ilandc/ilandc.pro"

echo -e "${GREEN}✓ .pro files patched${NC}"

#==============================================================================
# STEP 5: Patch ilandc.pro for macOS FreeImage paths
#==============================================================================

echo -e "\n${YELLOW}STEP 5: Patching ilandc.pro for macOS FreeImage...${NC}"

ILANDC_PRO="$ILAND_SOURCE_DIR/src/ilandc/ilandc.pro"

# Check if macOS block already exists
if ! grep -q "macx {" "$ILANDC_PRO"; then
    echo -e "  Adding macOS FreeImage configuration..."
    cat >> "$ILANDC_PRO" << EOF

# macOS FreeImage configuration (added by build script)
macx {
    INCLUDEPATH += $HOMEBREW_PREFIX/include
    LIBS += -L$HOMEBREW_PREFIX/lib -lfreeimage
}
EOF
    echo -e "${GREEN}✓ macOS configuration added${NC}"
else
    echo -e "${GREEN}✓ macOS configuration already exists${NC}"
fi

#==============================================================================
# STEP 6: Clean Previous Builds
#==============================================================================

echo -e "\n${YELLOW}STEP 6: Cleaning previous builds...${NC}"

cd "$ILAND_SOURCE_DIR/src/plugins"
rm -f Makefile .qmake.stash
rm -f fire/Makefile fire/.qmake.stash
rm -f wind/Makefile wind/.qmake.stash
rm -f barkbeetle/Makefile barkbeetle/.qmake.stash
rm -f fire/*.o wind/*.o barkbeetle/*.o
rm -f fire/*.a wind/*.a barkbeetle/*.a
rm -f *.a

cd "$ILAND_SOURCE_DIR/src/ilandc"
rm -f Makefile .qmake.stash
rm -f *.o
rm -f ilandc

echo -e "${GREEN}✓ Cleaned${NC}"

#==============================================================================
# STEP 7: Build Plugins
#==============================================================================

echo -e "\n${YELLOW}STEP 7: Building plugins...${NC}"
echo -e "  (This may take a few minutes)"

cd "$ILAND_SOURCE_DIR/src/plugins"

echo -e "  Running qmake for plugins..."
"$QMAKE_PATH" plugins.pro CONFIG+=sdk_no_version_check 2>&1 | tee -a "$BUILD_LOG"

echo -e "  Compiling plugins..."
make -j$(sysctl -n hw.ncpu) 2>&1 | tee -a "$BUILD_LOG"

# Verify plugins were built
if [ -f "libiland_fire.a" ] && [ -f "libiland_wind.a" ] && [ -f "libiland_barkbeetle.a" ]; then
    echo -e "${GREEN}✓ Plugins built successfully${NC}"
    ls -la libiland_*.a
else
    echo -e "${RED}ERROR: Plugin build failed. Check $BUILD_LOG${NC}"
    echo -e "${YELLOW}Expected plugin artifacts in: $ILAND_SOURCE_DIR/src/plugins${NC}"
    ls -la "$ILAND_SOURCE_DIR/src/plugins"/*.a 2>/dev/null || true
    exit 1
fi

#==============================================================================
# STEP 8: Build iLand Console (ilandc)
#==============================================================================

echo -e "\n${YELLOW}STEP 8: Building ilandc...${NC}"
echo -e "  (This may take several minutes)"

cd "$ILAND_SOURCE_DIR/src/ilandc"

echo -e "  Running qmake for ilandc..."
"$QMAKE_PATH" ilandc.pro CONFIG+=sdk_no_version_check 2>&1 | tee -a "$BUILD_LOG"

echo -e "  Compiling ilandc..."
make -j$(sysctl -n hw.ncpu) 2>&1 | tee -a "$BUILD_LOG"

#==============================================================================
# STEP 9: Verify Build
#==============================================================================

echo -e "\n${YELLOW}STEP 9: Verifying build...${NC}"

if [ -f "$ILAND_SOURCE_DIR/src/ilandc/ilandc" ]; then
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}   BUILD SUCCESSFUL!${NC}"
    echo -e "${GREEN}========================================${NC}"
    echo -e ""
    echo -e "Binary location:"
    echo -e "  ${BLUE}$ILAND_SOURCE_DIR/src/ilandc/ilandc${NC}"
    echo -e ""
    echo -e "File info:"
    ls -lh "$ILAND_SOURCE_DIR/src/ilandc/ilandc"
    file "$ILAND_SOURCE_DIR/src/ilandc/ilandc"
    echo -e ""
    echo -e "Testing binary..."
    "$ILAND_SOURCE_DIR/src/ilandc/ilandc" 2>&1 | head -20

    echo -e "\n${YELLOW}STEP 10: Publishing runtime for plugin auto-detection...${NC}"
    publish_runtime "$ILAND_SOURCE_DIR/src/ilandc/ilandc"
    echo -e "${GREEN}✓ Plugin runtime is executable and ready${NC}"

    echo -e ""
    echo -e "${GREEN}You can now run iLand with:${NC}"
    echo -e "  ${BLUE}$ILAND_SOURCE_DIR/src/ilandc/ilandc <project.xml> <years>${NC}"
    echo -e ""
    echo -e "${GREEN}Plugin auto-detect location:${NC}"
    echo -e "  ${BLUE}$PLUGIN_RUNTIME_TARGET${NC}"
    echo -e ""
    echo -e "${YELLOW}Optional: Add to PATH by running:${NC}"
    echo -e "  ${BLUE}sudo ln -s $ILAND_SOURCE_DIR/src/ilandc/ilandc /usr/local/bin/ilandc${NC}"
else
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}   BUILD FAILED${NC}"
    echo -e "${RED}========================================${NC}"
    echo -e ""
    echo -e "Check the build log for errors:"
    echo -e "  ${BLUE}$BUILD_LOG${NC}"
    echo -e ""
    echo -e "Common issues:"
    echo -e "  1. Missing FreeImage: brew install freeimage"
    echo -e "  2. Wrong Qt version: Ensure Homebrew Qt6 is in PATH"
    echo -e "  3. Anaconda interference: Run 'conda deactivate' first"
    exit 1
fi

echo -e "\n${BLUE}Build log saved to: $BUILD_LOG${NC}"