import copy
import json
import unittest
from harness import run, call, account, group, SUB
import test_avnm_redesign as redesign
from test_network_docs import enforced_connectivity_calls, netid, rid, rg
from test_workshop_safety import admin_calls, effective_admin_call

FW = f"/subscriptions/{SUB}/resourceGroups/rg-lzbegin-hub-demo123/providers/Microsoft.Network/azureFirewalls/fw-lzbegin-demo123"
LAW = rid("hub", "Microsoft.OperationalInsights/workspaces", "log-lzbegin-demo123")
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
    def run_extension(self, script, calls, **kwargs):
        calls = list(calls)
        if calls and calls[0]["argv"] == account()["argv"] and not script.endswith(" denied"):
            calls[1:1] = enforced_connectivity_calls()
        return run(script, calls, **kwargs)

    def test_unenforced_connectivity_stops_before_firewall_or_http_evidence(self):
        calls = enforced_connectivity_calls()[:2]
        config = json.loads(calls[-1]["stdout"])
        config["connectivityCapabilities"]["peeringEnforcement"] = "Unenforced"
        calls[-1]["stdout"] = json.dumps(config)
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json allowed',
                     [account(), *calls])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unenforced Connectivity", result.stderr)

    def prefix(self):
        return [account(), group("hub"), group("spokea"), group("spokeb"),
                call(["network", "firewall", "show", "-g", rg("hub"),
                      "-n", "fw-lzbegin-demo123", "-o", "json"],
                     {"id": FW, "sku": {"name": "AZFW_VNet", "tier": "Standard"},
                      "provisioningState": "Succeeded",
                      "ipConfigurations": [{"privateIPAddress": "10.0.2.4"}]}),
                call(["monitor", "diagnostic-settings", "show", "--name", "workshop",
                      "--resource", FW, "-o", "json"],
                     {"workspaceId": LAW, "logAnalyticsDestinationType": "Dedicated",
                      "logs": [{"category": "AZFWNetworkRule", "enabled": True},
                               {"category": "AZFWApplicationRule", "enabled": True}]}),
                call(["network", "public-ip", "show", "-g", rg("hub"),
                      "-n", "pip-lzbegin-fw-demo123", "--query", "ipAddress", "-o", "tsv"],
                     "203.0.113.10"),
                *[call(["network", "nic", "show", "-g", rg(zone),
                        "-n", f"nic-lzbegin-{zone}-demo123",
                        "--query", "ipConfigurations[0].privateIPAddress", "-o", "tsv"], ip)
                  for zone, ip in (("hub", "10.0.1.4"), ("spokea", "10.10.1.4"),
                                   ("spokeb", "10.20.1.4"))]]

    def proof_prefix(self):
        return (self.prefix() + redesign.route_calls() +
                redesign.SpokeNatAbsenceTests().calls() + admin_calls("restored"))

    def route_calls(self):
        cases = (
            ("spokea", "10.20.0.0/16", "VirtualAppliance", ["10.0.2.4"]),
            ("spokeb", "10.10.0.0/16", "VirtualAppliance", ["10.0.2.4"]),
            ("spokea", "0.0.0.0/0", "VirtualAppliance", ["10.0.2.4"]),
            ("spokeb", "0.0.0.0/0", "VirtualAppliance", ["10.0.2.4"]),
            ("hub", "10.10.0.0/16", "VNetPeering", []),
            ("hub", "10.20.0.0/16", "VNetPeering", []),
        )
        return [call(["network", "nic", "show-effective-route-table", "-g", rg(zone),
                      "-n", f"nic-lzbegin-{zone}-demo123", "-o", "json"],
                     {"value": [{"state": "Active", "addressPrefix": [prefix],
                                 "nextHopType": hop, "nextHopIpAddress": next_ip}]})
                for zone, prefix, hop, next_ip in cases]

    def test_hub_to_a_requires_peering_route_before_admin_or_http(self):
        routes = self.route_calls()[:5]
        routes[-1] = copy.deepcopy(routes[-1])
        payload = json.loads(routes[-1]["stdout"])
        payload["value"][0]["nextHopType"] = "VirtualAppliance"
        payload["value"][0]["nextHopIpAddress"] = ["10.0.2.4"]
        routes[-1]["stdout"] = json.dumps(payload)
        result = self.run_extension('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json allowed',
                     self.proof_prefix() + routes)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected effective next hop", result.stderr)

    def test_hub_to_a_requires_its_admin_rule_not_a_spoke_or_nsg_rule(self):
        flow = effective_admin_call("spokea", "hub-to-a", "10.0.1.4", "10.10.1.4",
                                    "AlwaysAllow", {"value": [{
                                        "id": "defaultSecurityRules/AllowVnetInBound",
                                        "access": "AlwaysAllow"}], "skipToken": ""})
        result = self.run_extension('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json allowed',
                     self.proof_prefix() + self.route_calls() + [flow])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Effective AVNM rule does not show hub-to-a/AlwaysAllow", result.stderr)

    def test_hub_to_a_http_probe_rejects_wrong_guest_response(self):
        flows = [
            effective_admin_call(zone, rule, remote, local, "AlwaysAllow")
            for zone, local, remote, rule in (
                ("spokea", "10.10.1.4", "10.0.1.4", "hub-to-a"),
                ("spokeb", "10.20.1.4", "10.10.1.4", "a-to-b"))
        ]
        guest = call(["vm", "run-command", "invoke", "--resource-group", rg("hub"),
                      "--name", "vm-lzbegin-hub-demo123", "--command-id", "RunShellScript",
                      "--scripts", {"regex": "@/.+/lzbegin-run\\.[A-Za-z0-9]+"}, "-o", "json"])
        guest["run_guest"] = True
        result = self.run_extension('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json allowed',
                     self.proof_prefix() + self.route_calls() + flows +
                     [account(), group("hub"), guest],
                     files={"bin/curl": "#!/bin/sh\nprintf 'wrong-server\\n'\n"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unexpected successful response: wrong-server", result.stderr)

    def test_wrong_subnet_ip_stops_before_avnm_checks(self):
        calls = self.prefix()
        calls[-1]["stdout"] = "10.10.1.99"
        result = self.run_extension('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json denied',
                     calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid workshop IP", result.stderr)

    def test_wrong_managed_route_or_spoke_nat_stops_before_http(self):
        routes = redesign.route_calls()
        calls = self.prefix() + routes
        calls[-1] = copy.deepcopy(calls[-1])
        table = json.loads(calls[-1]["stdout"])
        table["routes"][1]["nextHopIpAddress"] = "10.0.2.9"
        calls[-1]["stdout"] = json.dumps(table)
        result = self.run_extension('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json allowed', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Subnet routes", result.stderr)

        nat = redesign.SpokeNatAbsenceTests().calls(attachment=netid(
            "spokea", "natGateways", "nat-lzbegin-spokea-demo123"))
        result = self.run_extension('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json allowed',
                     self.prefix() + routes + nat)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("still has a NAT", result.stderr)

    def test_denied_skips_baseline_config_rechecks_but_requires_live_spoke_route(self):
        route = copy.deepcopy(self.route_calls()[0])
        payload = json.loads(route["stdout"])
        payload["value"][0]["nextHopIpAddress"] = ["10.0.2.9"]
        route["stdout"] = json.dumps(payload)
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json denied',
                     [*self.prefix(), route])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected next hop IP", result.stderr)

    def test_wrong_admin_rule_rejected_before_http(self):
        security = admin_calls("restored")
        security[-1] = copy.deepcopy(security[-1])
        rule = json.loads(security[-1]["stdout"])
        rule["access"] = "Deny"
        security[-1]["stdout"] = json.dumps(rule)
        calls = self.prefix() + redesign.route_calls() + redesign.SpokeNatAbsenceTests().calls() + security
        result = self.run_extension('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json restored', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Security Admin rule", result.stderr)

    def test_unready_firewall_stops_before_routes_or_nat_changes(self):
        calls = [account(), group("hub"), group("spokea"), group("spokeb"),
                 call(["network", "firewall", "show", "-g", "rg-lzbegin-hub-demo123",
                       "-n", "fw-lzbegin-demo123", "-o", "json"],
                      {"provisioningState": "Updating", "ipConfigurations": []})]
        result = self.run_extension('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json allowed', calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Firewall", result.stderr)

    def test_invalid_phase_does_not_call_azure(self):
        result = run('bash "$WORKSHOP_ROOT/scripts/verify-extension.sh" state.json anything')
        self.assertNotEqual(result.returncode, 0)
