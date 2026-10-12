#!/bin/bash
# Export the running XQuartz server's cookie, never the possibly stale default.
set -euo pipefail
server_line="$(ps -ww -axo command | awk '!found && $1 == "/opt/X11/bin/Xquartz" {print; found=1}')"
if [ -z "$server_line" ]; then
    echo "Open XQuartz on the Mac, then rerun bash docker/mac/mac-xauth.sh." >&2
    exit 1
fi
display_number="$(printf '%s\n' "$server_line" | awk '{for(i=2;i<=NF;i++) if($i ~ /^:[0-9]+$/) {sub(/^:/,"",$i);print $i;exit}}')"
server_auth="${server_line#* -auth }"
# XQuartz normally places -auth last. Also accept subsequent server options,
# retaining spaces within the authentication file's path.
server_auth="${server_auth%% -[[:alpha:]]*}"
if [ -z "$display_number" ] || [ "$server_auth" = "$server_line" ] || [ ! -r "$server_auth" ]; then
    echo "Cannot find the running XQuartz display and its readable -auth file." >&2
    exit 1
fi
cookies="$(/opt/X11/bin/xauth -f "$server_auth" nlist)"
if [ -z "$cookies" ]; then
    echo "The running XQuartz authentication file has no cookies. Restart XQuartz and retry." >&2
    exit 1
fi
umask 077
auth_dir="${GO2_MAC_XAUTH_DIR:-$HOME/Library/Caches/go2-fusion/xauth}"
mkdir -p "$auth_dir"
auth_file="$(mktemp "$auth_dir/Xauthority.XXXXXX")"
trap 'rm -f "$auth_file"' EXIT
# FamilyWild allows the container hostname to differ from the Mac hostname.
printf '%s\n' "$cookies" | sed 's/^..../ffff/' | /opt/X11/bin/xauth -f "$auth_file" nmerge -
mv "$auth_file" "$auth_dir/Xauthority"
printf 'host.docker.internal:%s\n' "$display_number" > "$auth_dir/display"
echo "XQuartz display :$display_number prepared. Credentials are stored outside the repository."
