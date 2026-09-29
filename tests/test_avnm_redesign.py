import copy
import json
import subprocess
import unittest

from harness import ROOT, STATE, SUB, call, group, run


BASE = (f"/subscriptions/{SUB}/resourceGroups/{STATE['resourceGroups']['hub']}"
        "/providers/Microsoft.Network/networkManagers/avnm-lzbegin-demo123")
CONFIG = BASE + "/routingConfigurations/rc-lzbegin-spokes-demo123"
FIREWALL_IP = "10.0.2.4"


class IpamVnetTemplateTests(unittest.TestCase):
    def test_compiled_vnet_and_subnets_request_pool_allocations(self):
        result = subprocess.run(
            ["az", "bicep", "build", "--file", "infra/workshop-ipam-vnet.bicep", "--stdout"],
            cwd=ROOT, text=True, capture_output=True, check=True)
        template = json.loads(result.stdout)
        self.assertEqual(template["parameters"]["zone"]["allowedValues"], ["hub", "spokea", "spokeb"])
        vnet = next(resource for resource in template["resources"]
                    if resource["type"] == "Microsoft.Network/virtualNetworks")
        self.assertEqual(vnet["apiVersion"], "2024-05-01")
        self.assertEqual(vnet["properties"]["addressSpace"]["ipamPoolPrefixAllocations"][0]["numberOfIpAddresses"],
                         "4096")
        self.assertNotIn("addressPrefixes", vnet["properties"]["addressSpace"])
        serialized = json.dumps(vnet["properties"]["subnets"])
        self.assertIn("'numberOfIpAddresses', '256'", serialized)
        self.assertIn("'numberOfIpAddresses', '64'", serialized)
        self.assertIn("AzureFirewallSubnet", serialized)
        self.assertIn("defaultOutboundAccess", serialized)
        self.assertIn("networkSecurityGroup", serialized)
        self.assertNotIn("'addressPrefix',", serialized)
        self.assertNotIn("rg-lzbegin-ipam", result.stdout)
        self.assertEqual(set(template["outputs"]), {"vnetId", "vnetPrefixes", "subnets"})


def az(argv, value):
    return call([*argv, "--subscription", SUB], value)


def route_calls():
    result = [
        group("hub"),
        az(["network", "manager", "routing-config", "show", "-g", STATE["resourceGroups"]["hub"],
            "--manager-name", "avnm-lzbegin-demo123", "-n", "rc-lzbegin-spokes-demo123",
            "-o", "json"], {"id": CONFIG, "provisioningState": "Succeeded"}),
    ]
    for zone, remote in (("spokea", "10.20.0.0/16"), ("spokeb", "10.10.0.0/16")):
        rg = STATE["resourceGroups"][zone]
        group_id = BASE + f"/networkGroups/ng-lzbegin-route-{zone}-demo123"
        table_id = (f"/subscriptions/{SUB}/resourceGroups/NetworkManagerRG/providers/"
                    f"Microsoft.Network/routeTables/managed-{zone}")
        result.extend([
            group(zone),
            az(["network", "manager", "routing-config", "rule-collection", "show",
                "-g", STATE["resourceGroups"]["hub"], "--manager-name", "avnm-lzbegin-demo123",
                "--config-name", "rc-lzbegin-spokes-demo123", "-n", zone, "-o", "json"],
               {"id": CONFIG + f"/ruleCollections/{zone}", "provisioningState": "Succeeded",
                "appliesTo": [{"networkGroupId": group_id}]}),
        ])
        for rule, prefix in (("to-other-spoke", remote), ("to-internet", "0.0.0.0/0")):
            result.append(az(
                ["network", "manager", "routing-config", "rule-collection", "rule", "show",
                 "-g", STATE["resourceGroups"]["hub"], "--manager-name", "avnm-lzbegin-demo123",
                 "--config-name", "rc-lzbegin-spokes-demo123", "--collection-name", zone,
                 "-n", rule, "-o", "json"],
                {"id": CONFIG + f"/ruleCollections/{zone}/rules/{rule}",
                 "provisioningState": "Succeeded",
                 "destination": {"type": "AddressPrefix", "destinationAddress": prefix},
                 "nextHop": {"nextHopType": "VirtualAppliance", "nextHopAddress": FIREWALL_IP}}))
        result.extend([
            az(["network", "vnet", "subnet", "show", "-g", rg, "--vnet-name",
                f"vnet-lzbegin-{zone}-demo123", "-n", "snet-workload", "-o", "json"],
               {"id": f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.Network/"
                      f"virtualNetworks/vnet-lzbegin-{zone}-demo123/subnets/snet-workload",
                "routeTable": {"id": table_id}}),
            az(["network", "route-table", "show", "--ids", table_id, "-o", "json"],
               {"id": table_id, "routes": [
                   {"provisioningState": "Succeeded", "addressPrefix": prefix,
                    "nextHopType": "VirtualAppliance", "nextHopIpAddress": FIREWALL_IP}
                   for prefix in (remote, "0.0.0.0/0")]}),
        ])
    return result


