import json
import unittest
from harness import run, call, account, group, STATE, SUB, POOL_ID, LEGACY_STATE

SOURCE = 'source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; '


class StateTests(unittest.TestCase):
    def test_new_state_owns_hub_ipam_pool(self):
        result = run(SOURCE + f'''
create_run abc123 {SUB} koreacentral >/dev/null &&
load_run .workshop-state/abc123.json &&
printf '%s %s\\n' "$RUN_SCHEMA" "$IPAM_POOL_ID"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(),
                         f"4 /subscriptions/{SUB}/resourceGroups/rg-lzbegin-hub-abc123/"
                         "providers/Microsoft.Network/networkManagers/avnm-lzbegin-abc123/"
                         "ipamPools/ipam-lzbegin-abc123")

    def test_old_shared_pool_state_is_cleanup_only(self):
        result = run(SOURCE + 'load_run state.json && require_run_schema_four',
                     files={"state.json": json.dumps(LEGACY_STATE)})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("schema 4", result.stderr)

    def test_state_exports_avnm_names_and_ids(self):
        result = run(SOURCE + r'''
load_run state.json &&
printf '%s\n' \
  "$AVNM" "$NETWORK_GROUP" "$CONNECTIVITY_CONFIG" \
  "$AVNM_ID" "$NETWORK_GROUP_ID" "$CONNECTIVITY_CONFIG_ID"
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        base = (
            f"/subscriptions/{SUB}/resourceGroups/rg-lzbegin-hub-demo123"
            "/providers/Microsoft.Network/networkManagers/avnm-lzbegin-demo123"
        )
        self.assertEqual(result.stdout.splitlines(), [
            "avnm-lzbegin-demo123",
            "ng-lzbegin-spokes-demo123",
            "cc-lzbegin-hub-spoke-demo123",
            base,
            base + "/networkGroups/ng-lzbegin-spokes-demo123",
            base + "/connectivityConfigurations/cc-lzbegin-hub-spoke-demo123",
        ])

    def test_schema_four_round_trip_records_and_exports_exact_pool(self):
        result = run(SOURCE + f'''
create_run abc123 {SUB.upper()} koreacentral >/dev/null &&
load_run .workshop-state/abc123.json &&
printf '%s\\n' "$IPAM_POOL_ID" &&
jq -c '{{schemaVersion,ipamPoolId}}' .workshop-state/abc123.json
''')
        self.assertEqual(result.returncode, 0, result.stderr)
        run_pool = POOL_ID.replace("demo123", "abc123")
        self.assertEqual(result.stdout.splitlines(), [
            run_pool, json.dumps({"schemaVersion": 4, "ipamPoolId": run_pool},
                                separators=(",", ":")),
        ])

    def test_schema_two_rejected_with_legacy_resume_instructions(self):
        old = dict(STATE, schemaVersion=2)
        result = run(SOURCE + "load_run state.json",
                     files={"state.json": json.dumps(old)})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("workshop-pre-ipam-8d4781f", result.stderr)

    def test_pool_id_must_be_exactly_derived_from_state_subscription(self):
        for pool in (None, "", POOL_ID.replace(SUB, "22222222-2222-2222-2222-222222222222"),
                     POOL_ID.replace("ipam-lzbegin-demo123", "another"),
                     POOL_ID.replace("rg-lzbegin-hub-demo123", "another"), 42):
            with self.subTest(pool=pool):
                data = dict(STATE)
                if pool is None:
                    del data["ipamPoolId"]
                else:
                    data["ipamPoolId"] = pool
                result = run(SOURCE + 'load_run state.json; '
                             '[[ ! -v IPAM_POOL_ID && ! -v SUBSCRIPTION_ID ]]',
                             files={"state.json": json.dumps(data)})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("Invalid or unreadable state file", result.stderr)

    def test_multiple_json_states_in_one_file_cannot_mix_runs_or_pool_ids(self):
        other = dict(STATE, runId="another", resourceGroups={
            zone: f"rg-lzbegin-{zone}-another" for zone in ("hub", "spokea", "spokeb")})
        result = run(SOURCE + 'load_run state.json; '
                     '[[ ! -v RUN_ID && ! -v IPAM_POOL_ID ]]',
                     files={"state.json": json.dumps(STATE) + "\n" + json.dumps(other)})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Invalid or unreadable state file", result.stderr)

    def test_schema_one_and_other_topologies_are_rejected(self):
        for change in (
            {"schemaVersion": 1},
            {"topology": "manual-hub-spoke"},
            {"topology": None},
            {"location": "westus2"},
        ):
            with self.subTest(change=change):
                data = dict(STATE, **change)
                result = run(SOURCE + "load_run state.json",
                             files={"state.json": json.dumps(data)})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid or unreadable state file", result.stderr)

    def test_failed_reload_clears_previous_state_and_zone_targets_without_exiting(self):
        variables = ("RUN_SCHEMA RUN_ID SUBSCRIPTION_ID LOCATION RG_HUB RG_SPOKEA RG_SPOKEB "
                     "AVNM NETWORK_GROUP CONNECTIVITY_CONFIG AVNM_ID NETWORK_GROUP_ID "
                     "CONNECTIVITY_CONFIG_ID IPAM_POOL_ID HUB_VNET_CIDR SPOKEA_VNET_CIDR "
                     "SPOKEB_VNET_CIDR HUB_SUBNET_CIDR SPOKEA_SUBNET_CIDR "
                     "SPOKEB_SUBNET_CIDR FIREWALL_SUBNET_CIDR RG SUBNET PREFIX VNET VM NSG")
        for path, files in (
            ("missing.json", {}),
            ("bad.json", {"bad.json": '{"schemaVersion":999}'}),
            ("bad.json", {"bad.json": "not JSON"}),
            ("", {}),
        ):
            with self.subTest(path=path, files=files):
                result = run(SOURCE + f'''
load_run state.json && export SPOKEA_VNET_CIDR=172.20.16.0/20 && zone_context spokea || exit 90
export IPAM_POOL_ID=stale HUB_VNET_CIDR=stale SPOKEA_VNET_CIDR=stale SPOKEB_VNET_CIDR=stale
export HUB_SUBNET_CIDR=stale SPOKEA_SUBNET_CIDR=stale SPOKEB_SUBNET_CIDR=stale FIREWALL_SUBNET_CIDR=stale
export STATE_FILE='{path}'
load_run "$STATE_FILE"
status=$?
printf 'LOAD_STATUS=%s\\n' "$status"
for name in {variables}; do
  [[ ! -v "$name" ]] || {{ printf 'STALE:%s\\n' "$name"; exit 91; }}
done
printf 'SHELL_ALIVE\\n'
load_run state.json && ! zone_context hub &&
  printf 'RESTORED:%s:%s\\n' "$RUN_ID" "$RG_HUB"
''', files=files)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertIn("LOAD_STATUS=1\nSHELL_ALIVE", result.stdout)
                self.assertIn("Invalid or unreadable state file", result.stderr)
                self.assertIn("RESTORED:demo123:rg-lzbegin-hub-demo123", result.stdout)

    def test_switching_state_drops_zone_targets_from_previous_run(self):
        result = run(SOURCE + f'''
load_run state.json && export SPOKEA_VNET_CIDR=172.20.16.0/20 && zone_context spokea &&
  export HUB_VNET_CIDR=stale SPOKEA_VNET_CIDR=stale SPOKEB_VNET_CIDR=stale &&
  export HUB_SUBNET_CIDR=stale SPOKEA_SUBNET_CIDR=stale &&
  export SPOKEB_SUBNET_CIDR=stale FIREWALL_SUBNET_CIDR=stale &&
  create_run abc123 {SUB} koreacentral >/dev/null &&
  load_run .workshop-state/abc123.json || exit 90
for name in HUB_VNET_CIDR SPOKEA_VNET_CIDR SPOKEB_VNET_CIDR HUB_SUBNET_CIDR \
  SPOKEA_SUBNET_CIDR SPOKEB_SUBNET_CIDR FIREWALL_SUBNET_CIDR RG SUBNET PREFIX VNET VM NSG; do
  [[ ! -v "$name" ]] || {{ printf 'STALE:%s\\n' "$name"; exit 91; }}
done
! zone_context spokeb && printf '%s %s %s\\n' "$RUN_ID" "$LOCATION" "$RG_SPOKEB"
''')
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertEqual(result.stdout, "abc123 koreacentral rg-lzbegin-spokeb-abc123\n")

    def new_group_calls(self, values=("false", "false", "false")):
        return [call(["group", "exists", "--name",
                      {"regex": f"rg-lzbegin-{zone}-[a-f0-9]{{12}}"}, "-o", "tsv"], value)
                for zone, value in zip(("hub", "spokea", "spokeb"), values)]

    def preflight_calls(self):
        return [call(["network", "manager", "list", "--subscription", SUB, "-o", "json"], []),
                call(["network", "vnet", "list", "--subscription", SUB, "-o", "json"], [])]

    def test_new_runs_use_distinct_ids_and_valid_recoverable_state(self):
        result = run(SOURCE + f'''
set -e
first=$(new_run {SUB} koreacentral)
second=$(new_run {SUB} koreacentral)
test "$first" != "$second"
load_run "$first"
printf '%s %s\\n' "$RUN_ID" "$RG_HUB"
load_run "$second"
printf '%s %s\\n' "$RUN_ID" "$RG_HUB"
''', [account(), *self.preflight_calls(), *self.new_group_calls(),
      account(), *self.preflight_calls(), *self.new_group_calls()])
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.splitlines()
        self.assertEqual(len(lines), 2)
        for line in lines:
            run_id, rg = line.split()
            self.assertRegex(run_id, r"^[a-f0-9]{12}$")
            self.assertEqual(rg, f"rg-lzbegin-hub-{run_id}")
        self.assertNotEqual(lines[0], lines[1])

    def test_new_run_rejects_any_existing_rg_before_creating_state(self):
        for index in range(3):
            with self.subTest(zone=index):
                result = run(SOURCE + f'new_run {SUB} koreacentral; '
                             'rc=$?; test ! -e .workshop-state || exit 9; exit "$rc"',
                             [account(), *self.preflight_calls(),
                              *self.new_group_calls(["false"] * index + ["true"])])
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertIn("already exists", result.stderr)

    def test_new_run_rejects_unknown_existence_and_cloud_errors(self):
        for value, code in (("unknown", 0), ("", 3)):
            with self.subTest(value=value, code=code):
                calls = self.new_group_calls([value])
                calls[0]["returncode"] = code
                result = run(SOURCE + f'new_run {SUB} koreacentral',
                             [account(), *self.preflight_calls(), *calls])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Cannot", result.stderr)

    def test_round_trip_and_private_permissions(self):
        result = run(SOURCE + f'create_run abc123 {SUB} koreacentral && '
                     'load_run .workshop-state/abc123.json && '
                     'printf "%s %s\\n" "$RUN_ID" "$RG_HUB" && '
                     'stat -c %a .workshop-state/abc123.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("abc123 rg-lzbegin-hub-abc123\n600", result.stdout)

    def test_invalid_id_creates_nothing(self):
        result = run(SOURCE + f'create_run ../other {SUB} koreacentral; '
                     'rc=$?; test ! -e .workshop-state || exit 9; exit "$rc"')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("runId", result.stderr)

    def test_create_run_rejects_other_valid_azure_location(self):
        result = run(SOURCE + f'create_run abc123 {SUB} westus2')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("koreacentral", result.stderr)

    def test_existing_state_is_not_overwritten(self):
        result = run(SOURCE + f'create_run abc123 {SUB} koreacentral && '
                     f'create_run abc123 {SUB} koreacentral')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exists", result.stderr)

    def test_rejects_tampered_rg_without_exiting_shell(self):
        data = json.loads(json.dumps(STATE))
        data["resourceGroups"]["hub"] = "production"
        result = run(SOURCE + 'load_run state.json; printf "alive:%s" "$?"',
                     files={"state.json": json.dumps(data)})
        self.assertEqual(result.stdout, "alive:1")
        self.assertIn("state", result.stderr)

    def test_rejects_unknown_schema_and_shell_injection(self):
        for field, value in (("schemaVersion", 5), ("runId", "$(touch escaped)"),
                             ("subscriptionId", "not-a-subscription")):
            with self.subTest(field=field):
                data = dict(STATE, **{field: value})
                result = run(SOURCE + 'load_run state.json', files={"state.json": json.dumps(data)})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("state", result.stderr)

    def test_subscription_mismatch_is_not_automatically_switched(self):
        result = run(SOURCE + 'load_run state.json && assert_subscription',
                     [call(["account", "show", "--query", "id", "-o", "tsv"], "other")])
        self.assertNotEqual(result.returncode, 0)

    def test_subscription_and_owned_group(self):
        result = run(SOURCE + 'load_run state.json && assert_subscription && assert_owned_rg "$RG_HUB"',
                     [account(), group("hub")])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_owner_prevents_use(self):
        response = group("hub")
        data = json.loads(response["stdout"])
        data["tags"]["runId"] = "other"
        response["stdout"] = json.dumps(data)
        result = run(SOURCE + 'load_run state.json && assert_owned_rg "$RG_HUB"', [response])
        self.assertNotEqual(result.returncode, 0)

    def test_foreign_group_rejected_before_azure(self):
        result = run(SOURCE + 'load_run state.json && assert_owned_rg production')
        self.assertNotEqual(result.returncode, 0)

    def test_zone_context_rejects_unknown_zone(self):
        result = run(SOURCE + 'load_run state.json && zone_context elsewhere')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("zone", result.stderr)
