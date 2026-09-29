import copy
import json
import unittest

from harness import run, group
from test_ipam_cidrs import CIDR_ENV, PREFIXES
import test_avnm_redesign as redesign
from test_network_docs import az, rg, netid, rid, vnet, foreign_ids, enforced_connectivity_calls

FW = netid("hub", "azureFirewalls", "fw-lzbegin-demo123")
LAW = rid("hub", "Microsoft.OperationalInsights/workspaces", "log-lzbegin-demo123")
POLICY = netid("hub", "firewallPolicies", "fwpol-lzbegin-demo123")
FW_IP = "172.20.1.4"
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
                           "ipProtocols": ["TCP"], "sourceAddresses": [PREFIXES["spokea"][1], PREFIXES["spokeb"][1]],
                           "destinationAddresses": ["AzureCloud"], "destinationPorts": ["443"]}]},
               {"name": "lab-http", "priority": 200, "action": {"type": "Allow"},
                "rules": [{"name": "spokea-to-spokeb", "ruleType": "NetworkRule",
                           "ipProtocols": ["TCP"], "sourceAddresses": [PREFIXES["spokea"][1]],
                           "destinationAddresses": [PREFIXES["spokeb"][1]],
                           "destinationPorts": ["8080"]}]},
               {"name": "egress-check", "priority": 300, "action": {"type": "Allow"},
                "rules": [{"name": "public-ip-check", "ruleType": "ApplicationRule",
                           "sourceAddresses": [PREFIXES["spokea"][1], PREFIXES["spokeb"][1]],
                           "targetFqdns": ["api.ipify.org"]}]},
           ]})]


def admin_calls(stage="baseline", hub="172.20.0.4", a="172.20.16.4", b="172.20.32.4"):
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
                             "sourcePortRanges": ["0-65535"], "destinationPortRanges": ["8080"],
                             "sources": [{"addressPrefixType": "IPPrefix", "addressPrefix": source + "/32"}],
                             "destinations": [{"addressPrefixType": "IPPrefix",
                                               "addressPrefix": destination + "/32"}]}))
    return calls


def effective_admin_rule(zone, name, source, destination, access):
    return {
        "id": CONFIG + f"/ruleCollections/{zone}/rules/{name}",
        "access": access,
        "direction": "Inbound",
        "protocol": "Tcp",
        "sourcePortRanges": ["0-65535"],
        "destinationPortRanges": ["8080"],
        "sources": [{"addressPrefixType": "IPPrefix", "addressPrefix": source + "/32"}],
        "destinations": [{"addressPrefixType": "IPPrefix", "addressPrefix": destination + "/32"}],
        "priority": 0,
    }


def effective_admin_call(zone, name, source, destination, access, payload=None):
    if payload is None:
        payload = {"value": [effective_admin_rule(zone, name, source, destination, access)],
                   "skipToken": ""}
    return az(["network", "manager", "list-effective-security-admin-rule",
               "-g", rg(zone), "--virtual-network-name", vnet(zone), "-o", "json"], payload)


