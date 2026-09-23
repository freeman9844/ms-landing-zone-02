import json
import unittest
from harness import run, call, account, group, STATE, SUB


def ready_calls(existing=(), extension=False, current=0, limit=10, power="VM running"):
    calls = [
        account(),
        call(["account", "list-locations", "--query", "[].name", "-o", "json"], ["koreacentral"]),
        call(["extension", "show", "--name", "virtual-network-manager", "--query", "version", "-o", "tsv"], "1.0.0"),
        call(["provider", "show", "--namespace", "Microsoft.Network", "--query", "registrationState", "-o", "tsv"], "Registered"),
        call(["provider", "show", "--namespace", "Microsoft.Compute", "--query", "registrationState", "-o", "tsv"], "Registered"),
    ]
    if extension:
        calls.append(call(["provider", "show", "--namespace", "Microsoft.OperationalInsights",
                           "--query", "registrationState", "-o", "tsv"], "Registered"))
    for zone in ("hub", "spokea", "spokeb"):
        rg = STATE["resourceGroups"][zone]
        calls.append(call(["group", "exists", "--name", rg, "-o", "tsv"],
                          "true" if zone in existing else "false"))
        if zone in existing:
            calls.extend([
                group(zone),
                call(["vm", "list", "--resource-group", rg, "--show-details", "-o", "json"], [{
                    "name": f"vm-lzbegin-{zone}-demo123",
                    "id": f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.Compute/virtualMachines/vm-lzbegin-{zone}-demo123",
                    "location": "koreacentral", "hardwareProfile": {"vmSize": "Standard_B2als_v2"},
                    "provisioningState": "Succeeded", "powerState": power,
                }]),
            ])
    if len(existing) == 3:
        return calls
    return calls + [
        call(["vm", "list-skus", "--location", "koreacentral", "--size", "Standard_B2als_v2", "--all", "-o", "json"], [
            {"name": "Standard_B2als_v2", "family": "standardBasv2Family", "restrictions": [],
             "capabilities": [{"name": "vCPUs", "value": "2"}]}]),
        call(["vm", "list-usage", "--location", "koreacentral", "-o", "json"], [
            {"name": {"value": "cores"}, "currentValue": current, "limit": limit},
            {"name": {"value": "standardBasv2Family"}, "currentValue": current, "limit": limit}]),
    ]


class PreflightTests(unittest.TestCase):
    def test_numeric_string_quota_from_live_cli_is_supported(self):
        calls = ready_calls()
        calls[-1]["stdout"] = json.dumps([
            {"name": {"value": "cores"}, "currentValue": "0", "limit": "100"},
            {"name": {"value": "standardBasv2Family"}, "currentValue": "0", "limit": "100"},
        ])
        result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json', calls)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_quota_is_not_coerced_to_available_capacity(self):
        for value in (None, True, "unknown", "-1", -1, 1.5):
            with self.subTest(value=value):
                calls = ready_calls()
                usage = json.loads(calls[-1]["stdout"])
                usage[0]["currentValue"] = value
                calls[-1]["stdout"] = json.dumps(usage)
                result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json', calls)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("quota", result.stderr)

    def test_extension_reuses_running_vms_without_requesting_more_quota(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json --extension',
                     ready_calls(existing=("hub", "spokea", "spokeb"), extension=True))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_missing_avnm_extension_fails_before_resource_checks(self):
        calls = ready_calls()[:3]
        calls[-1].update(returncode=1, stdout="", stderr="extension not installed")
        result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("virtual-network-manager", result.stderr)

    def test_rerun_with_all_vms_needs_no_new_capacity(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json',
                     ready_calls(existing=("hub", "spokea", "spokeb")))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_partial_deployment_needs_only_missing_vm_capacity(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json',
                     ready_calls(existing=("hub", "spokea"), current=4, limit=6))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_extension_rejects_missing_vm(self):
        calls = ready_calls(extension=True)[:7]
        result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json --extension', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing", result.stderr)

    def test_existing_unready_vm_is_not_counted_as_allocated_capacity(self):
        for power in ("VM deallocated", "VM stopped"):
            with self.subTest(power=power):
                calls = ready_calls(existing=("hub",), power=power)[:8]
                result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json', calls)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ready", result.stderr)

    def test_foreign_group_is_not_used_to_discount_quota(self):
        calls = ready_calls(existing=("hub",))[:7]
        data = json.loads(calls[-1]["stdout"])
        data["tags"]["runId"] = "someoneelse"
        calls[-1]["stdout"] = json.dumps(data)
        result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Ownership", result.stderr)

    def test_ready_is_read_only(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json', ready_calls())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_missing_provider_stops_before_quota(self):
        calls = ready_calls()[:4]
        calls[-1]["stdout"] = "NotRegistered"
        result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Microsoft.Network", result.stderr)

    def test_empty_avnm_extension_version_is_rejected(self):
        calls = ready_calls()
        calls[2]["stdout"] = ""
        result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json', calls[:3])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("virtual-network-manager", result.stderr)

    def test_capacity_shortfall_is_error(self):
        calls = ready_calls()
        calls[-1]["stdout"] = '[{"name":{"value":"cores"},"currentValue":5,"limit":10},{"name":{"value":"standardBasv2Family"},"currentValue":0,"limit":10}]'
        result = run('bash "$WORKSHOP_ROOT/scripts/preflight.sh" state.json', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("quota", result.stderr)
