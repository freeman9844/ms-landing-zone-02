import json
import re
import unittest

from harness import POOL_ID, ROOT, SUB, call, run

SOURCE = 'source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; source "$WORKSHOP_ROOT/scripts/workshop-ipam.sh"; '
REST = ["rest", "--method", "get", "--url", POOL_ID + "?api-version=2024-05-01",
        "--subscription", SUB, "-o", "json"]
READY = {"id": POOL_ID, "location": "koreacentral",
         "properties": {"addressPrefixes": ["172.20.0.0/14"],
                        "provisioningState": "Succeeded"}}


class SharedPoolTests(unittest.TestCase):
    def test_ready_pool_is_checked_read_only_in_active_subscription(self):
        result = run(SOURCE + f'SUBSCRIPTION_ID={SUB}; assert_shared_ipam_pool',
                     [call(REST, READY)])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_module_one_does_not_create_state_when_pool_is_missing_or_wrong(self):
        text = (ROOT / "docs/01-prerequisites.md").read_text()
        block = next(block for block in re.findall(r"```bash\n(.*?)\n```", text, re.S)
                     if 'STATE_FILE=$(new_run ' in block)
        for response in (call(REST, code=3, stderr="pool not found"),
                         call(REST, dict(READY, location="eastus"))):
            with self.subTest(response=response):
                result = run(block + '\nrc=$?; test ! -e .workshop-state || exit 9; exit "$rc"',
                             [call(["account", "set", "--subscription", SUB]),
                              call(["account", "show", "--query", "id", "-o", "tsv"], SUB),
                              response], input_text=SUB + "\n")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("pool", result.stderr.lower())

    def test_module_one_clears_previous_run_context_before_new_pool_check(self):
        text = (ROOT / "docs/01-prerequisites.md").read_text()
        block = next(block for block in re.findall(r"```bash\n(.*?)\n```", text, re.S)
                     if 'STATE_FILE=$(new_run ' in block)
        result = run('STATE_FILE=previous.json; IPAM_POOL_ID="' + POOL_ID + '"\n' +
                     block + '\n[[ ! -v STATE_FILE && ! -v IPAM_POOL_ID ]]',
                     [call(["account", "set", "--subscription", SUB]),
                      call(["account", "show", "--query", "id", "-o", "tsv"], SUB),
                      call(REST, code=3, stderr="pool not found")],
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