class SafetyTests(unittest.TestCase):
    def execute(self, command, calls=()):
        script = ('source scripts/workshop-common.sh && source scripts/workshop-safety.sh && '
                  'load_run state.json && ' + CIDR_ENV + command +
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

    def test_enforced_connectivity_requires_exact_config_deployment_and_four_forwarded_peerings(self):
        command = "assert_enforced_connectivity"
        self.assertEqual(self.execute(command, enforced_connectivity_calls()).returncode, 0)
        effective = json.loads(enforced_connectivity_calls()[4]["stdout"])["value"][0]
        for index, path, bad in (
            (1, ("id",), netid("hub", "networkManagers", "other") +
             "/connectivityConfigurations/cc-lzbegin-hub-spoke-demo123"),
            (1, ("connectivityTopology",), "Mesh"),
            (1, ("hubs", 0, "resourceId"), netid("spokea", "virtualNetworks", vnet("spokea"))),
            (1, ("appliesToGroups", 0, "networkGroupId"), "wrong-group"),
            (1, ("connectivityCapabilities", "peeringEnforcement"), "Unenforced"),
            (1, ("connectivityCapabilities", "connectedGroupAddressOverlap"), "Disallowed"),
            (1, ("connectivityCapabilities", "connectedGroupPrivateEndpointsScale"), "HighScale"),
            (2, ("deploymentStatus",), "NotStarted"),
            (2, ("deploymentStatus",), "Failed"),
            (2, ("configurationIds", 0), "wrong-configuration"),
            (4, ("value",), []),
            (4, ("value",), [effective, effective]),
            (4, ("value", 0, "properties", "connectivityCapabilities", "peeringEnforcement"), "Unenforced"),
            (6, ("value", 0, "id"), "wrong-effective-configuration"),
            (6, ("value", 0, "properties", "connectivityCapabilities", "peeringEnforcement"), "Unenforced"),
            (8, (0, "allowForwardedTraffic"), False),
            (8, (1, "allowForwardedTraffic"), False),
            (8, (1, "allowVirtualNetworkAccess"), False),
            (10, (0, "allowForwardedTraffic"), False),
            (10, (0, "peeringState"), "Initiated"),
            (12, (0, "allowForwardedTraffic"), False),
            (12, (0, "remoteVirtualNetwork", "id"), netid("spokea", "virtualNetworks", vnet("spokea"))),
        ):
            with self.subTest(index=index, path=path, bad=bad):
                calls = copy.deepcopy(enforced_connectivity_calls()[:index + 1])
                value = json.loads(calls[-1]["stdout"])
                if index == 2:
                    value = value[0]
                cursor = value
                for key in path[:-1]:
                    cursor = cursor[key]
                cursor[path[-1]] = bad
                calls[-1]["stdout"] = json.dumps([value] if index == 2 else value)
                self.assertNotEqual(self.execute(command, calls).returncode, 0)

    def test_enforced_connectivity_rejects_stale_success_and_lookup_errors(self):
        good = enforced_connectivity_calls()
        for status in ("NotStarted", "Failed"):
            with self.subTest(status=status):
                calls = copy.deepcopy(good[:3])
                statuses = json.loads(calls[-1]["stdout"])
                statuses.append(dict(statuses[0], commitTime="2026-01-02T00:00:00Z",
                                     deploymentStatus=status))
                calls[-1]["stdout"] = json.dumps(statuses)
                self.assertNotEqual(self.execute("assert_enforced_connectivity", calls).returncode, 0)
        for index in range(len(good)):
            for code, output in ((1, ""), (0, "{broken")):
                with self.subTest(index=index, code=code):
                    if "argv" not in good[index]:
                        continue
                    calls = copy.deepcopy(good[:index + 1])
                    calls[-1].update(returncode=code, stdout=output)
                    self.assertNotEqual(self.execute("assert_enforced_connectivity", calls).returncode, 0)

    def test_enforced_connectivity_accepts_terminal_cli_page(self):
        calls = enforced_connectivity_calls()
        calls[2]["stdout"] = json.dumps({
            "skipToken": "",
            "value": json.loads(calls[2]["stdout"]),
        })
        self.assertEqual(self.execute("assert_enforced_connectivity", calls).returncode, 0)

    def test_enforced_connectivity_requires_rest_effective_capability(self):
        calls = enforced_connectivity_calls()
        self.assertEqual(self.execute("assert_enforced_connectivity", calls).returncode, 0)
        stale = copy.deepcopy(calls[:5])
        payload = json.loads(stale[-1]["stdout"])
        payload["value"][0]["properties"]["connectivityCapabilities"] = None
        stale[-1]["stdout"] = json.dumps(payload)
        self.assertNotEqual(self.execute("assert_enforced_connectivity", stale).returncode, 0)

    def test_resource_id_comparison_accepts_only_case_differences(self):
        for actual in (LAW.lower(), LAW.swapcase(), LAW):
            self.assertEqual(self.execute(f'assert_resource_id "{actual}" "{LAW}"').returncode, 0)
        for actual in ("", "null", *foreign_ids(LAW)):
            self.assertNotEqual(self.execute(f'assert_resource_id "{actual}" "{LAW}"').returncode, 0)

    def test_ip_validation_rejects_malformed_or_wrong_subnet_addresses(self):
        for address, network, valid in (
            ("172.20.1.4", "172.20.1.0/26", True),
            ("172.20.1.99", "172.20.1.0/26", False),
            ("999.1.2.3", "172.20.1.0/26", False),
            ("null", "172.20.1.0/26", False),
            ("172.20.16.9", "172.20.16.0/24", True),
            ("172.20.32.9", "172.20.16.0/24", False),
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
                 "ipConfigurations": [{"privateIPAddress": "172.20.1.100"}]}),
            (2, "foreign-workspace"),
            (3, {"workspaceId": LAW, "logAnalyticsDestinationType": "AzureDiagnostics", "logs": []}),
            (4, {"ruleCollections": []}),
        ):
            with self.subTest(index=index, value=value):
                calls = copy.deepcopy(ready_calls()[:index + 1])
                calls[-1]["stdout"] = value if isinstance(value, str) else json.dumps(value)
                self.assertNotEqual(self.execute("firewall_ready_ip", calls).returncode, 0)

    def test_firewall_uses_live_ipam_firewall_and_management_ranges(self):
        calls = copy.deepcopy(ready_calls())
        firewall = json.loads(calls[1]["stdout"])
        firewall["ipConfigurations"][0]["privateIPAddress"] = "172.21.1.4"
        calls[1]["stdout"] = json.dumps(firewall)
        collections = json.loads(calls[4]["stdout"])
        for collection in collections["ruleCollections"]:
            for rule in collection["rules"]:
                rule["sourceAddresses"] = [
                    value.replace("172.20.", "172.21.") for value in rule["sourceAddresses"]]
                if "destinationAddresses" in rule:
                    rule["destinationAddresses"] = [
                        value.replace("172.20.", "172.21.") for value in rule["destinationAddresses"]]
        calls[4]["stdout"] = json.dumps(collections)
        command = ('source scripts/workshop-common.sh; source scripts/workshop-safety.sh; '
                   'load_run state.json; ' + CIDR_ENV.replace("172.20.", "172.21.") +
                   'firewall_ready_ip')
        result = run(command, calls)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("172.21.1.4", result.stdout)

    def test_managed_routes_require_exact_subnet_group_prefix_and_hop(self):
        command = f'assert_avnm_routes_ready "{FW_IP}"'
        self.assertEqual(self.execute(command, redesign.route_calls()).returncode, 0)
        for index, field, bad in (
            (1, "provisioningState", "Updating"),
            (3, "appliesTo", [{"networkGroupId": GROUPS["spokeb"]}]),
            (4, "destination", {"type": "AddressPrefix", "destinationAddress": "10.0.0.0/16"}),
            (5, "nextHop", {"nextHopType": "VirtualAppliance", "nextHopAddress": "172.20.1.5"}),
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
                    f'assert_admin_rules_ready 172.20.0.4 172.20.16.4 172.20.32.4 {stage}',
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
                    f'assert_admin_rules_ready 172.20.0.4 172.20.16.4 172.20.32.4 {stage}',
                    calls).returncode, 0)

    def test_admin_rule_listing_proves_deny_absent_after_recovery(self):
        command = "assert_admin_rules_ready 172.20.0.4 172.20.16.4 172.20.32.4 "
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
            ("assert_admin_rules_ready 172.20.0.4 172.20.16.4 172.20.32.4 denied", admin_calls("denied")),
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
