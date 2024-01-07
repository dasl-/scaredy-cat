#!/usr/bin/env bash

set -euo pipefail -o errtrace

BASE_DIR="$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )")"

main(){
    trap 'fail $? $LINENO' ERR

    updateAndInstallPackages
    info "Done installing dependencies."
}

updateAndInstallPackages(){
    info "Updating and installing packages..."

    sudo apt update

    local apt_packages=(
        # raspberry pi camera library: https://github.com/raspberrypi/picamera2#installation
        python3-picamera2

        # enable viewing camera preview images over ssh
        # See: https://github.com/dasl-/scaredy-cat/blob/main/docs/viewing_live_camera_images_over_ssh.adoc
        python3-pyqt5
        python3-opengl

        python3-opencv

        # reduce jitter in controlling servos with GPIO
        python3-pigpio
    )

    # shellcheck disable=SC2048,SC2086
    sudo apt -y install ${apt_packages[*]}
    sudo apt -y full-upgrade

    sudo PIP_BREAK_SYSTEM_PACKAGES=1 python3 -m pip install --upgrade pytz
}

fail(){
    local exit_code=$1
    local line_no=$2
    local script_name
    script_name=$(basename "${BASH_SOURCE[0]}")
    die "Error in $script_name at line number: $line_no with exit code: $exit_code"
}

info(){
    echo -e "\x1b[32m$*\x1b[0m" # green stdout
}

warn(){
    echo -e "\x1b[33m$*\x1b[0m" # yellow stdout
}

die(){
    echo
    echo -e "\x1b[31m$*\x1b[0m" >&2 # red stderr
    exit 1
}

main "$@"
