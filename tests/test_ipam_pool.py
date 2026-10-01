import json
import re
import unittest

from harness import LEGACY_POOL_ID, POOL_ID as RUN_POOL_ID, ROOT, SUB, call, group, run

POOL_ID = LEGACY_POOL_ID

SOURCE = 'source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; source "$WORKSHOP_ROOT/scripts/workshop-ipam.sh"; '
REST = ["rest", "--method", "get", "--url", POOL_ID + "?api-version=2024-05-01",
        "--subscription", SUB, "-o", "json"]
MANAGER_ID = POOL_ID.split("/ipamPools/")[0]
MANAGER_REST = ["rest", "--method", "get", "--url", MANAGER_ID + "?api-version=2024-05-01",
                "--subscription", SUB, "-o", "json"]
READY = {"id": POOL_ID, "location": "koreacentral",
         "properties": {"addressPrefixes": ["172.20.0.0/14"],
                        "provisioningState": "Succeeded"}}
MANAGER_READY = {"id": MANAGER_ID, "location": "koreacentral",
                 "properties": {"networkManagerScopes": {
                     "managementGroups": [], "subscriptions": [f"/subscriptions/{SUB}"]},
                     "networkManagerScopeAccesses": [],
                     "provisioningState": "Succeeded"}}


class SharedPoolTests(unittest.TestCase):
    def test_run_pool_and_parent_must_match_state(self):
        manager_id = RUN_POOL_ID.split("/ipamPools/")[0]
        pool_rest = ["rest", "--method", "get", "--url", RUN_POOL_ID + "?api-version=2024-05-01",
                     "--subscription", SUB, "-o", "json"]
        manager_rest = ["rest", "--method", "get", "--url", manager_id + "?api-version=2024-05-01",
                        "--subscription", SUB, "-o", "json"]
        pool = {"id": RUN_POOL_ID, "location": "koreacentral",
                "properties": {"addressPrefixes": ["172.20.0.0/14"],
                               "provisioningState": "Succeeded"}}
        manager = {"id": manager_id, "location": "koreacentral",
                   "properties": {"provisioningState": "Succeeded",
                                  "networkManagerScopes": {"subscriptions": [f"/subscriptions/{SUB}"],
                                                           "managementGroups": []},
                                  "networkManagerScopeAccesses":
                                      ["Connectivity", "SecurityAdmin", "Routing"]}}
        script = SOURCE + 'load_run state.json && assert_run_ipam_pool'
        self.assertEqual(run(script, [group("hub"), call(pool_rest, pool),
                                      call(manager_rest, manager)]).returncode, 0)
        for wrong_pool in (dict(pool, id="foreign"), dict(pool, properties={
            "addressPrefixes": ["172.20.0.0/15"], "provisioningState": "Succeeded"}),
                           dict(pool, properties={
                               "addressPrefixes": ["172.20.0.0/14"], "provisioningState": "Updating"})):
            with self.subTest(pool=wrong_pool):
                self.assertNotEqual(run(script, [group("hub"), call(pool_rest, wrong_pool)]).returncode, 0)
        wrong_manager = dict(manager, properties=dict(manager["properties"],
                              networkManagerScopeAccesses=["Connectivity"]))
        self.assertNotEqual(run(script, [group("hub"), call(pool_rest, pool),
                                         call(manager_rest, wrong_manager)]).returncode, 0)
        self.assertNotEqual(run(script, [group("hub"),
                                         call(pool_rest, code=3, stderr="Forbidden")]).returncode, 0)

    def test_module_two_creates_only_missing_run_pool(self):
        from harness import POOL_ID as run_pool
        doc = (ROOT / "docs/02-network-foundation.md").read_text()
        block = re.search(r"<!-- exec:run-ipam-pool -->\s*```bash\n(.*?)\n```", doc, re.S).group(1)
        manager_id = run_pool.split("/ipamPools/")[0]
        hub = "rg-lzbegin-hub-demo123"
        manager = {"id": manager_id, "location": "koreacentral", "provisioningState": "Succeeded",
                   "networkManagerScopes": {"subscriptions": [f"/subscriptions/{SUB}"]},
                   "networkManagerScopeAccesses": ["Connectivity", "SecurityAdmin", "Routing"]}
        parent = {"id": manager_id, "location": "koreacentral", "properties": {
            "provisioningState": "Succeeded", "networkManagerScopes": {
                "subscriptions": [f"/subscriptions/{SUB}"], "managementGroups": []},
            "networkManagerScopeAccesses": manager["networkManagerScopeAccesses"]}}
        pool = {"id": run_pool, "location": "koreacentral", "properties": {
            "addressPrefixes": ["172.20.0.0/14"], "provisioningState": "Succeeded"}}
        listing = ["rest", "--method", "get", "--url",
                   manager_id + "/ipamPools?api-version=2024-05-01",
                   "--subscription", SUB, "-o", "json"]
        manager_show = ["network", "manager", "show", "--name", "avnm-lzbegin-demo123",
                        "-g", hub, "--subscription", SUB, "-o", "json"]
        pool_read = ["rest", "--method", "get", "--url",
                     run_pool + "?api-version=2024-05-01", "--subscription", SUB, "-o", "json"]
        parent_read = ["rest", "--method", "get", "--url",
                       manager_id + "?api-version=2024-05-01",
                       "--subscription", SUB, "-o", "json"]
        prefix = [group("hub"), call(manager_show, manager)]
        checks = [group("hub"), call(pool_read, pool), call(parent_read, parent)]
        result = run(SOURCE + 'load_run state.json && ' + block,
                     prefix + [call(listing, {"value": [pool]})] + checks)
        self.assertEqual(result.returncode, 0, result.stderr)
        create = ["network", "manager", "ipam-pool", "create",
                  "--name", "ipam-lzbegin-demo123",
                  "--network-manager-name", "avnm-lzbegin-demo123",
                  "-g", hub, "--location", "koreacentral",
                  "--address-prefixes", '["172.20.0.0/14"]',
                  "-o", "json", "--subscription", SUB]
        result = run(SOURCE + 'load_run state.json && ' + block,
                     prefix + [call(listing, {"value": []}),
                               call(create, pool)] +
                     checks)
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run(SOURCE + 'load_run state.json && ' + block,
                     prefix + [call(listing, {"value": []}),
                               call(create, code=1, stderr="pool creation failed")])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pool creation failed", result.stderr)
        result = run(SOURCE + 'load_run state.json && ' + block,
                     prefix + [call(listing, {"value": [{"id": "foreign"}]})] +
                     [group("hub"), call(pool_read, code=3, stderr="not found")])
        self.assertNotEqual(result.returncode, 0)
        result = run(SOURCE + 'load_run state.json && ' + block,
                     prefix + [call(listing, {"value": [], "nextLink": "more"})])
        self.assertNotEqual(result.returncode, 0)

    def test_new_run_preflight_rejects_feature_conflicts_and_address_overlap(self):
        manager = {"networkManagerScopeAccesses": ["Connectivity"],
                   "networkManagerScopes": {"subscriptions": [f"/subscriptions/{SUB}"],
                                            "managementGroups": []}}
        vnet = {"id": "other", "addressSpace": {"addressPrefixes": ["172.20.0.0/20"]}}
        manager_call = ["network", "manager", "list", "--subscription", SUB, "-o", "json"]
        vnet_call = ["network", "vnet", "list", "--subscription", SUB, "-o", "json"]
        for managers, vnets, expected in (
            ([], [], True),
            ([manager], [], False),
            ([], [vnet], False),
            ([], [{"addressSpace": {"addressPrefixes": ["10.0.0.0/16"]}}], True),
            ("not json", [], False),
        ):
            with self.subTest(managers=managers, vnets=vnets):
                result = run(SOURCE + f'SUBSCRIPTION_ID={SUB}; assert_new_run_subscription',
                             [call(manager_call, managers), call(vnet_call, vnets)])
                self.assertEqual(result.returncode == 0, expected, result.stderr)
        result = run(SOURCE + f'SUBSCRIPTION_ID={SUB}; assert_new_run_subscription',
                     [call(manager_call, code=3, stderr="Forbidden")])
        self.assertNotEqual(result.returncode, 0)

    def test_ready_pool_is_checked_read_only_in_active_subscription(self):
        result = run(SOURCE + f'SUBSCRIPTION_ID={SUB}; assert_shared_ipam_pool',
                     [call(REST, READY), call(MANAGER_REST, MANAGER_READY)])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_module_one_does_not_create_state_when_subscription_preflight_fails(self):
        text = (ROOT / "docs/01-prerequisites.md").read_text()
        block = next(block for block in re.findall(r"```bash\n(.*?)\n```", text, re.S)
                     if 'STATE_FILE=$(new_run ' in block)
        manager = ["network", "manager", "list", "--subscription", SUB, "-o", "json"]
        vnet = ["network", "vnet", "list", "--subscription", SUB, "-o", "json"]
        for calls in ([call(manager, code=3, stderr="Forbidden")],
                      [call(manager, []), call(vnet, [
                          {"addressSpace": {"addressPrefixes": ["172.20.0.0/20"]}}])]):
            with self.subTest(calls=calls):
                result = run(block + '\nrc=$?; test ! -e .workshop-state || exit 9; exit "$rc"',
                             [call(["account", "set", "--subscription", SUB]),
                              call(["account", "show", "--query", "id", "-o", "tsv"], SUB),
                              call(["account", "show", "--query", "id", "-o", "tsv"], SUB),
                              *calls], input_text=SUB + "\n")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("preflight" if len(calls) == 2 else "Cannot inspect subscription",
                              result.stderr)

    def test_wrong_manager_properties_fail_closed(self):
        cases = [
            {"id": MANAGER_ID.replace("rg-lzbegin-ipam", "other")},
            {"id": MANAGER_ID.replace(SUB, "22222222-2222-2222-2222-222222222222")},
            {"location": "eastus"},
            {"properties": dict(MANAGER_READY["properties"], provisioningState="Updating")},
            {"properties": dict(MANAGER_READY["properties"],
                                networkManagerScopes={"managementGroups": [],
                                                      "subscriptions": ["/subscriptions/22222222-2222-2222-2222-222222222222"]})},
            {"properties": dict(MANAGER_READY["properties"],
                                networkManagerScopes={"managementGroups": ["foreign"],
                                                      "subscriptions": [f"/subscriptions/{SUB}"]})},
            {"properties": dict(MANAGER_READY["properties"],
                                networkManagerScopes={"managementGroups": [],
                                                      "subscriptions": [f"/subscriptions/{SUB}", f"/subscriptions/{SUB}"]})},
            {"properties": dict(MANAGER_READY["properties"], networkManagerScopeAccesses=["Routing"])},
            {"properties": dict(MANAGER_READY["properties"], networkManagerScopeAccesses=["Connectivity"])},
            {"properties": dict(MANAGER_READY["properties"],
                                networkManagerScopeAccesses=["Connectivity", "SecurityAdmin"])},
            {"properties": {}},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                result = run(SOURCE + f'SUBSCRIPTION_ID={SUB}; assert_shared_ipam_pool',
                             [call(REST, READY), call(MANAGER_REST, dict(MANAGER_READY, **changes))])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("manager", result.stderr.lower())

    def test_unreadable_or_malformed_manager_fails_closed(self):
        for response in ("", "not JSON", "null", "[]"):
            with self.subTest(response=response):
                result = run(SOURCE + f'SUBSCRIPTION_ID={SUB}; assert_shared_ipam_pool',
                             [call(REST, READY), call(MANAGER_REST, response)])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("manager", result.stderr.lower())

    def test_module_one_clears_previous_run_context_before_new_subscription_check(self):
        text = (ROOT / "docs/01-prerequisites.md").read_text()
        block = next(block for block in re.findall(r"```bash\n(.*?)\n```", text, re.S)
                     if 'STATE_FILE=$(new_run ' in block)
        result = run('STATE_FILE=previous.json; IPAM_POOL_ID="' + POOL_ID + '"\n' +
                     block + '\n[[ ! -v STATE_FILE && ! -v IPAM_POOL_ID ]]',
                     [call(["account", "set", "--subscription", SUB]),
                      call(["account", "show", "--query", "id", "-o", "tsv"], SUB),
                      call(["account", "show", "--query", "id", "-o", "tsv"], SUB),
                      call(["network", "manager", "list", "--subscription", SUB, "-o", "json"],
                           code=3, stderr="Forbidden")],
                     input_text=SUB + "\n")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_previously_loaded_foreign_pool_is_rejected_without_rest_call(self):
        result = run(SOURCE + f'''
SUBSCRIPTION_ID={SUB}
IPAM_POOL_ID={POOL_ID.replace(SUB, "22222222-2222-2222-2222-222222222222")}
assert_shared_ipam_pool
''')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("pool", result.stderr.lower())

    def test_missing_pool_and_rest_failures_do_not_look_ready(self):
        for status in (3, 4):
            with self.subTest(status=status):
                result = run(SOURCE + f'SUBSCRIPTION_ID={SUB}; assert_shared_ipam_pool',
                             [call(REST, code=status, stderr="read denied or missing\n")])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("pool", result.stderr.lower())

    def test_wrong_pool_properties_fail_closed(self):
        cases = [
            {"id": POOL_ID.replace(SUB, "22222222-2222-2222-2222-222222222222")},
            {"location": "eastus"},
            {"location": None},
            {"properties": {"addressPrefixes": ["172.20.0.0/15"],
                            "provisioningState": "Succeeded"}},
            {"properties": {"addressPrefixes": ["172.20.0.0/14", "172.24.0.0/14"],
                            "provisioningState": "Succeeded"}},
            {"properties": {"addressPrefixes": ["172.20.0.0/14"],
                            "provisioningState": "Failed"}},
            {"properties": {"addressPrefixes": "172.20.0.0/14",
                            "provisioningState": "Succeeded"}},
            {"properties": {}},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                data = dict(READY, **changes)
                result = run(SOURCE + f'SUBSCRIPTION_ID={SUB}; assert_shared_ipam_pool',
                             [call(REST, data)])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("pool", result.stderr.lower())

    def test_empty_or_invalid_rest_json_is_not_success(self):
        for response in ("", "not JSON", "null", "[]"):
            with self.subTest(response=response):
                result = run(SOURCE + f'SUBSCRIPTION_ID={SUB}; assert_shared_ipam_pool',
                             [call(REST, response)])
                self.assertNotEqual(result.returncode, 0)

    def test_missing_or_invalid_subscription_cannot_be_used(self):
        for subscription in ("", "bogus", "22222222-2222-2222-2222-222222222222"):
            with self.subTest(subscription=subscription):
                result = run(SOURCE + f'SUBSCRIPTION_ID={subscription}; '
                             'IPAM_POOL_ID="' + POOL_ID + '"; assert_shared_ipam_pool')
                self.assertNotEqual(result.returncode, 0)
