import json
import unittest
from harness import run, call, account, group, STATE


def inventory(absent=False):
    calls = [account()]
    for zone, name in STATE["resourceGroups"].items():
        calls.append(call(["group", "exists", "--name", name, "-o", "tsv"], "false" if absent else "true"))
        if not absent:
            calls.append(group(zone))
    return calls


class CleanupTests(unittest.TestCase):
    def test_wrong_confirmation_never_deletes(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', inventory(), input_text="no\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("cancelled", result.stderr)

    def test_all_absent_is_explicit_success_without_prompt(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', inventory(True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("already absent", result.stdout)

    def test_lookup_error_is_not_treated_as_absent(self):
        calls = [account(), call(["group", "exists", "--name", STATE["resourceGroups"]["hub"], "-o", "tsv"],
                                 "", code=1, stderr="Forbidden")]
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls)
        self.assertNotEqual(result.returncode, 0)

    def test_valid_confirmation_checks_actual_deletion(self):
        calls = inventory() + [account()] + [group(zone) for zone in STATE["resourceGroups"]]
        for name in STATE["resourceGroups"].values():
            calls.append(call(["group", "delete", "--name", name, "--yes", "--no-wait"]))
        for name in STATE["resourceGroups"].values():
            calls.append(call(["group", "exists", "--name", name, "-o", "tsv"], "false"))
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls,
                     input_text=f"DELETE demo123 FROM {STATE['subscriptionId']}\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("deletion complete", result.stdout)

    def test_mismatched_owner_prevents_all_deletion(self):
        calls = inventory()[:3]
        data = json.loads(calls[-1]["stdout"])
        data["tags"]["managedBy"] = "production"
        calls[-1]["stdout"] = json.dumps(data)
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls)
        self.assertNotEqual(result.returncode, 0)
