import unittest
from harness import run, call, account, group, SUB

FW = f"/subscriptions/{SUB}/resourceGroups/rg-lzbegin-hub-demo123/providers/Microsoft.Network/azureFirewalls/fw-lzbegin-demo123"
WORKSPACE = "22222222-2222-2222-2222-222222222222"
QUERY_ARGS = ["monitor", "log-analytics", "query", "--workspace", WORKSPACE,
              "--analytics-query", {"regex": "(?s)AZFWNetworkRule.*TimeGenerated.*2026-09-18T00:00:00Z.*"
                                     "SourceIp.*10\\.10\\.1\\.4.*DestinationIp.*10\\.20\\.1\\.4.*"
                                     "DestinationPort.*8080.*Action.*Allow.*_ResourceId.*fw-lzbegin-demo123.*"},
              "--timespan", "PT1H", "-o", "json"]


def setup_calls():
    return [account(), group("hub"),
            call(["network", "firewall", "show", "-g", "rg-lzbegin-hub-demo123", "-n", "fw-lzbegin-demo123",
                  "--query", "id", "-o", "tsv"], FW),
            call(["monitor", "log-analytics", "workspace", "show", "-g", "rg-lzbegin-hub-demo123",
                  "-n", "log-lzbegin-demo123", "--query", "customerId", "-o", "tsv"], WORKSPACE)]


class FirewallLogTests(unittest.TestCase):
    command = ('bash "$WORKSHOP_ROOT/scripts/firewall-logs.sh" state.json '
               '2026-09-18T00:00:00Z 10.10.1.4 10.20.1.4 8080 Allow')

    def test_waits_for_matching_flow_not_just_any_rows(self):
        row = {"TimeGenerated": "2026-09-18T00:00:01Z", "SourceIp": "10.10.1.4",
               "DestinationIp": "10.20.1.4", "DestinationPort": 8080,
               "Action": "Allow", "_ResourceId": FW}
        wrong = dict(row, SourceIp="10.10.1.99")
        result = run(self.command, setup_calls() + [
            call(QUERY_ARGS, []), call(QUERY_ARGS, [wrong]), call(QUERY_ARGS, [row])])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS", result.stdout)

    def test_query_error_is_not_a_successful_empty_result(self):
        result = run(self.command, setup_calls() + [call(QUERY_ARGS, "", code=1, stderr="Forbidden")])
        self.assertNotEqual(result.returncode, 0)

    def test_twenty_empty_responses_are_incomplete(self):
        result = run(self.command, setup_calls() + [call(QUERY_ARGS, []) for _ in range(20)])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("10 minutes", result.stderr)

    def test_invalid_query_inputs_never_reach_azure(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/firewall-logs.sh" state.json '
                     '"not-a-date" "1.1.1.1;bad" 10.20.1.4 8080 Allow')
        self.assertNotEqual(result.returncode, 0)


class ExtensionGateTests(unittest.TestCase):
    def test_unready_firewall_stops_before_routes_or_nat_changes(self):
        calls = [account(), group("hub"), group("spokea"), group("spokeb"),
                 call(["network", "firewall", "show", "-g", "rg-lzbegin-hub-demo123",
                       "-n", "fw-lzbegin-demo123", "-o", "json"],
                      {"provisioningState": "Updating", "ipConfigurations": []})]
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json allowed', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Firewall", result.stderr)

    def test_invalid_phase_does_not_call_azure(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json anything')
        self.assertNotEqual(result.returncode, 0)
