#!/bin/bash
# Rehearse a 25.10.x release in docker with the kiln's real settings.
#
#   docker/legacy/run.sh run  <ref> [sim|hw]   start the app on :8081
#   docker/legacy/run.sh test <ref>            run that ref's test suite
#
# <ref> is any git ref (v25.10.0, hotfix/25.10.1, ...). Its files are
# exported to docker/.run/<ref>/src, with the pi's config.py and profiles
# copied in from the backups (BACKUP_DIR, default ../kiln-backups).
#   sim  config.simulate = True: the app's own simulated oven
#   hw   config.simulate = False: RealOven against docker/fakehw
#        (relay state -> docker/.run/<ref>/data/fakehw-relay,
#         inject a fault by writing its name to .../data/fakehw-fault)
# DETACH=1 runs the container in the background as kiln-legacy.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image="${LEGACY_IMAGE:-kiln-controller-legacy:25.10}"
backup_dir="${BACKUP_DIR:-$repo/../kiln-backups}"

action="${1:?usage: run.sh run|test <ref> [sim|hw]}"
ref="${2:?usage: run.sh run|test <ref> [sim|hw]}"
mode="${3:-sim}"

snapshot="$(ls -d "$backup_dir"/pi/*/kiln-controller 2>/dev/null | sort | tail -1)"
if [ -z "$snapshot" ]; then
    echo "no pi backup under $backup_dir/pi; see docs/updating.md" >&2
    exit 1
fi

run="$repo/docker/.run/${ref//\//_}"
rm -rf "$run"
mkdir -p "$run/src" "$run/data"
git -C "$repo" archive "$ref" | tar -x -C "$run/src"

cp "$snapshot/config.py" "$run/src/config.py"
if [ -d "$backup_dir/kiln-data/profiles" ]; then
    cp "$backup_dir/kiln-data/profiles/"*.json "$run/src/storage/profiles/"
fi
if [ "$mode" = sim ]; then
    # the pi's sim_* values are leftovers; model this 3.2 kW kiln from 18 degC
    sed -i.bak -E \
        -e 's/^simulate *=.*/simulate = True/' \
        -e 's/^sim_t_env *=.*/sim_t_env = 18/' \
        -e 's/^sim_p_heat *=.*/sim_p_heat = 3200/' \
        "$run/src/config.py"
    rm -f "$run/src/config.py.bak"
fi

docker_args=(--rm -v "$run/src:/app" -v "$run/data:/run-data"
             -v "$repo/docker/fakehw:/opt/fakehw:ro")
for var in FAKEHW_WATTS FAKEHW_AMBIENT FAKEHW_SPEEDUP FAKEHW_FAULT; do
    if [ -n "${!var:-}" ]; then
        docker_args+=(-e "$var=${!var}")
    fi
done

case "$action" in
    run)
        echo "rehearsing $ref ($mode) from $run on http://localhost:8081"
        if [ "${DETACH:-0}" = 1 ]; then
            docker rm -f kiln-legacy >/dev/null 2>&1 || true
            docker run -d --name kiln-legacy -p 8081:8081 "${docker_args[@]}" "$image"
        else
            docker run -it -p 8081:8081 "${docker_args[@]}" "$image"
        fi
        ;;
    test)
        docker run "${docker_args[@]}" "$image" /opt/venv/bin/python -m pytest Test -q
        ;;
    *)
        echo "unknown action $action" >&2
        exit 1
        ;;
esac
