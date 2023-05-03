#!/usr/bin/env bash

set -euo pipefail -o errtrace

BASE_DIR="$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )")"

SWAP_FILE='/etc/dphys-swapfile'
TEMPORARILY_COMMENTED_OUT_STR='temporarily_commented_out_by_watchcat'
TEMPORARILY_ADDED_STR='temporarily_added_by_watchcat'

main(){
    trap 'fail $? $LINENO' ERR

    updateAndInstallPackages
    installDlib
}

updateAndInstallPackages(){
    info "Updating and installing packages..."

    sudo apt update


    local apt_packages=(
        # Dependencies for https://github.com/ageitgey/face_recognition
        # See face_recognition raspberry pi installation steps, although we made a handful of modifications:
        # https://gist.github.com/ageitgey/1ac8dbe8572f3f533df6269dab35df65
        build-essential
        cmake
        gfortran
        git
        wget
        curl
        graphicsmagick
        libgraphicsmagick1-dev
        # Note, the referenced instructions originally said to install libatlas-dev, which I changed to libatlas-base-dev.
        # Package appears to have been renamed.
        libatlas-base-dev
        libavcodec-dev
        libavformat-dev
        libboost-all-dev
        libgtk2.0-dev
        libjpeg-dev
        liblapack-dev
        libswscale-dev
        pkg-config
        python3-dev
        python3-numpy
        python3-pip
        zip

        # raspberry pi camera library: https://github.com/raspberrypi/picamera2#installation
        python3-picamera2
        # enable viewing camera preview images over ssh
        # See: https://github.com/dasl-/watchcat/blob/main/docs/viewing_live_camera_images_over_ssh.adoc
        python3-pyqt5
        python3-opengl
    )
    sudo apt -y install "${apt_packages[*]}"
    sudo apt -y full-upgrade

    # face_recognition: https://github.com/ageitgey/face_recognition
    sudo python3 -m pip install --upgrade face_recognition

}

removeTemporarilyAddedLinesFromSwapFile(){
    local backup_version
    backup_version=$1
    # Remove temporarily added lines and create a backup of the original swap file
    sed -i.watchcat_bak"$backup_version" "/$TEMPORARILY_ADDED_STR/d" $SWAP_FILE
}


# See face_recognition raspberry pi installation steps, although we made a handful of modifications:
# https://github.com/ageitgey/face_recognition
# https://gist.github.com/ageitgey/1ac8dbe8572f3f533df6269dab35df65
temporarilySetSwapTo(){
    local new_swap_size
    new_swap_size=$1

    info "Temporarily setting swap size to: $new_swap_size ..."

    removeTemporarilyAddedLinesFromSwapFile 1

    # comment out existing CONF_SWAPSIZE lines
    sudo sed $SWAP_FILE -i -e "s/^\(CONF_SWAPSIZE=.*\)/#\1 $TEMPORARILY_COMMENTED_OUT_STR/"

    # set temporary new swap size
    echo "CONF_SWAPSIZE=$new_swap_size # $TEMPORARILY_ADDED_STR" | sudo tee -a $SWAP_FILE >/dev/null

    sudo /etc/init.d/dphys-swapfile restart
}

restoreOldSwapSettings(){
    info "Restoring old swap settings ..."
    removeTemporarilyAddedLinesFromSwapFile 2

    # uncomment temporarily commented out lines
    sudo sed $SWAP_FILE -i -e "s/^\#(CONF_SWAPSIZE=.*) $TEMPORARILY_COMMENTED_OUT_STR/\1/"

    sudo /etc/init.d/dphys-swapfile restart
}

installDlib(){
    info "Installing dlib ..."

    # Temporarily enable a larger swap file size (so the dlib compile won't fail due to limited memory):
    # See: https://gist.github.com/ageitgey/1ac8dbe8572f3f533df6269dab35df65
    temporarilySetSwapTo 1024

    local clone_dir
    clone_dir="$BASE_DIR/../dlib"
    if [ -d "$clone_dir" ]; then
        info "Pulling repo in $clone_dir ..."
        pushd "$clone_dir"
        git pull
    else
        info "Cloning repo into $clone_dir ..."
        # the instructions said to clone a different branch ( git clone -b 'v19.6' --single-branch https://github.com/davisking/dlib.git dlib/ ).
        # I had to clone a more recent version to solve "AttributeError: 'Thread' object has no attribute 'isAlive'" encoubntered during the
        # subsequent installation step (see: https://github.com/jupyter-vim/jupyter-vim/issues/51 )
        git clone -b 'v19.24' --single-branch https://github.com/davisking/dlib.git "$clone_dir"
        pushd "$clone_dir"
    fi

    info "Compiling dlib. This may take ~40 minutes on a raspberry pi 4 ..."
    sudo python3 setup.py install --compiler-flags "-mfpu=neon"

    popd
    restoreOldSwapSettings
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
