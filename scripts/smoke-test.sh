#!/usr/bin/env bash
# End-to-end check of a running deployment through its public entry point:
# health, the exact version being served, and the full user journey.
#
#   scripts/smoke-test.sh [expected-git-sha]
source "$(dirname "$0")/lib.sh"
need curl python3
EXPECTED_SHA="${1:-}"
ensure_base_url

log "smoke test against $BASE_URL"
curl -fsS "$BASE_URL/healthz" >/dev/null && ok "liveness /healthz"
curl -fsS "$BASE_URL/readyz" | grep -q '"database":"up"' && ok "readiness /readyz (database up)"

version_json="$(curl -fsS "$BASE_URL/version")"
echo "  version: $version_json"
if [[ -n "$EXPECTED_SHA" ]]; then
  served="$(python3 -c 'import json,sys;print(json.load(sys.stdin)["git_sha"])' <<<"$version_json")"
  [[ "$served" == "$EXPECTED_SHA" ]] && ok "serving expected commit $EXPECTED_SHA" \
    || fail "serving $served, expected $EXPECTED_SHA"
fi

curl -fsS "$BASE_URL/" | grep -q "<title>Expenses</title>" && ok "web UI served"

# User journey: record expenses, check the totals are *correct* (not just 200), clean up.
# A far-past date isolates this run's rows from any existing data.
day="1999-01-0$(( RANDOM % 9 + 1 ))"
cat_a="smoke-food-$RANDOM"; cat_b="smoke-rent-$RANDOM"
post() { curl -fsS -X POST "$BASE_URL/api/expenses" -H 'Content-Type: application/json' -d "$1"; }
id1="$(post "{\"amount\":\"10.25\",\"category\":\"$cat_a\",\"spent_on\":\"$day\"}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
id2="$(post "{\"amount\":\"4.75\",\"category\":\"$cat_a\",\"spent_on\":\"$day\"}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
id3="$(post "{\"amount\":\"100\",\"category\":\"$cat_b\",\"spent_on\":\"$day\"}" | python3 -c 'import json,sys;print(json.load(sys.stdin)["id"])')"
ok "recorded 3 expenses (#$id1 #$id2 #$id3) on $day"
summary="$(curl -fsS "$BASE_URL/api/summary?start=$day&end=$day")"
python3 - "$summary" "$cat_a" "$cat_b" <<'PY' && ok "summary totals correct (115.00 = 15.00 + 100.00)" || fail "wrong summary: $summary"
import json, sys
s, a, b = json.loads(sys.argv[1]), sys.argv[2], sys.argv[3]
by = {c["category"]: c for c in s["by_category"]}
assert s["total"] == "115.00", s
assert by[a]["total"] == "15.00" and by[a]["count"] == 2, by
assert by[b]["total"] == "100.00", by
PY
n="$(curl -fsS "$BASE_URL/api/expenses?start=$day&end=$day&category=$cat_a" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')"
[[ "$n" == "2" ]] && ok "date + category filter returns 2" || fail "filter returned $n"
http() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
c="$(http -X POST "$BASE_URL/api/expenses" -H 'Content-Type: application/json' -d "{\"amount\":\"0\",\"category\":\"x\",\"spent_on\":\"$day\"}")"
[[ "$c" == "422" ]] && ok "zero amount rejected (422)" || fail "validation returned $c"
for i in $id1 $id2 $id3; do c="$(http -X DELETE "$BASE_URL/api/expenses/$i")"; [[ "$c" == "204" ]] || fail "delete #$i returned $c"; done
ok "cleaned up"
[[ "$(curl -fsS "$BASE_URL/api/summary?start=$day&end=$day")" == *'"total":"0.00"'* ]] && ok "summary back to 0.00 after delete"

curl -fsS "$BASE_URL/metrics" | grep -q 'expenses_operations_total{operation="create",outcome="success"}' \
  && ok "metrics exported"
log "smoke test passed"
