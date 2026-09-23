import copy
import json
import unittest
from harness import run, group, SUB
from test_network_docs import az, rg, netid, rid, vnet, subnet_args, OWNED, recase_ids, foreign_ids

FW = netid("hub", "azureFirewalls", "fw-lzbegin-demo123")
LAW = rid("hub", "Microsoft.OperationalInsights/workspaces", "log-lzbegin-demo123")
POLICY = netid("hub", "firewallPolicies", "fwpol-lzbegin-demo123")
FW_IP = "10.0.2.4"


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
           {"ruleCollections": [{"name": name, "action": {"type": "Allow"}}
                                for name in ("management", "lab-http", "egress-check")]})]


def generated_peering_name(local, remote):
    return f"avnm-{local}-{remote}"


def peering_list_call(local, remote, peerings=None):
    remote_id = netid(remote, "virtualNetworks", vnet(remote))
    if peerings is None:
        peerings = [{
            "name": generated_peering_name(local, remote),
            "remoteVirtualNetwork": {"id": remote_id},
        }]
    return az(["network", "vnet", "peering", "list", "-g", rg(local), "--vnet-name", vnet(local), "-o", "json"],
              peerings)


def peering_show_call(local, remote, data=None, name=None):
    remote_id = netid(remote, "virtualNetworks", vnet(remote))
    if data is None:
        data = {"peeringState": "Connected", "allowForwardedTraffic": True,
                "allowVirtualNetworkAccess": True, "remoteVirtualNetwork": {"id": remote_id}}
    return az(["network", "vnet", "peering", "show", "-g", rg(local), "--vnet-name", vnet(local),
               "-n", name or generated_peering_name(local, remote), "-o", "json"], data)


def tables_calls():
    calls = []
    for zone, prefix in (("spokea", "10.20.0.0/16"), ("spokeb", "10.10.0.0/16")):
        table = f"rt-lzbegin-{zone}-demo123"
        calls += [group(zone), az(["network", "route-table", "show", "-g", rg(zone), "-n", table, "-o", "json"],
                                  {"id": netid(zone, "routeTables", table), "routes": [
                                      {"name": "to-other-spoke", "addressPrefix": prefix,
                                       "nextHopType": "VirtualAppliance", "nextHopIpAddress": FW_IP},
                                      {"name": "to-internet", "addressPrefix": "0.0.0.0/0",
                                       "nextHopType": "VirtualAppliance", "nextHopIpAddress": FW_IP}]})]
        for local, remote in (("hub", zone), (zone, "hub")):
            calls.append(peering_list_call(local, remote))
            calls.append(peering_show_call(local, remote))
    return calls


def removal_calls(zone, stage):
    nat = netid(zone, "natGateways", f"nat-lzbegin-{zone}-demo123")
    pip = netid(zone, "publicIPAddresses", f"pip-lzbegin-{zone}-demo123")
    subnet = netid(zone, "virtualNetworks", f"{vnet(zone)}/subnets/snet-workload")
    data = {"id": subnet, "routeTable": {"id": netid(zone, "routeTables", f"rt-lzbegin-{zone}-demo123")},
            "natGateway": {"id": nat} if stage == "detach" else None}
    calls = [group(zone), az(["network", "vnet", "subnet", "show", *subnet_args(zone), "-o", "json"], data)]
    if stage == "pip":
        calls.append(az(["network", "nat", "gateway", "list", "-g", rg(zone), "-o", "json"], []))
    else:
        calls.append(az(["network", "nat", "gateway", "show", "-g", rg(zone),
                         "-n", f"nat-lzbegin-{zone}-demo123", "-o", "json"],
                        {"id": nat, "tags": OWNED, "publicIpAddresses": [{"id": pip}],
                         "subnets": [{"id": subnet}] if stage == "detach" else []}))
    calls.append(az(["network", "public-ip", "show", "-g", rg(zone),
                     "-n", f"pip-lzbegin-{zone}-demo123", "-o", "json"],
                    {"id": pip, "tags": OWNED, "natGateway": {"id": nat} if stage != "pip" else None,
                     "ipConfiguration": None}))
    return calls


