#!/usr/bin/env bash
set -euo pipefail
pm=${1:?PM required}
export CORIUM_ROOT
CORIUM_ROOT=$(mktemp -d)
export CORIUM_TEST_NO_DAEMONS=1 CORIUM_NETWORK_ID_OVERRIDE=default
trap 'rm -rf "$CORIUM_ROOT"' EXIT
case "$pm" in
  apt) expected=$(dpkg-query -W -f='${Package}\t${Version}' bash) ;;
  pacman) expected=$(pacman -Q bash | awk '{print $1 "\t" $2}') ;;
  dnf) expected=$(rpm -q bash --queryformat '%{NAME}\t%{VERSION}-%{RELEASE}') ;;
  portage) expected=$(equery -q list sys-apps/portage | sed -E 's|^(.*)/([^-]+)-(.+)$|\1/\2\t\3|') ;;
  xbps) expected=$(xbps-query -p pkgver bash | sed -E 's/^(.*)-([^-]+)$/\1\t\2/') ;;
  zypper) expected=$(rpm -q bash --queryformat '%{NAME}\t%{VERSION}-%{RELEASE}') ;;
  pkgsrc) expected=$(pkg_info -q -a | head -n 1 | sed -E 's/^(.*)-([^-]+)$/\1\t\2/') ;;
  pip) expected=$(python3 -m pip show pip | awk '/^Version:/{print "pip\t" $2}') ;;
  npm)
    fixture=$(mktemp -d)
    printf '{\n "name": "corium-ci-native",\n "version": "1.0.0"\n}\n' > "$fixture/package.json"
    npm install -g "$fixture"
    expected=$'corium-ci-native\t1.0.0'
    ;;
  *) exit 2 ;;
esac
[[ -n "$expected" ]] || { echo 'Native PM fixture inventory is empty'; exit 1; }
source ./corix_v108.sh
corix_manage_sync "$pm"
file="$EXTERNAL_PM_DB/$pm.db"
[[ -s "$file" ]]
awk -F '\t' -v expected="$expected" '($1 "\t" $2)==expected {found=1} END {exit !found}' "$file"
cp "$file" "${CORIUM_PM_REPORT:-/tmp}/external-${pm}.tsv"
# Import an external inventory twice and verify deterministic output.
cp "$file" "$CORIUM_ROOT/first.tsv"
corix_manage_sync "$pm"
cmp "$file" "$CORIUM_ROOT/first.tsv"
echo "PASS: native $pm inventory, version binding, idempotence"
