#!/usr/bin/env bash

set -euo pipefail -o errtrace

BASE_DIR="$(dirname "$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )")"

usage() {
    local exit_code=$1
    echo "usage: $0"
    echo "    -h    display this help message"
    exit "$exit_code"
}

main(){
    trap 'fail $? $LINENO' ERR

    parseOpts "$@"
    setupSystemdServices

    info "Done installing."
}

parseOpts(){
    while getopts ":h" opt; do
        case $opt in
            h) usage 0 ;;
            \?)
                echo "Invalid option: -$OPTARG" >&2
                usage 1
                ;;
            :)
                echo "Option -$OPTARG requires an argument." >&2
                usage 1
                ;;
        esac
    done
}

setupSystemdServices(){
    info "Setting up systemd services..."

cat <<-EOF | sudo tee /etc/systemd/system/scaredycat_tick_controller.service >/dev/null
[Unit]
Description=scaredycat_tick_controller
After=network-online.target
Wants=network-online.target
BindsTo=pigpiod.service
After=pigpiod.service
BindsTo=scaredycat_main.service
Before=scaredycat_main.service

[Service]
Environment=HOME=/root
ExecStart=$BASE_DIR/bin/tick_controller
Restart=on-failure
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=SCAREDYCAT_TICK_CONTROLLER

[Install]
WantedBy=multi-user.target
EOF

cat <<-EOF | sudo tee /etc/systemd/system/scaredycat_main.service >/dev/null
[Unit]
Description=scaredycat_main
After=network-online.target
Wants=network-online.target
BindsTo=scaredycat_tick_controller.service
After=scaredycat_tick_controller.service

[Service]
Environment=HOME=/root
ExecStart=$BASE_DIR/bin/scaredycat
Restart=on-failure
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=SCAREDYCAT_MAIN

[Install]
WantedBy=multi-user.target
EOF

    sudo chown root:root /etc/systemd/system/scaredycat_*.service
    sudo chmod 644 /etc/systemd/system/scaredycat_*.service
    sudo systemctl enable /etc/systemd/system/scaredycat_*.service
    sudo systemctl enable pigpiod.service

    sudo systemctl daemon-reload
    sudo systemctl restart pigpiod.service
    sudo systemctl restart $(ls /etc/systemd/system/scaredycat_*.service | cut -d'/' -f5)
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