class SafetyTests(unittest.TestCase):
    def execute(self, command, calls=()):
        script = ('source scripts/workshop-common.sh && source scripts/workshop-safety.sh && '
                  'load_run state.json && ' + command +
                  '\nstatus=$?\nprintf "ALIVE\\n"\nexit "$status"')
        result = run(script, calls)
        self.assertIn("ALIVE", result.stdout)
        return result

    def test_peering_lookup_returns_the_only_complete_remote_id_match(self):
        remote = netid("spokea", "virtualNetworks", vnet("spokea"))
        calls = [az([
            "network", "vnet", "peering", "list",
            "-g", rg("hub"),
            "--vnet-name", vnet("hub"),
            "-o", "json",
        ], [
            {"name": "generated-a", "remoteVirtualNetwork": {"id": remote}},
            {"name": "foreign", "remoteVirtualNetwork": {"id": "foreign"}},
        ])]
        result = self.execute(
            f'peering_name_for_remote "{rg("hub")}" "{vnet("hub")}" "{remote}"',
            calls,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("generated-a", result.stdout)

    def test_peering_lookup_rejects_zero_or_duplicate_matches(self):
        remote = netid("spokea", "virtualNetworks", vnet("spokea"))
        for peerings in (
            [],
            [{"name": "child-id", "remoteVirtualNetwork": {"id": remote + "/subnets/snet-workload"}}],
            [
                {"name": "one", "remoteVirtualNetwork": {"id": remote}},
                {"name": "two", "remoteVirtualNetwork": {"id": remote.swapcase()}},
            ],
        ):
            with self.subTest(peerings=peerings):
                calls = [az([
                    "network", "vnet", "peering", "list",
                    "-g", rg("hub"),
                    "--vnet-name", vnet("hub"),
                    "-o", "json",
                ], peerings)]
                result = self.execute(
                    f'peering_name_for_remote "{rg("hub")}" "{vnet("hub")}" "{remote}"',
                    calls,
                )
                self.assertNotEqual(result.returncode, 0)

    def test_peering_lookup_rejects_missing_or_empty_match_name(self):
        remote = netid("spokea", "virtualNetworks", vnet("spokea"))
        for match in (
            {"remoteVirtualNetwork": {"id": remote}},
            {"name": "", "remoteVirtualNetwork": {"id": remote}},
        ):
            with self.subTest(match=match):
                calls = [az([
                    "network", "vnet", "peering", "list",
                    "-g", rg("hub"),
                    "--vnet-name", vnet("hub"),
                    "-o", "json",
                ], [match])]
                result = self.execute(
                    f'peering_name_for_remote "{rg("hub")}" "{vnet("hub")}" "{remote}"',
                    calls,
                )
                self.assertNotEqual(result.returncode, 0)

    def test_resource_id_comparison_accepts_only_case_differences(self):
        for actual in (LAW.lower(), LAW.swapcase(), LAW):
            result = self.execute(f'assert_resource_id "{actual}" "{LAW}"')
            self.assertEqual(result.returncode, 0, result.stderr)
        for actual in ("", "null", *foreign_ids(LAW)):
            result = self.execute(f'assert_resource_id "{actual}" "{LAW}"')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ERROR:", result.stderr)

    def test_safety_guards_accept_casing_for_all_resource_id_relationships(self):
        cases = [("firewall_ready_ip", ready_calls()),
                 (f'assert_route_tables_ready "{FW_IP}"', tables_calls())]
        cases += [(f"assert_spoke_nat_removal {zone} {stage}", removal_calls(zone, stage))
                  for zone in ("spokea", "spokeb") for stage in ("detach", "nat", "pip")]
        for command, calls in cases:
            for transform in (str.lower, str.swapcase):
                with self.subTest(command=command, casing=transform.__name__):
                    altered = recase_ids(calls, transform)
                    if command == "firewall_ready_ip":
                        data = json.loads(altered[3]["stdout"])
                        data["workspaceId"] = LAW.swapcase() if transform == str.lower else LAW.lower()
                        altered[3]["stdout"] = json.dumps(data)
                    result = self.execute(command, altered)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_workspace_discovery_and_reference_reject_foreign_complete_ids(self):
        for index in (2, 3):
            for bad in foreign_ids(LAW):
                with self.subTest(index=index, value=bad):
                    calls = ready_calls()[:index + 1]
                    if index == 2:
                        calls[-1]["stdout"] = bad.lower()
                    else:
                        data = json.loads(calls[-1]["stdout"])
                        data["workspaceId"] = bad.lower()
                        calls[-1]["stdout"] = json.dumps(data)
                    result = self.execute("firewall_ready_ip", calls)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("ERROR:", result.stderr)

    def test_nat_absence_guard_rejects_existing_nat_regardless_of_id_case(self):
        for zone in ("spokea", "spokeb"):
            for transform in (str.lower, str.swapcase):
                calls = removal_calls(zone, "pip")[:3]
                calls[-1]["stdout"] = json.dumps([{
                    "id": transform(netid(zone, "natGateways", f"nat-lzbegin-{zone}-demo123")),
                    "name": transform(f"nat-lzbegin-{zone}-demo123"),
                }])
                result = self.execute(f"assert_spoke_nat_removal {zone} pip", calls)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR:", result.stderr)

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

    def test_readiness_requires_firewall_diagnostics_and_all_allow_collections(self):
        result = self.execute("firewall_ready_ip", ready_calls())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(FW_IP, result.stdout)
        cases = [
            (1, {"id": FW, "provisioningState": "Updating", "ipConfigurations": []}),
            (1, {"id": "foreign", "provisioningState": "Succeeded", "ipConfigurations": [{"privateIPAddress": FW_IP}]}),
            (1, {"id": FW, "provisioningState": "Succeeded", "firewallPolicy": {"id": POLICY},
                 "ipConfigurations": [{"privateIPAddress": "10.0.2.100"}]}),
            (2, "foreign-workspace"),
            (3, {"workspaceId": LAW, "logAnalyticsDestinationType": "AzureDiagnostics", "logs": []}),
            (3, {"workspaceId": LAW, "logAnalyticsDestinationType": "Dedicated",
                 "logs": [{"category": "AZFWNetworkRule", "enabled": "true"},
                          {"category": "AZFWApplicationRule", "enabled": True}]}),
            (4, {"ruleCollections": [{"name": n, "action": {"type": "Deny" if n == "lab-http" else "Allow"}}
                                    for n in ("management", "lab-http", "egress-check")]}),
            (4, {"ruleCollections": []}),
        ]
        for index, value in cases:
            with self.subTest(index=index, value=value):
                calls = ready_calls()[:index + 1]
                calls[-1]["stdout"] = value if isinstance(value, str) else json.dumps(value)
                self.assertNotEqual(self.execute("firewall_ready_ip", calls).returncode, 0)

    def test_both_tables_and_all_four_forwarded_peerings_are_required(self):
        result = self.execute(f'assert_route_tables_ready "{FW_IP}"', tables_calls())
        self.assertEqual(result.returncode, 0, result.stderr)
        for index in (1, 7):
            calls = tables_calls()[:index + 1]
            data = json.loads(calls[-1]["stdout"])
            data["routes"][0]["addressPrefix"] = "10.0.0.0/16"
            calls[-1]["stdout"] = json.dumps(data)
            with self.subTest(route_index=index):
                self.assertNotEqual(self.execute(f'assert_route_tables_ready "{FW_IP}"', calls).returncode, 0)
        for index in (3, 5, 9, 11):
            calls = tables_calls()[:index + 1]
            data = json.loads(calls[-1]["stdout"])
            data["allowForwardedTraffic"] = False
            calls[-1]["stdout"] = json.dumps(data)
            with self.subTest(peering_index=index):
                self.assertNotEqual(self.execute(f'assert_route_tables_ready "{FW_IP}"', calls).returncode, 0)

    def test_removal_checks_order_exact_scope_and_resource_tags(self):
        for zone in ("spokea", "spokeb"):
            for stage in ("detach", "nat", "pip"):
                with self.subTest(zone=zone, stage=stage):
                    result = self.execute(f"assert_spoke_nat_removal {zone} {stage}", removal_calls(zone, stage))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    for index in range(1, 4):
                        calls = removal_calls(zone, stage)[:index + 1]
                        calls[-1]["stdout"] = "null"
                        self.assertNotEqual(self.execute(f"assert_spoke_nat_removal {zone} {stage}", calls).returncode, 0)
                    for resource in (2, 3) if stage != "pip" else (3,):
                        mismatches = [("id", "foreign")] + [
                            ("tags", dict(OWNED, **{tag: "other"})) for tag in OWNED]
                        for key, value in mismatches:
                            calls = removal_calls(zone, stage)[:resource + 1]
                            data = json.loads(calls[-1]["stdout"])
                            data[key] = value
                            calls[-1]["stdout"] = json.dumps(data)
                            self.assertNotEqual(self.execute(f"assert_spoke_nat_removal {zone} {stage}", calls).returncode, 0)

    def test_removal_rejects_changed_resource_references(self):
        for zone in ("spokea", "spokeb"):
            for stage, index, field, value in (
                ("detach", 1, "natGateway", {"id": "foreign-nat"}),
                ("detach", 1, "routeTable", {"id": "foreign-table"}),
                ("detach", 2, "subnets", [{"id": "foreign-subnet"}]),
                ("detach", 2, "publicIpAddresses", [{"id": "foreign-pip"}]),
                ("nat", 2, "subnets", [{"id": "still-attached"}]),
                ("nat", 2, "publicIpAddresses", []),
                ("pip", 3, "natGateway", {"id": "other-nat"}),
                ("pip", 3, "ipConfiguration", {"id": "attached-nic"}),
            ):
                with self.subTest(zone=zone, stage=stage, field=field):
                    calls = removal_calls(zone, stage)[:index + 1]
                    data = json.loads(calls[-1]["stdout"])
                    data[field] = value
                    calls[-1]["stdout"] = json.dumps(data)
                    self.assertNotEqual(self.execute(f"assert_spoke_nat_removal {zone} {stage}", calls).returncode, 0)

    def test_route_table_gate_rejects_wrong_hops_extra_routes_and_wrong_peers(self):
        for index in (1, 7):
            calls = tables_calls()[:index + 1]
            data = json.loads(calls[-1]["stdout"])
            data["routes"].append({"name": "unexpected", "addressPrefix": "10.0.0.0/8", "nextHopType": "None"})
            calls[-1]["stdout"] = json.dumps(data)
            self.assertNotEqual(self.execute(f'assert_route_tables_ready "{FW_IP}"', calls).returncode, 0)
            for route_index in (0, 1):
                for key, value in (("nextHopIpAddress", "10.0.2.9"), ("nextHopType", "Internet")):
                    calls = tables_calls()[:index + 1]
                    data = json.loads(calls[-1]["stdout"])
                    data["routes"][route_index][key] = value
                    calls[-1]["stdout"] = json.dumps(data)
                    self.assertNotEqual(self.execute(f'assert_route_tables_ready "{FW_IP}"', calls).returncode, 0)
            for key, value in (("id", "foreign"), ("routes", [])):
                calls = tables_calls()[:index + 1]
                data = json.loads(calls[-1]["stdout"])
                data[key] = value
                calls[-1]["stdout"] = json.dumps(data)
                self.assertNotEqual(self.execute(f'assert_route_tables_ready "{FW_IP}"', calls).returncode, 0)
        for index in (3, 5, 9, 11):
            for key, value in (("peeringState", "Disconnected"), ("allowVirtualNetworkAccess", False),
                               ("remoteVirtualNetwork", {"id": "foreign"})):
                calls = tables_calls()[:index + 1]
                data = json.loads(calls[-1]["stdout"])
                data[key] = value
                calls[-1]["stdout"] = json.dumps(data)
                self.assertNotEqual(self.execute(f'assert_route_tables_ready "{FW_IP}"', calls).returncode, 0)

    def test_route_table_gate_rejects_duplicate_foreign_and_child_peering_matches(self):
        list_indices = {
            ("hub", "spokea"): 2,
            ("spokea", "hub"): 4,
            ("hub", "spokeb"): 8,
            ("spokeb", "hub"): 10,
        }
        for (local, remote), index in list_indices.items():
            remote_id = netid(remote, "virtualNetworks", vnet(remote))
            for label, peerings in (
                ("duplicate", [
                    {"name": "one", "remoteVirtualNetwork": {"id": remote_id}},
                    {"name": "two", "remoteVirtualNetwork": {"id": remote_id.swapcase()}},
                ]),
                ("foreign-subscription", [{
                    "name": "foreign",
                    "remoteVirtualNetwork": {"id": remote_id.replace(SUB, "99999999-9999-9999-9999-999999999999")},
                }]),
                ("child-path", [{
                    "name": "child",
                    "remoteVirtualNetwork": {"id": remote_id + "/subnets/snet-foreign"},
                }]),
            ):
                with self.subTest(local=local, remote=remote, label=label):
                    calls = tables_calls()[:index + 1]
                    calls[-1]["stdout"] = json.dumps(peerings)
                    self.assertNotEqual(self.execute(f'assert_route_tables_ready "{FW_IP}"', calls).returncode, 0)

    def test_removal_rejects_attached_nat_or_existing_nat_before_ip_delete(self):
        for zone in ("spokea", "spokeb"):
            for stage in ("nat", "pip"):
                calls = removal_calls(zone, stage)[:2]
                data = json.loads(calls[-1]["stdout"])
                data["natGateway"] = {"id": "still-attached"}
                calls[-1]["stdout"] = json.dumps(data)
                self.assertNotEqual(self.execute(f"assert_spoke_nat_removal {zone} {stage}", calls).returncode, 0)
            calls = removal_calls(zone, "pip")[:3]
            calls[-1]["stdout"] = json.dumps([{"id": netid(zone, "natGateways", f"nat-lzbegin-{zone}-demo123"),
                                               "name": f"nat-lzbegin-{zone}-demo123"}])
            self.assertNotEqual(self.execute(f"assert_spoke_nat_removal {zone} pip", calls).returncode, 0)
        self.assertNotEqual(self.execute("assert_spoke_nat_removal hub detach").returncode, 0)
        self.assertNotEqual(self.execute("assert_spoke_nat_removal spokea unknown").returncode, 0)

    def test_every_safety_lookup_fails_closed_on_api_error_or_malformed_json(self):
        cases = [("firewall_ready_ip", ready_calls()),
                 (f'assert_route_tables_ready "{FW_IP}"', tables_calls())]
        cases += [(f"assert_spoke_nat_removal {zone} {stage}", removal_calls(zone, stage))
                  for zone in ("spokea", "spokeb") for stage in ("detach", "nat", "pip")]
        for command, good_calls in cases:
            for index in range(len(good_calls)):
                for code, output in ((1, ""), (0, "{broken")):
                    with self.subTest(command=command, index=index, code=code):
                        calls = copy.deepcopy(good_calls[:index + 1])
                        calls[-1].update(returncode=code, stdout=output)
                        self.assertNotEqual(self.execute(command, calls).returncode, 0)
