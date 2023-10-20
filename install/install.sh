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

    # Setting the hostname should be as close to the last step as possible. Anything after this step that
    # requires `sudo` will emit a warning: "sudo: unable to resolve host raspberrypi: Name or service not known".
    # Note that `sudo` will still work; it's just a "warning".
    setHostname

    new_config=$(cat $CONFIG)
    config_diff=$(diff <(echo "$old_config") <(echo "$new_config") || true)
    if [[ -f $RESTART_REQUIRED_FILE || -n "$config_diff" ]] ; then
        info "Restart is required!"
        info "Config diff:\n$config_diff"
        info "Restarting..."

        # Hide the "sudo: unable to resolve host raspberrypi: Name or service not known" output by
        # redirecting stderr. This it to avoid someone thinking something didn't work  (it's fine).
        # Related to changing the hostname via setHostname above.
        sudo shutdown -r now 2>/dev/null
    fi
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
    info "Setting up systemd services"

    sudo "$BASE_DIR/install/pifi_queue_service.sh"
    sudo "$BASE_DIR/install/pifi_server_service.sh"
    sudo "$BASE_DIR/install/pifi_websocket_server_service.sh"
    sudo chown root:root /etc/systemd/system/pifi_*.service
    sudo chmod 644 /etc/systemd/system/pifi_*.service
    sudo systemctl enable /etc/systemd/system/pifi_*.service
    sudo systemctl daemon-reload
    sudo systemctl restart $(ls /etc/systemd/system/pifi_*.service | cut -d'/' -f5)
}

setupSystemd(){
    info "\\nSetting up systemd..."

cat <<-EOF | sudo tee /etc/systemd/system/watchcat_motor.service >/dev/null
[Unit]
Description=watchcat_motor
After=network-online.target
Wants=network-online.target

[Service]
Environment=HOME=/root
ExecStart=$BASE_DIR/bin/motor
Restart=on-failure
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=WATCHCAT_MOTOR

[Install]
WantedBy=multi-user.target
EOF

cat <<-EOF | sudo tee /etc/systemd/system/watchcat_main.service >/dev/null
[Unit]
Description=watchcat_main
After=network-online.target
Wants=network-online.target
BindsTo=watchcat_motor.service
After=watchcat_motor.service

[Service]
Environment=HOME=/root
ExecStart=$BASE_DIR/bin/watchcat
Restart=on-failure
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=WATCHCAT_MAIN

[Install]
WantedBy=multi-user.target
EOF

    sudo chown root:root /etc/systemd/system/watchcat_*.service
    sudo chmod 644 /etc/systemd/system/watchcat_*.service
    sudo systemctl enable /etc/systemd/system/watchcat_*.service

    sudo systemctl daemon-reload
    sudo systemctl restart $(ls /etc/systemd/system/watchcat_*.service | cut -d'/' -f5)
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