class AvnmRoutingSafetyTests(unittest.TestCase):
    def check(self, calls):
        script = ('source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; '
                  'source "$WORKSHOP_ROOT/scripts/workshop-safety.sh"; '
                  'load_run state.json; assert_avnm_routes_ready 10.0.2.4')
        return run(script, calls)

    def test_valid_separate_route_groups_and_attached_tables(self):
        result = self.check(route_calls())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_group_is_rejected_before_inspecting_table(self):
        calls = route_calls()[:4]
        calls[-1] = copy.deepcopy(calls[-1])
        calls[-1]["stdout"] = calls[-1]["stdout"].replace("route-spokea", "route-spokeb")
        result = self.check(calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("routing target", result.stderr)

    def test_missing_default_route_is_not_success(self):
        calls = route_calls()
        calls[-1] = copy.deepcopy(calls[-1])
        calls[-1]["stdout"] = calls[-1]["stdout"].replace('"0.0.0.0/0"', '"10.0.0.0/16"')
        result = self.check(calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Subnet routes", result.stderr)

    def test_incomplete_configuration_is_rejected(self):
        calls = route_calls()[:2]
        calls[-1] = copy.deepcopy(calls[-1])
        calls[-1]["stdout"] = calls[-1]["stdout"].replace("Succeeded", "Updating")
        result = self.check(calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("routing configuration", result.stderr)


class SpokeNatAbsenceTests(unittest.TestCase):
    def check(self, calls):
        script = ('source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; '
                  'source "$WORKSHOP_ROOT/scripts/workshop-safety.sh"; '
                  'load_run state.json; assert_no_spoke_nat')
        return run(script, calls)

    def calls(self, nat=None, pip=None, attachment=None):
        calls = []
        for zone in ("spokea", "spokeb"):
            rg = STATE["resourceGroups"][zone]
            calls.extend([
                group(zone),
                az(["network", "vnet", "subnet", "show", "-g", rg, "--vnet-name",
                    f"vnet-lzbegin-{zone}-demo123", "-n", "snet-workload", "-o", "json"],
                   {"natGateway": {"id": attachment} if zone == "spokea" and attachment else None}),
            ])
            if zone == "spokea" and attachment:
                break
            calls.extend([
                az(["network", "nat", "gateway", "list", "-g", rg, "-o", "json"],
                   [nat] if zone == "spokea" and nat else []),
            ])
            if zone == "spokea" and nat:
                calls.append(az(["network", "public-ip", "list", "-g", rg, "-o", "json"], []))
                break
            calls.extend([
                az(["network", "public-ip", "list", "-g", rg, "-o", "json"],
                   [pip] if zone == "spokea" and pip else []),
            ])
            if zone == "spokea" and pip:
                break
        return calls

    def test_both_spokes_have_no_nat_or_public_ip(self):
        result = self.check(self.calls())
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_spoke_nat_attachment_is_rejected(self):
        result = self.check(self.calls(attachment="/subscriptions/other/natGateway/foreign"))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("still has a NAT", result.stderr)

    def test_spoke_nat_resource_is_rejected(self):
        result = self.check(self.calls(nat={"name": "unexpected"}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected Spoke NAT", result.stderr)

    def test_spoke_public_ip_is_rejected(self):
        result = self.check(self.calls(pip={"name": "unexpected"}))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unexpected Spoke public IP", result.stderr)


if __name__ == "__main__":
    unittest.main()
