import copy
import json
import unittest

from harness import run, group
import test_avnm_redesign as redesign
from test_network_docs import az, rg, netid, rid, vnet, foreign_ids

FW = netid("hub", "azureFirewalls", "fw-lzbegin-demo123")
LAW = rid("hub", "Microsoft.OperationalInsights/workspaces", "log-lzbegin-demo123")
POLICY = netid("hub", "firewallPolicies", "fwpol-lzbegin-demo123")
FW_IP = "10.0.2.4"
CONFIG = netid("hub", "networkManagers", "avnm-lzbegin-demo123") + (
    "/securityAdminConfigurations/sc-lzbegin-http-demo123")
GROUPS = {
    zone: netid("hub", "networkManagers", "avnm-lzbegin-demo123") +
    f"/networkGroups/ng-lzbegin-route-{zone}-demo123"
    for zone in ("spokea", "spokeb")
}


def ready_calls():
    return [
        group("hub"),
        az(["network", "firewall", "show", "-g", rg("hub"), "-n", "fw-lzbegin-demo123", "-o", "json"],
           {"id": FW, "provisioningState": "Succeeded", "firewallPolicy": {"id": POLICY},
            "ipConfigurations": [{"privateIPAddress": FW_IP}]}),
        az(["monitor", "log-analytics", "workspace", "show", "-g", rg("hub"),
            "-n", "log-lzbegin-demo123", "--query", "id", "-o", "tsv"], LAW),
        az(["monitor", "diagnostic-settings", "show", "--name", "workshop", "--resource", FW, "-o", "json"],
           {"workspaceId": LAW, "logAnalyticsDestinationType": "Dedicated",
            "logs": [{"category": "AZFWNetworkRule", "enabled": True},
                     {"category": "AZFWApplicationRule", "enabled": True}]}),
        az(["network", "firewall", "policy", "rule-collection-group", "show", "-g", rg("hub"),
            "--policy-name", "fwpol-lzbegin-demo123", "-n", "workshop", "-o", "json"],
           {"ruleCollections": [
               {"name": "management", "priority": 100, "action": {"type": "Allow"},
                "rules": [{"name": "azure-management", "ruleType": "NetworkRule",
                           "ipProtocols": ["TCP"], "sourceAddresses": ["10.10.1.0/24", "10.20.1.0/24"],
                           "destinationAddresses": ["AzureCloud"], "destinationPorts": ["443"]}]},
               {"name": "lab-http", "action": {"type": "Allow"}},
               {"name": "egress-check", "action": {"type": "Allow"}},
           ]})]


def admin_calls(stage="baseline", hub="10.0.1.4", a="10.10.1.4", b="10.20.1.4"):
    calls = [az(["network", "manager", "security-admin-config", "show", "-g", rg("hub"),
                 "--network-manager-name", "avnm-lzbegin-demo123",
                 "--configuration-name", "sc-lzbegin-http-demo123", "-o", "json"],
                {"id": CONFIG, "provisioningState": "Succeeded"})]
    for zone, rules in (
        ("spokea", [("hub-to-a", hub, a, "AlwaysAllow", 200)] +
         ([("deny-hub-to-a", hub, a, "Deny", 100)] if stage == "denied" else [])),
        ("spokeb", [("hub-to-b", hub, b, "AlwaysAllow", 210),
                    ("a-to-b", a, b, "AlwaysAllow", 220)]),
    ):
        calls.append(az(["network", "manager", "security-admin-config", "rule-collection",
                         "show", "-g", rg("hub"), "--network-manager-name", "avnm-lzbegin-demo123",
                         "--configuration-name", "sc-lzbegin-http-demo123",
                         "--rule-collection-name", zone, "-o", "json"],
                        {"id": CONFIG + f"/ruleCollections/{zone}", "provisioningState": "Succeeded",
                         "appliesToGroups": [{"networkGroupId": GROUPS[zone]}]}))
        calls.append(az(["network", "manager", "security-admin-config", "rule-collection", "rule",
                         "list", "-g", rg("hub"), "--network-manager-name", "avnm-lzbegin-demo123",
                         "--configuration-name", "sc-lzbegin-http-demo123",
                         "--rule-collection-name", zone, "-o", "json"],
                        [{"id": CONFIG + f"/ruleCollections/{zone}/rules/{name}"} for name, *_ in rules]))
        for name, source, destination, access, priority in rules:
            calls.append(az(["network", "manager", "security-admin-config", "rule-collection", "rule",
                             "show", "-g", rg("hub"), "--network-manager-name", "avnm-lzbegin-demo123",
                             "--configuration-name", "sc-lzbegin-http-demo123",
                             "--rule-collection-name", zone, "--rule-name", name, "-o", "json"],
                            {"id": CONFIG + f"/ruleCollections/{zone}/rules/{name}",
                             "provisioningState": "Succeeded", "kind": "Custom",
                             "access": access, "priority": priority,
                             "direction": "Inbound", "protocol": "Tcp",
                             "sourcePortRanges": ["*"], "destinationPortRanges": ["8080"],
                             "sources": [{"addressPrefixType": "IPPrefix", "addressPrefix": source + "/32"}],
                             "destinations": [{"addressPrefixType": "IPPrefix",
                                               "addressPrefix": destination + "/32"}]}))
    return calls


class SafetyTests(unittest.TestCase):
    def execute(self, command, calls=()):
        script = ('source scripts/workshop-common.sh && source scripts/workshop-safety.sh && '
                  'load_run state.json && ' + command +
                  '\nstatus=$?\nprintf "ALIVE\\n"\nexit "$status"')
        result = run(script, calls)
        self.assertIn("ALIVE", result.stdout)
        return result

    def test_peering_lookup_requires_unique_complete_remote_id(self):
        remote = netid("spokea", "virtualNetworks", vnet("spokea"))
        args = ["network", "vnet", "peering", "list", "-g", rg("hub"), "--vnet-name", vnet("hub"), "-o", "json"]
        command = f'peering_name_for_remote "{rg("hub")}" "{vnet("hub")}" "{remote}"'
        for peerings, valid in (
            ([{"name": "generated", "remoteVirtualNetwork": {"id": remote}}], True),
            ([], False),
            ([{"name": "child", "remoteVirtualNetwork": {"id": remote + "/subnets/snet-workload"}}], False),
            ([{"name": "one", "remoteVirtualNetwork": {"id": remote}},
              {"name": "two", "remoteVirtualNetwork": {"id": remote.swapcase()}}], False),
        ):
            with self.subTest(peerings=peerings):
                result = self.execute(command, [az(args, peerings)])
                self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_resource_id_comparison_accepts_only_case_differences(self):
        for actual in (LAW.lower(), LAW.swapcase(), LAW):
            self.assertEqual(self.execute(f'assert_resource_id "{actual}" "{LAW}"').returncode, 0)
        for actual in ("", "null", *foreign_ids(LAW)):
            self.assertNotEqual(self.execute(f'assert_resource_id "{actual}" "{LAW}"').returncode, 0)

    def test_ip_validation_rejects_malformed_or_wrong_subnet_addresses(self):
        for address, network, valid in (
            ("10.0.2.4", "10.0.2.0/26", True),
            ("10.0.2.99", "10.0.2.0/26", False),
            ("999.1.2.3", "10.0.2.0/26", False),
            ("null", "10.0.2.0/26", False),
            ("10.10.1.9", "10.10.1.0/24", True),
            ("10.20.1.9", "10.10.1.0/24", False),
        ):
            with self.subTest(address=address):
                result = self.execute(f'assert_ipv4_in_subnet "{address}" "{network}"')
                self.assertEqual(result.returncode == 0, valid, result.stderr)

    def test_firewall_readiness_and_foreign_ids(self):
        result = self.execute("firewall_ready_ip", ready_calls())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(FW_IP, result.stdout)
        for index, value in (
            (1, {"id": FW, "provisioningState": "Updating", "ipConfigurations": []}),
            (1, {"id": "foreign", "provisioningState": "Succeeded",
                 "ipConfigurations": [{"privateIPAddress": FW_IP}]}),
            (1, {"id": FW, "provisioningState": "Succeeded", "firewallPolicy": {"id": POLICY},
                 "ipConfigurations": [{"privateIPAddress": "10.0.2.100"}]}),
            (2, "foreign-workspace"),
            (3, {"workspaceId": LAW, "logAnalyticsDestinationType": "AzureDiagnostics", "logs": []}),
            (4, {"ruleCollections": []}),
        ):
            with self.subTest(index=index, value=value):
                calls = copy.deepcopy(ready_calls()[:index + 1])
                calls[-1]["stdout"] = value if isinstance(value, str) else json.dumps(value)
                self.assertNotEqual(self.execute("firewall_ready_ip", calls).returncode, 0)

    def test_managed_routes_require_exact_subnet_group_prefix_and_hop(self):
        command = f'assert_avnm_routes_ready "{FW_IP}"'
        self.assertEqual(self.execute(command, redesign.route_calls()).returncode, 0)
        for index, field, bad in (
            (1, "provisioningState", "Updating"),
            (3, "appliesTo", [{"networkGroupId": GROUPS["spokeb"]}]),
            (4, "destination", {"type": "AddressPrefix", "destinationAddress": "10.0.0.0/16"}),
            (5, "nextHop", {"nextHopType": "VirtualAppliance", "nextHopAddress": "10.0.2.5"}),
            (6, "id", "foreign-subnet"),
            (6, "routeTable", {"id": "foreign-table"}),
            (7, "routes", []),
            (13, "routes", []),
        ):
            with self.subTest(index=index, field=field):
                calls = copy.deepcopy(redesign.route_calls()[:index + 1])
                data = json.loads(calls[-1]["stdout"])
                data[field] = bad
                calls[-1]["stdout"] = json.dumps(data)
                self.assertNotEqual(self.execute(command, calls).returncode, 0)

    def test_security_admin_rules_scope_ip_priority_and_denied_stage(self):
        for stage in ("baseline", "denied", "restored"):
            with self.subTest(stage=stage):
                self.assertEqual(self.execute(
                    f'assert_admin_rules_ready 10.0.1.4 10.10.1.4 10.20.1.4 {stage}',
                    admin_calls(stage)).returncode, 0)
        for stage, index, field, bad in (
            ("baseline", 0, "provisioningState", "Updating"),
            ("baseline", 1, "appliesToGroups", [{"networkGroupId": GROUPS["spokeb"]}]),
            ("baseline", 3, "priority", 100),
            ("baseline", 3, "access", "Allow"),
            ("baseline", 3, "sources", [{"addressPrefixType": "IPPrefix", "addressPrefix": "10.0.1.9/32"}]),
            ("baseline", 6, "destinationPortRanges", ["80"]),
            ("denied", 4, "access", "AlwaysAllow"),
            ("denied", 4, "priority", 230),
        ):
            with self.subTest(stage=stage, index=index, field=field):
                calls = copy.deepcopy(admin_calls(stage)[:index + 1])
                data = json.loads(calls[-1]["stdout"])
                data[field] = bad
                calls[-1]["stdout"] = json.dumps(data)
                self.assertNotEqual(self.execute(
                    f'assert_admin_rules_ready 10.0.1.4 10.10.1.4 10.20.1.4 {stage}',
                    calls).returncode, 0)

    def test_admin_rule_listing_proves_deny_absent_after_recovery(self):
        command = "assert_admin_rules_ready 10.0.1.4 10.10.1.4 10.20.1.4 "
        for stage, index, extras in (
            ("baseline", 2, ["deny-hub-to-a"]),
            ("restored", 2, ["deny-hub-to-a"]),
            ("denied", 2, []),
            ("restored", 5, ["foreign-rule"]),
        ):
            with self.subTest(stage=stage, extras=extras):
                calls = copy.deepcopy(admin_calls(stage)[:index + 1])
                rules = json.loads(calls[-1]["stdout"])
                if extras:
                    zone = "spokea" if index == 2 else "spokeb"
                    rules.extend({"id": CONFIG + f"/ruleCollections/{zone}/rules/{name}"}
                                 for name in extras)
                else:
                    rules.pop()
                calls[-1]["stdout"] = json.dumps(rules)
                self.assertNotEqual(self.execute(command + stage, calls).returncode, 0)

    def test_no_spoke_nat_fails_for_attached_nat_and_unexpected_resources(self):
        fixture = redesign.SpokeNatAbsenceTests()
        for kind, value in (
            ("attachment", "/subscriptions/other/natGateway/foreign"),
            ("nat", {"name": "unexpected"}),
            ("pip", {"name": "unexpected"}),
        ):
            with self.subTest(kind=kind):
                self.assertNotEqual(self.execute("assert_no_spoke_nat",
                                                 fixture.calls(**{kind: value})).returncode, 0)
        self.assertEqual(self.execute("assert_no_spoke_nat", fixture.calls()).returncode, 0)

    def test_readiness_lookups_fail_closed_on_api_errors_and_malformed_json(self):
        fixture = redesign.SpokeNatAbsenceTests()
        cases = [
            ("firewall_ready_ip", ready_calls()),
            (f'assert_avnm_routes_ready "{FW_IP}"', redesign.route_calls()),
            ("assert_admin_rules_ready 10.0.1.4 10.10.1.4 10.20.1.4 denied", admin_calls("denied")),
            ("assert_no_spoke_nat", fixture.calls()),
        ]
        for command, good in cases:
            for index in range(len(good)):
                for code, output in ((1, ""), (0, "{broken")):
                    with self.subTest(command=command, index=index, code=code):
                        calls = copy.deepcopy(good[:index + 1])
                        calls[-1].update(returncode=code, stdout=output)
                        if command == "assert_no_spoke_nat" and index in (2, 6) and code == 0:
                            calls.append(copy.deepcopy(good[index + 1]))
                        self.assertNotEqual(self.execute(command, calls).returncode, 0)
