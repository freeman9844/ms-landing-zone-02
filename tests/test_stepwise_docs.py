import copy
import json
import re
import unittest
import test_network_docs
from harness import run, account, group, call, ROOT, SUB
from test_network_docs import blocks, DOCS, az, rg, netid, vnet, subnet_args, nic, TAGS, recase_ids, foreign_ids, preparation_calls, avnm_id, routing_group_id, avnm_peerings, connectivity_config, connectivity_config_id, enforced_connectivity_calls
from test_workshop_safety import FW, LAW, FW_IP, ready_calls, effective_admin_call, effective_admin_rule


def support_resource(kind, zone):
    name = f"{kind}-lzbegin-{zone}-demo123"
    types = {"pip": "publicIPAddresses", "nat": "natGateways",
             "nic": "networkInterfaces", "vm": "virtualMachines"}
    provider = "Microsoft.Compute" if kind == "vm" else "Microsoft.Network"
    rid = f"/subscriptions/{SUB}/resourceGroups/{rg(zone)}/providers/{provider}/{types[kind]}/{name}"
    tags = {"runId": "demo123", "workshop": "lz-beginner",
            "environment": "lab", "managedBy": "workshop"}
    obj = {"id": rid, "name": name, "type": f"{provider}/{types[kind]}",
           "tags": tags, "location": "koreacentral", "provisioningState": "Succeeded"}
    if kind == "pip":
        obj.update(sku={"name": "Standard"}, publicIPAllocationMethod="Static",
                   publicIPAddressVersion="IPv4")
    if kind == "nat":
        obj.update(sku={"name": "Standard"}, idleTimeoutInMinutes=4,
                   publicIpAddresses=[{"id": support_resource("pip", "hub")["id"]}])
    if kind == "nic":
        subnet = "snet-management" if zone == "hub" else "snet-workload"
        obj.update(enableIPForwarding=False, ipConfigurations=[{
            "subnet": {"id": netid(zone, "virtualNetworks", vnet(zone)) + f"/subnets/{subnet}"},
            "publicIPAddress": None}])
    if kind == "vm":
        disk_name = name + "_disk1_2628fd89665b46e5a3110aef30244cdf"
        obj.update(
            hardwareProfile={"vmSize": "Standard_B2als_v2"},
            securityProfile={"securityType": "TrustedLaunch",
                             "uefiSettings": {"secureBootEnabled": True, "vTpmEnabled": True}},
            storageProfile={"imageReference": {"publisher": "Canonical", "offer": "ubuntu-24_04-lts",
                                               "sku": "server"},
                            "osDisk": {"name": disk_name,
                                       "managedDisk": {"storageAccountType": "StandardSSD_LRS",
                                                       "id": (f"/subscriptions/{SUB}/resourceGroups/{rg(zone)}"
                                                             f"/providers/Microsoft.Compute/disks/{disk_name}")},
                                       "deleteOption": "Delete"}},
            osProfile={"adminUsername": "workshopadmin", "computerName": f"{zone}-demo123",
                       "linuxConfiguration": {"disablePasswordAuthentication": True,
                                              "provisionVMAgent": True,
                                              "ssh": {"publicKeys": [{"keyData": "fixture-public-key"}]}}},
            networkProfile={"networkInterfaces": [{"id": support_resource("nic", zone)["id"],
                                                    "deleteOption": "Delete"}]},
            diagnosticsProfile={"bootDiagnostics": {"enabled": True}})
    return obj


def support_read(kind, zone, data=None):
    commands = {"pip": ["network", "public-ip"], "nat": ["network", "nat", "gateway"],
                "nic": ["network", "nic"], "vm": ["vm"]}
    return az([*commands[kind], "show", "-g", rg(zone),
               "-n", f"{kind}-lzbegin-{zone}-demo123", "-o", "json"],
              support_resource(kind, zone) if data is None else data)


def support_verification_calls():
    calls = []
    for zone, kinds in (("hub", ("pip", "nat", "nic", "vm")),
                        ("spokea", ("nic", "vm")), ("spokeb", ("nic", "vm"))):
        inventory = [support_resource(kind, zone) for kind in kinds]
        inventory.append({"name": support_resource("vm", zone)["storageProfile"]["osDisk"]["name"],
                          "type": "Microsoft.Compute/disks"})
        for kind in kinds:
            calls.append(az(["resource", "list", "--resource-group", rg(zone), "-o", "json"], inventory))
            calls.append(support_read(kind, zone))
    return calls


def support_cases():
    cases = {
        "support-preview": [],
        "support-deploy": [
            az(["network", "public-ip", "create", "-g", rg("hub"), "-n", "pip-lzbegin-hub-demo123",
                "-l", "koreacentral", "--sku", "Standard", "--allocation-method", "Static",
                "--version", "IPv4", *TAGS, "-o", "json"]),
            az(["network", "nat", "gateway", "create", "-g", rg("hub"),
                "-n", "nat-lzbegin-hub-demo123", "-l", "koreacentral",
                "--public-ip-addresses", "pip-lzbegin-hub-demo123", "--idle-timeout", "4",
                "--sku", "Standard", *TAGS, "-o", "json"]),
        ],
        "attach-nat-hub": support_verification_calls() + [az(["network", "vnet", "subnet", "update", *subnet_args("hub"),
                              "--nat-gateway", "nat-lzbegin-hub-demo123", "-o", "json"])],
        "read-vm-ips": [nic("hub", "172.20.0.4"), nic("spokea", "172.20.16.4"), nic("spokeb", "172.20.32.4")],
    }
    for zone in ("hub", "spokea", "spokeb"):
        subnet = "snet-management" if zone == "hub" else "snet-workload"
        name = f"vm-lzbegin-{zone}-demo123"
        calls = cases["support-deploy"]
        calls.extend([
            az(["network", "nic", "create", "-g", rg(zone), "-n", f"nic-lzbegin-{zone}-demo123",
                "-l", "koreacentral", "--subnet",
                netid(zone, "virtualNetworks", vnet(zone)) + f"/subnets/{subnet}",
                "--ip-forwarding", "false", *TAGS, "-o", "json"]),
            az(["vm", "create", "-g", rg(zone), "-n", name, "-l", "koreacentral",
                "--nics", f"nic-lzbegin-{zone}-demo123",
                "--image", "Canonical:ubuntu-24_04-lts:server:latest",
                "--size", "Standard_B2als_v2", "--admin-username", "workshopadmin",
                "--authentication-type", "ssh", "--ssh-key-values", "fixture-public-key",
                "--computer-name", f"{zone}-demo123", "--storage-sku", "StandardSSD_LRS",
                "--os-disk-delete-option", "Delete", "--nic-delete-option", "Delete",
                "--security-type", "TrustedLaunch", "--enable-secure-boot", "true",
                "--enable-vtpm", "true", "--enable-agent", "true", *TAGS, "-o", "json"]),
            az(["vm", "boot-diagnostics", "enable", "-g", rg(zone), "-n", name, "-o", "json"]),
        ])
    return cases


def diagnostic_ids():
    return [az(["network", "firewall", "show", "-g", rg("hub"), "-n", "fw-lzbegin-demo123",
                "--query", "id", "-o", "tsv"], FW),
            az(["monitor", "log-analytics", "workspace", "show", "-g", rg("hub"), "-n", "log-lzbegin-demo123",
                "--query", "id", "-o", "tsv"], LAW)]


def firewall_cases():
    base = ["network", "firewall", "policy", "rule-collection-group"]
    collection = [*base, "collection", "add-filter-collection", "-g", rg("hub"),
                  "--policy-name", "fwpol-lzbegin-demo123", "--rcg-name", "workshop"]
    cases = {
        "register-logs": [az(["provider", "register", "--namespace", "Microsoft.OperationalInsights", "--wait"])],
        "install-firewall-cli": [call(["extension", "add", "--name", "azure-firewall", "--version", "2.2.1",
                                     "--upgrade", "--yes"])],
        "install-logs-cli": [call(["extension", "add", "--name", "log-analytics", "--upgrade", "--yes"])],
        "install-avnm-routing-cli": [call(["extension", "add", "--name", "virtual-network-manager",
                                           "--version", "3.0.2", "--upgrade", "--yes"])],
        "firewall-workspace": [az(["monitor", "log-analytics", "workspace", "create", "-g", rg("hub"),
                                                "-n", "log-lzbegin-demo123", "-l", "koreacentral", "--sku", "PerGB2018",
                                                "--retention-time", "30", *TAGS, "-o", "json"])],
        "firewall-public-ip": [az(["network", "public-ip", "create", "-g", rg("hub"),
                                                "-n", "pip-lzbegin-fw-demo123", "-l", "koreacentral",
                                                "--sku", "Standard", "--allocation-method", "Static", "--version", "IPv4",
                                                *TAGS, "-o", "json"])],
        "firewall-policy": [az(["network", "firewall", "policy", "create", "-g", rg("hub"),
                                             "-n", "fwpol-lzbegin-demo123", "-l", "koreacentral", "--sku", "Standard",
                                             "--threat-intel-mode", "Alert", *TAGS, "-o", "json"])],
        "firewall-create": [az(["network", "firewall", "create", "-g", rg("hub"),
                                             "-n", "fw-lzbegin-demo123", "-l", "koreacentral", "--sku", "AZFW_VNet",
                                             "--tier", "Standard", "--firewall-policy", "fwpol-lzbegin-demo123",
                                             *TAGS, "-o", "json"])],
        "firewall-ip-config": [az(["network", "firewall", "ip-config", "create", "-g", rg("hub"),
                                                "--firewall-name", "fw-lzbegin-demo123", "-n", "primary",
                                                "--public-ip-address", "pip-lzbegin-fw-demo123",
                                                "--vnet-name", vnet("hub"), "-o", "json"])],
        "inspect-firewall": [az(["network", "firewall", "show", "-g", rg("hub"),
                                               "-n", "fw-lzbegin-demo123", "-o", "json"],
                                {"id": FW, "provisioningState": "Succeeded",
                                 "firewallPolicy": {"id": netid("hub", "firewallPolicies", "fwpol-lzbegin-demo123")},
                                 "ipConfigurations": [{"privateIPAddress": FW_IP}]})],
        "firewall-rule-group": [az([*base, "create", "-g", rg("hub"),
                                                  "--policy-name", "fwpol-lzbegin-demo123",
                                                  "-n", "workshop", "--priority", "200", "-o", "json"])],
        "firewall-management-rule": [az([*collection, "-n", "management", "--collection-priority", "100",
                                                       "--action", "Allow", "--rule-name", "azure-management",
                                                       "--rule-type", "NetworkRule", "--ip-protocols", "TCP",
                                                       "--source-addresses", "172.20.16.0/24", "172.20.32.0/24",
                                                       "--destination-addresses", "AzureCloud", "--destination-ports", "443",
                                                       "-o", "json"])],
        "firewall-http-rule": [az([*collection, "-n", "lab-http", "--collection-priority", "200", "--action", "Allow",
                                   "--rule-name", "spokea-to-spokeb", "--rule-type", "NetworkRule",
                                   "--ip-protocols", "TCP", "--source-addresses", "172.20.16.0/24",
                                   "--destination-addresses", "172.20.32.0/24", "--destination-ports", "8080", "-o", "json"])],
        "firewall-egress-rule": [az([*collection, "-n", "egress-check", "--collection-priority", "300",
                                                   "--action", "Allow", "--rule-name", "public-ip-check",
                                                   "--rule-type", "ApplicationRule", "--source-addresses",
                                                   "172.20.16.0/24", "172.20.32.0/24", "--protocols", "Https=443",
                                                   "--target-fqdns", "api.ipify.org", "-o", "json"])],
        "firewall-diagnostics": [
            *diagnostic_ids(),
            az(["monitor", "diagnostic-settings", "categories", "list", "--resource", FW, "-o", "json"],
               {"value": [{"name": "AZFWNetworkRule"}, {"name": "AZFWApplicationRule"}]}),
            az(["monitor", "diagnostic-settings", "create", "--name", "workshop", "--resource", FW,
                "--workspace", LAW, "--export-to-resource-specific", "true", "--logs",
                '[{"category":"AZFWNetworkRule","enabled":true},{"category":"AZFWApplicationRule","enabled":true}]',
                "-o", "json"])],
    }
    return cases


def routing_cases():
    manager = avnm_id()
    config = manager + "/routingConfigurations/rc-lzbegin-spokes-demo123"
    cases = {
        "routing-config-create": [az(["network", "manager", "routing-config", "create", "-g", rg("hub"),
            "--manager-name", "avnm-lzbegin-demo123", "-n", "rc-lzbegin-spokes-demo123",
            "--description", "Spoke routes via Hub Firewall", "-o", "json"],
           {"id": config})],
        "inspect-avnm-routing-subnets": [az([
            "rest", "--method", "post", "--url", avnm_id() +
            "/listDeploymentStatus?api-version=2025-05-01",
            "--body", '{"deploymentTypes":["Routing"],"regions":["koreacentral"]}',
            "-o", "json"], [{"deploymentType": "Routing", "region": "koreacentral",
                           "commitTime": "2026-01-01T00:00:00Z", "deploymentStatus": "Deployed",
                           "configurationIds": [config]}])],
    }
    for local, remote in (("hub", "spokea"), ("spokea", "hub"), ("hub", "spokeb"), ("spokeb", "hub")):
        remote_id = netid(remote, "virtualNetworks", vnet(remote))
        generated = f"avnm-{local}-{remote}"
        cases[f"forward-{local}-to-{remote}"] = [
            *(ready_calls() if (local, remote) == ("hub", "spokea") else []),
            az(["network", "vnet", "show", "-g", rg(remote), "-n", vnet(remote), "--query", "id", "-o", "tsv"],
               remote_id),
            az(["network", "vnet", "peering", "list", "-g", rg(local), "--vnet-name", vnet(local), "-o", "json"], [{
                "name": generated,
                "remoteVirtualNetwork": {"id": remote_id},
            }]),
            az(["network", "vnet", "peering", "show", "-g", rg(local), "--vnet-name", vnet(local),
                "-n", generated, "-o", "json"], {"peeringState": "Connected",
                                                 "remoteVirtualNetwork": {"id": remote_id}}),
            az(["network", "vnet", "peering", "update", "-g", rg(local), "--vnet-name", vnet(local),
                "-n", generated, "--set", "allowForwardedTraffic=true", "-o", "json"]),
            az(["network", "vnet", "peering", "show", "-g", rg(local), "--vnet-name", vnet(local),
                "-n", generated, "-o", "json"], {"peeringState": "Connected",
                                                 "allowForwardedTraffic": True,
                                                 "remoteVirtualNetwork": {"id": remote_id}})]
    for zone, group in (("spokea", routing_group_id("spokea")), ("spokeb", routing_group_id("spokeb"))):
        collection = config + f"/ruleCollections/{zone}"
        applies = json.dumps([{"networkGroupId": group}], separators=(",", ":"))
        cases[f"routing-collection-{zone}"] = [az([
            "network", "manager", "routing-config", "rule-collection", "create", "-g", rg("hub"),
            "--manager-name", "avnm-lzbegin-demo123", "--config-name", "rc-lzbegin-spokes-demo123",
            "-n", zone, "--applies-to", applies, "--disable-bgp-route", "true", "-o", "json"],
            {"id": collection, "appliesTo": [{"networkGroupId": group}]})]
        for kind, rule, prefix in (("other", "to-other-spoke", "172.20.32.0/20" if zone == "spokea" else "172.20.16.0/20"),
                                   ("internet", "to-internet", "0.0.0.0/0")):
            dest = json.dumps({"type": "AddressPrefix", "destination_address": prefix}, separators=(",", ":"))
            hop = json.dumps({"next_hop_type": "VirtualAppliance", "next_hop_address": FW_IP}, separators=(",", ":"))
            cases[f"routing-rule-{zone}-{kind}"] = [*ready_calls(), az([
                "network", "manager", "routing-config", "rule-collection", "rule", "create",
                "-g", rg("hub"), "--manager-name", "avnm-lzbegin-demo123",
                "--config-name", "rc-lzbegin-spokes-demo123", "--collection-name", zone, "-n", rule,
                "--destination", dest, "--next-hop", hop, "-o", "json"],
                {"id": collection + "/rules/" + rule,
                 "destination": {"type": "AddressPrefix", "destinationAddress": prefix},
                 "nextHop": {"nextHopType": "VirtualAppliance", "nextHopAddress": FW_IP}})]
    for name, action in (("firewall-deny", "Deny"), ("firewall-restore", "Allow")):
        prerequisites = [*effective_route_calls(), *no_spoke_nat_calls()] if action == "Deny" else []
        policy = json.loads(ready_calls()[-1]["stdout"])
        next(collection for collection in policy["ruleCollections"]
             if collection["name"] == "lab-http")["action"]["type"] = (
                 "Allow" if action == "Deny" else "Deny")
        cases[name] = [*prerequisites, az(["network", "firewall", "policy", "rule-collection-group", "show", "-g", rg("hub"),
                           "--policy-name", "fwpol-lzbegin-demo123", "-n", "workshop", "-o", "json"],
                          policy),
                       az(["network", "firewall", "policy", "rule-collection-group", "update", "-g", rg("hub"),
                           "--policy-name", "fwpol-lzbegin-demo123", "-n", "workshop",
                           "--set", f"ruleCollections[1].action.type={action}", "-o", "json"])]
    return cases


def route_configuration_calls():
    return routing_cases()["routing-config-create"]


def routing_group_calls():
    calls = []
    for zone in ("spokea", "spokeb"):
        group_id = routing_group_id(zone)
        calls += [
            az(["network", "manager", "group", "show", "--ids", group_id, "-o", "json"],
               {"id": group_id, "provisioningState": "Succeeded"}),
            az(["network", "manager", "group", "static-member", "list",
                "--network-group", f"ng-lzbegin-route-{zone}-demo123",
                "--network-manager", "avnm-lzbegin-demo123", "--resource-group", rg("hub"),
                "-o", "json"], [{"resourceId": netid(zone, "virtualNetworks", vnet(zone)),
                                "provisioningState": "Succeeded"}])]
    return calls


def routing_commit_calls():
    calls = routing_group_calls()
    for zone in ("spokea", "spokeb"):
        calls.extend([
            group(zone),
            az(["network", "vnet", "subnet", "show", *subnet_args(zone), "-o", "json"],
               {"id": netid(zone, "virtualNetworks", vnet(zone) + "/subnets/snet-workload"),
                "routeTable": None, "natGateway": None}),
        ])
    calls.append(az(["network", "manager", "post-commit",
                     "--network-manager-name", "avnm-lzbegin-demo123",
                     "--commit-type", "Routing", "--configuration-ids",
                     avnm_id() + "/routingConfigurations/rc-lzbegin-spokes-demo123",
                     "--target-locations", "koreacentral", "--resource-group", rg("hub"),
                     "-o", "json"]))
    return calls


def forwarding_check_calls():
    return [entry for zone in ("hub", "spokea", "spokeb")
            for entry in (group(zone),
                          az(["network", "vnet", "peering", "list", "-g", rg(zone),
                              "--vnet-name", vnet(zone), "-o", "json"],
                             avnm_peerings(zone, forwarded=True)))]


def enforcement_cases():
    config = connectivity_config()
    updated = copy.deepcopy(enforced_connectivity_calls()[1])
    return {
        "enforce-peering": [
            *forwarding_check_calls(),
            az(["network", "manager", "connect-config", "show", "-g", rg("hub"),
                "--network-manager-name", "avnm-lzbegin-demo123",
                "--configuration-name", "cc-lzbegin-hub-spoke-demo123", "-o", "json"], config),
            az(["network", "manager", "connect-config", "update", "-g", rg("hub"),
                "--network-manager-name", "avnm-lzbegin-demo123",
                "--configuration-name", "cc-lzbegin-hub-spoke-demo123",
                "--connect-capabilities",
                '{"connectedGroupAddressOverlap":"Allowed","connectedGroupPrivateEndpointsScale":"Standard","peeringEnforcement":"Enforced"}',
                "-o", "json"], json.loads(updated["stdout"])),
            updated,
        ],
        "commit-enforced-connectivity": [
            *forwarding_check_calls(),
            updated,
            az(["network", "manager", "post-commit", "-g", rg("hub"),
                "--network-manager-name", "avnm-lzbegin-demo123",
                "--commit-type", "Connectivity", "--configuration-ids",
                connectivity_config_id(), "--target-locations", "koreacentral"]),
        ],
        "inspect-enforced-connectivity": enforced_connectivity_calls(),
    }


def no_spoke_nat_calls():
    calls = []
    for zone in ("spokea", "spokeb"):
        calls += [group(zone),
            az(["network", "vnet", "subnet", "show", *subnet_args(zone), "-o", "json"], {"natGateway": None}),
            az(["network", "nat", "gateway", "list", "-g", rg(zone), "-o", "json"], []),
            az(["network", "public-ip", "list", "-g", rg(zone), "-o", "json"], [])]
    return calls


def deployed_route_calls():
    manager = avnm_id()
    config = manager + "/routingConfigurations/rc-lzbegin-spokes-demo123"
    calls = [
        group("hub"),
        az(["network", "manager", "routing-config", "show", "-g", rg("hub"),
            "--manager-name", "avnm-lzbegin-demo123", "-n", "rc-lzbegin-spokes-demo123",
            "-o", "json"], {"id": config, "provisioningState": "Succeeded",
                           "routeTableUsageMode": "ManagedOnly"}),
    ]
    for zone, remote in (("spokea", "172.20.32.0/20"), ("spokeb", "172.20.16.0/20")):
        collection = config + f"/ruleCollections/{zone}"
        calls += [
            group(zone),
            az(["network", "manager", "routing-config", "rule-collection", "show",
                "-g", rg("hub"), "--manager-name", "avnm-lzbegin-demo123",
                "--config-name", "rc-lzbegin-spokes-demo123", "-n", zone, "-o", "json"],
               {"id": collection, "provisioningState": "Succeeded",
                "appliesTo": [{"networkGroupId": routing_group_id(zone)}]})]
        for rule, prefix in (("to-other-spoke", remote), ("to-internet", "0.0.0.0/0")):
            calls.append(az([
                "network", "manager", "routing-config", "rule-collection", "rule", "show",
                "-g", rg("hub"), "--manager-name", "avnm-lzbegin-demo123",
                "--config-name", "rc-lzbegin-spokes-demo123", "--collection-name", zone,
                "-n", rule, "-o", "json"],
                {"id": collection + f"/rules/{rule}", "provisioningState": "Succeeded",
                 "destination": {"type": "AddressPrefix", "destinationAddress": prefix},
                 "nextHop": {"nextHopType": "VirtualAppliance", "nextHopAddress": FW_IP}}))
        table = netid(zone, "routeTables", "avnm-managed-" + zone)
        calls += [
            az(["network", "vnet", "subnet", "show", *subnet_args(zone), "-o", "json"],
               {"id": netid(zone, "virtualNetworks", vnet(zone) + "/subnets/snet-workload"),
                "routeTable": {"id": table}}),
            az(["network", "route-table", "show", "--ids", table, "-o", "json"],
               {"id": table, "routes": [
                   {"provisioningState": "Succeeded", "addressPrefix": prefix,
                    "nextHopType": "VirtualAppliance", "nextHopIpAddress": FW_IP}
                   for prefix in (remote, "0.0.0.0/0")]})]
    return calls


def effective_route_calls():
    calls = [*ready_calls(), *deployed_route_calls()]
    for zone, remote in (("spokea", "172.20.32.0/20"), ("spokeb", "172.20.16.0/20")):
        calls.append(az(["network", "nic", "show-effective-route-table", "-g", rg(zone),
                         "-n", "nic-lzbegin-" + zone + "-demo123", "-o", "json"],
                        {"value": [{"state": "Active", "addressPrefix": [prefix],
                                    "nextHopType": "VirtualAppliance", "nextHopIpAddress": [FW_IP]}
                                   for prefix in (remote, "0.0.0.0/0")]}))
    return calls


def security_rule(zone, name, source, destination, access, priority):
    return {
        "id": avnm_id() + f"/securityAdminConfigurations/sc-lzbegin-http-demo123/ruleCollections/{zone}/rules/{name}",
        "provisioningState": "Succeeded", "kind": "Custom", "access": access, "priority": priority,
        "direction": "Inbound", "protocol": "Tcp", "sourcePortRanges": ["0-65535"],
        "destinationPortRanges": ["8080"],
        "sources": [{"addressPrefixType": "IPPrefix", "addressPrefix": source + "/32"}],
        "destinations": [{"addressPrefixType": "IPPrefix", "addressPrefix": destination + "/32"}],
    }


def admin_rule_checks(stage="baseline"):
    base = ["network", "manager", "security-admin-config"]
    options = ["-g", rg("hub"), "--network-manager-name", "avnm-lzbegin-demo123",
               "--configuration-name", "sc-lzbegin-http-demo123"]
    config = avnm_id() + "/securityAdminConfigurations/sc-lzbegin-http-demo123"
    calls = [az([*base, "show", *options, "-o", "json"],
                {"id": config, "provisioningState": "Succeeded"})]
    for zone, rules in (
        ("spokea", [("hub-to-a", "172.20.0.4", "172.20.16.4", "AlwaysAllow", 200)]
         + ([("deny-hub-to-a", "172.20.0.4", "172.20.16.4", "Deny", 100)] if stage == "denied" else [])),
        ("spokeb", [("hub-to-b", "172.20.0.4", "172.20.32.4", "AlwaysAllow", 210),
                     ("a-to-b", "172.20.16.4", "172.20.32.4", "AlwaysAllow", 220)]),
    ):
        calls.append(az([*base, "rule-collection", "show", *options, "--rule-collection-name",
                         zone, "-o", "json"],
                        {"id": config + "/ruleCollections/" + zone, "provisioningState": "Succeeded",
                         "appliesToGroups": [{"networkGroupId": routing_group_id(zone)}]}))
        calls.append(az([*base, "rule-collection", "rule", "list", *options,
                         "--rule-collection-name", zone, "-o", "json"],
                        [{"id": config + f"/ruleCollections/{zone}/rules/{item[0]}"} for item in rules]))
        for name, source, dest, access, priority in rules:
            calls.append(az([*base, "rule-collection", "rule", "show", *options,
                             "--rule-collection-name", zone, "--rule-name", name, "-o", "json"],
                            security_rule(zone, name, source, dest, access, priority)))
    return calls


def security_cases():
    base = ["network", "manager", "security-admin-config"]
    options = ["-g", rg("hub"), "--network-manager-name", "avnm-lzbegin-demo123",
               "--configuration-name", "sc-lzbegin-http-demo123"]
    config = avnm_id() + "/securityAdminConfigurations/sc-lzbegin-http-demo123"
    cases = {
        "security-config": [az([*base, "create", *options, "--description",
                                "Workshop TCP 8080 on spoke VMs", "--apply-on", "None", "-o", "json"])],
    }
    for zone in ("spokea", "spokeb"):
        suffix = "" if zone == "spokea" else "-b"
        cases["security-collection" + suffix] = [az([
            *base, "rule-collection", "create", *options, "--rule-collection-name", zone,
            "--applies-to-groups", "network-group-id=" + routing_group_id(zone), "-o", "json"])]
    for step, zone, rule, source, dest, access, priority in (
        ("allow-hub-spokea", "spokea", "hub-to-a", "172.20.0.4", "172.20.16.4", "AlwaysAllow", 200),
        ("allow-hub-spokeb", "spokeb", "hub-to-b", "172.20.0.4", "172.20.32.4", "AlwaysAllow", 210),
        ("allow-spokea-spokeb", "spokeb", "a-to-b", "172.20.16.4", "172.20.32.4", "AlwaysAllow", 220),
    ):
        cases[step] = [az([*base, "rule-collection", "rule", "create", *options,
                           "--rule-collection-name", zone, "--rule-name", rule,
                           "--priority", str(priority), "--direction", "Inbound",
                           "--access", access, "--protocol", "Tcp",
                           "--sources", f"address-prefix={source}/32", "address-prefix-type=IPPrefix",
                           "--source-port-ranges", "0-65535", "--destinations",
                           f"address-prefix={dest}/32", "address-prefix-type=IPPrefix",
                           "--dest-port-ranges", "8080", "-o", "json"])]
    for step in ("security-deploy",):
        cases[step] = [az(["network", "manager", "post-commit", "-g", rg("hub"),
                           "--network-manager-name", "avnm-lzbegin-demo123", "--commit-type",
                           "SecurityAdmin", "--configuration-ids", config,
                           "--target-locations", "koreacentral", "-o", "json"])]
    cases["inspect-security-rules"] = admin_rule_checks("baseline")
    return cases


def verifier(script, args, code=0):
    expected = " ".join([script, "state.json", *args])
    return f'''bash() {{
  [[ "$*" == "{expected}" ]] || return 99
  printf 'VERIFY:{expected}\\n'
  return {code}
}}
'''


class StepwiseDocsTests(unittest.TestCase):
    keyfile = {".workshop-keys/demo123/id_ed25519.pub": "fixture-public-key"}

    def test_module_05_reconnect_clears_old_ips_and_names_read_only_recovery_steps(self):
        steps = blocks(DOCS[5])
        intro = DOCS[5].read_text().split("## 1. VM 배포 전", 1)[0]
        self.assertIn("read-vm-ips", intro)
        self.assertIn("admin-flow-check", intro)
        script = ('export STATE_FILE=state.json\n'
                  'hub_ip=stale; a_ip=stale; b_ip=stale\n'
                  'check_admin_flow() { :; }\n' +
                  steps["prepare-05"] +
                  '\n[[ ! -v hub_ip && ! -v a_ip && ! -v b_ip ]] && '
                  '! declare -F check_admin_flow >/dev/null')
        result = run(script, preparation_calls(5))
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_module_05_reconnected_shell_can_reload_ips_and_verify_rule(self):
        steps = blocks(DOCS[5])
        script = ('export STATE_FILE=state.json\n' + steps["prepare-05"] + '\n' +
                  steps["read-vm-ips"] + '\n' + steps["allow-hub-spokea"] + '\n' +
                  steps["admin-flow-check"] + '\n' + steps["verify-admin-allow-a"])
        calls = (preparation_calls(5) + support_cases()["read-vm-ips"] +
                 security_cases()["allow-hub-spokea"] +
                 [effective_admin_call("spokea", "hub-to-a", "172.20.0.4",
                                       "172.20.16.4", "AlwaysAllow")])
        result = run(script, calls)
        self.assertEqual(result.returncode, 0, result.stderr)

    def execute(self, module, name, calls=(), input_text=None, files=None, prefix="", state=test_network_docs.STATE):
        steps = blocks(DOCS[module])
        if (module, name) == (5, "vm-route-gate"):
            calls = [*enforced_connectivity_calls(), *calls]
        if module == 5 and name in ("support-preview", "support-deploy"):
            prefix += "check_vm_network() { :; }\n"
        if module == 5 and name in ("allow-hub-spokea", "allow-hub-spokeb",
                                     "allow-spokea-spokeb",
                                     "inspect-security-rules"):
            prefix += 'hub_ip=172.20.0.4; a_ip=172.20.16.4; b_ip=172.20.32.4\n'
        if module == 5 and name.startswith("verify-admin-") and name not in (
            "verify-admin-http-baseline", "verify-admin-http-denied", "verify-admin-http-restored"):
            prefix += steps["admin-flow-check"] + "\n"
            prefix += 'hub_ip=172.20.0.4; a_ip=172.20.16.4; b_ip=172.20.32.4\n'
        return test_network_docs.NetworkDocsTests.execute(
            self, module, name, calls, input_text, files, prefix, state)

    def test_module_05_execution_blocks_do_not_chain_with_and(self):
        for name, script in blocks(DOCS[5]).items():
            with self.subTest(step=name):
                self.assertNotIn("&&", script)

    def test_only_module_06_has_a_deny_restore_exercise(self):
        steps05 = blocks(DOCS[5])
        for name in ("deny-hub", "security-deploy-deny", "verify-admin-deny",
                     "verify-admin-http-denied", "security-undeploy-for-restore",
                     "restore-hub", "security-deploy-restore", "verify-admin-restored",
                     "verify-admin-http-restored"):
            self.assertNotIn(name, steps05)
        self.assertIn("inspect-security-rules", steps05)
        self.assertIn("verify-admin-http-baseline", steps05)
        steps06 = blocks(DOCS[6])
        for name in ("firewall-deny", "verify-denied", "firewall-restore", "verify-restored"):
            self.assertIn(name, steps06)

    def test_module_06_uses_one_comprehensive_baseline_instead_of_separate_route_checks(self):
        steps = blocks(DOCS[6])
        self.assertNotIn("validate-avnm-subnets", steps)
        self.assertNotIn("validate-effective-nic-routes", steps)
        self.assertIn("verify-allowed", steps)
        self.assertIn("validate_effective_nic_routes", steps["firewall-deny"])
        self.assertIn("assert_no_spoke_nat", steps["firewall-deny"])

    def test_firewall_deny_validates_routes_in_a_fresh_prepared_shell(self):
        calls = routing_cases()["firewall-deny"]
        self.assertEqual(self.execute(6, "firewall-deny", calls).returncode, 0)
        invalid = copy.deepcopy(calls[:len(effective_route_calls())])
        routes = json.loads(invalid[-1]["stdout"])
        routes["value"][0]["nextHopIpAddress"] = ["172.20.1.5"]
        invalid[-1]["stdout"] = json.dumps(routes)
        self.assertNotEqual(self.execute(6, "firewall-deny", invalid).returncode, 0)

    def test_module_05_uses_hub_nat_update_result_without_duplicate_inspection(self):
        steps = blocks(DOCS[5])
        self.assertIn("attach-nat-hub", steps)
        self.assertIn("vm-route-gate", steps)
        self.assertNotIn("inspect-nat-hub", steps)
        self.assertNotIn("inspect-no-spoke-nat", steps)
        self.assertIn("assert_no_spoke_nat", steps["vm-route-gate"])
        self.assertIn("assert_no_spoke_nat", blocks(DOCS[6])["firewall-deny"])

    def test_module_06_allowed_result_example_covers_route_http_and_fresh_log(self):
        doc = DOCS[6].read_text()
        example = doc.split("<!-- exec:verify-allowed -->", 1)[1].split("## 4.", 1)[0]
        for evidence in ("Waiting for current flow logs", "VirtualAppliance",
                         "VNetPeering", "effective AVNM rule", "PASS: HTTP spokeb",
                         '"Action": "Allow"', '"SourceIp": "<Spoke A 사설 IP>"',
                         '"DestinationIp": "<Spoke B 사설 IP>"',
                         "PASS: matching Firewall Allow evidence found.",
                         "PASS: extension allowed"):
            with self.subTest(evidence=evidence):
                self.assertIn(evidence, example)

    def test_ordinary_actions_check_ownership_once_for_a_prepared_session(self):
        cases = dict(self.cases())
        cases[3] = test_network_docs.connectivity_cases()
        for module, names in (
            (3, ("avnm-ready", "network-group-create", "member-spokea",
                 "member-spokeb", "connectivity-config-create",
                 "connectivity-commit", "inspect-avnm-peerings-hub")),
            (4, ("firewall-workspace", "firewall-public-ip", "firewall-http-rule")),
            (5, ("attach-nat-hub", "security-config", "security-collection")),
            (6, ()),
        ):
            with self.subTest(module=module):
                steps = blocks(DOCS[module])
                script = 'export STATE_FILE=state.json\n'
                script += " &&\n".join([steps[f"prepare-{module:02}"], *(steps[name] for name in names)])
                calls = preparation_calls(module)
                for name in names:
                    calls.extend(cases[module][name])
                result = run(script, calls, files=self.keyfile)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_preparation_rejects_foreign_groups_and_lookup_failures(self):
        for module, action in ((3, "avnm-ready"), (4, "firewall-workspace"),
                               (5, "support-deploy"), (6, "verify-allowed")):
            steps = blocks(DOCS[module])
            for index in (1, 2, 3):
                for failure in ("foreign", "api-error"):
                    with self.subTest(module=module, group=index, failure=failure):
                        calls = preparation_calls(module)[:index + 1]
                        if failure == "foreign":
                            data = json.loads(calls[-1]["stdout"])
                            data["tags"]["runId"] = "another-run"
                            calls[-1]["stdout"] = json.dumps(data)
                        else:
                            calls[-1].update(returncode=1, stdout="", stderr="Forbidden")
                        script = 'export STATE_FILE=state.json\n'
                        script += steps[f"prepare-{module:02}"] + " &&\n" + steps[action]
                        script += '\nstatus=$?\nprintf "SHELL_ALIVE\\n"\nexit "$status"'
                        result = run(script, calls, files=self.keyfile, input_text="CREATE\nFIREWALL\n")
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("SHELL_ALIVE", result.stdout)
                        self.assertIn("Ownership mismatch" if failure == "foreign" else "Forbidden", result.stderr)

    def test_workspace_get_lowercase_response_does_not_block_diagnostics_creation(self):
        calls = firewall_cases()["firewall-diagnostics"]
        calls[1]["stdout"] = LAW.lower()
        workspace_index = calls[-1]["argv"].index("--workspace") + 1
        calls[-1]["argv"][workspace_index] = LAW.lower()
        result = self.execute(4, "firewall-diagnostics", calls)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_diagnostics_accepts_lowercase_workspace_discovery_and_mixedcase_reference(self):
        for name in ("firewall-diagnostics",):
            for transform in (str.lower, str.swapcase):
                with self.subTest(step=name, casing=transform.__name__):
                    calls = recase_ids(firewall_cases()[name], transform)
                    if name.startswith("inspect-"):
                        setting = json.loads(calls[-1]["stdout"])
                        setting["workspaceId"] = LAW.swapcase() if transform == str.lower else LAW.lower()
                        calls[-1]["stdout"] = json.dumps(setting)
                    result = self.execute(4, name, calls)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_reference_mismatches_remain_errors_not_suffix_matches(self):
        for bad in foreign_ids(LAW):
            calls = firewall_cases()["firewall-diagnostics"]
            calls[1]["stdout"] = bad.lower()
            self.assertNotEqual(self.execute(4, "firewall-diagnostics", calls[:2]).returncode, 0)

    def cases(self):
        return ((4, firewall_cases()
                 | {k: v for k, v in routing_cases().items() if k.startswith("forward-")
                    or k.startswith("routing-collection-") or k.startswith("routing-rule-")
                    }
                 | enforcement_cases()),
                (5, support_cases() | security_cases()),
                (6, {k: v for k, v in routing_cases().items() if k.startswith("firewall-")}))

    def test_each_action_runs_after_only_preparation_with_explicit_targets(self):
        for module, cases in self.cases():
            for name, calls in cases.items():
                with self.subTest(module=module, step=name):
                    result = self.execute(module, name, calls, files=self.keyfile,
                                          input_text="CREATE\n" if name == "support-deploy" else "FIREWALL\n")
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_all_four_forwarding_updates_precede_enforcement_and_redeployment(self):
        steps = blocks(DOCS[4])
        names = [f"forward-{local}-to-{remote}" for local, remote in (
            ("hub", "spokea"), ("spokea", "hub"), ("hub", "spokeb"), ("spokeb", "hub"))]
        names += ["enforce-peering", "commit-enforced-connectivity", "inspect-enforced-connectivity"]
        script = 'export STATE_FILE=state.json\n' + steps["prepare-04"] + '\n'
        script += "\n".join(f'{steps[name]}\n[[ $? == 0 ]] || exit 1' for name in names)
        calls = preparation_calls(4)
        for name in names:
            calls.extend(routing_cases().get(name, enforcement_cases().get(name, [])))
        result = run(script, calls)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_enforcement_cannot_update_or_commit_until_all_four_peerings_forward(self):
        for name in ("enforce-peering", "commit-enforced-connectivity"):
            for index in (1, 3, 5):
                with self.subTest(action=name, peering_index=index):
                    calls = copy.deepcopy(enforcement_cases()[name][:index + 1])
                    peerings = json.loads(calls[-1]["stdout"])
                    peerings[-1]["allowForwardedTraffic"] = False
                    calls[-1]["stdout"] = json.dumps(peerings)
                    self.assertNotEqual(self.execute(4, name, calls).returncode, 0)
        for name in ("enforce-peering", "commit-enforced-connectivity"):
            calls = copy.deepcopy(enforcement_cases()[name])
            before_update = -3 if name == "enforce-peering" else -2
            calls[before_update]["stdout"] = json.dumps(dict(connectivity_config(), id="wrong-config"))
            self.assertNotEqual(self.execute(4, name, calls[:len(calls) + before_update + 1]).returncode, 0)

    def test_enforcement_update_rechecks_saved_configuration_before_reporting_success(self):
        calls = copy.deepcopy(enforcement_cases()["enforce-peering"])
        persisted = json.loads(calls[-1]["stdout"])
        persisted["connectivityCapabilities"]["peeringEnforcement"] = "Unenforced"
        calls[-1]["stdout"] = json.dumps(persisted)
        result = self.execute(4, "enforce-peering", calls)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("PASS: peeringEnforcement=Enforced saved", result.stdout)

    def test_routing_configuration_rejects_wrong_full_id(self):
        calls = route_configuration_calls()
        self.assertEqual(self.execute(4, "routing-config-create", calls).returncode, 0)
        invalid = copy.deepcopy(calls)
        invalid[0]["stdout"] = json.dumps({"id": avnm_id() + "/routingConfigurations/other"})
        self.assertNotEqual(self.execute(4, "routing-config-create", invalid).returncode, 0)

    def test_first_run_routing_config_does_not_list_existing_names(self):
        calls = route_configuration_calls()
        self.assertEqual(self.execute(4, "routing-config-create", calls).returncode, 0)

    def test_routing_collections_and_rules_reject_wrong_targets_next_hops_and_full_ids(self):
        for zone in ("spokea", "spokeb"):
            for step, field, wrong in (
                (f"routing-collection-{zone}", "appliesTo",
                 [{"networkGroupId": routing_group_id("spokeb" if zone == "spokea" else "spokea")}]),
                (f"routing-collection-{zone}", "id", routing_group_id(zone)),
                (f"routing-rule-{zone}-other", "nextHop",
                 {"nextHopType": "VirtualAppliance", "nextHopAddress": "172.20.1.5"}),
                (f"routing-rule-{zone}-other", "id", "/subscriptions/" + SUB +
                 "/resourceGroups/" + rg("hub") + "/providers/Microsoft.Network/networkManagers/other/rules/to-other-spoke"),
            ):
                with self.subTest(step=step, field=field):
                    calls = copy.deepcopy(routing_cases()[step])
                    payload = json.loads(calls[-1]["stdout"])
                    payload[field] = wrong
                    calls[-1]["stdout"] = json.dumps(payload)
                    self.assertNotEqual(self.execute(4, step, calls).returncode, 0)
        calls = copy.deepcopy(routing_cases()["routing-rule-spokea-other"])
        payload = json.loads(calls[-1]["stdout"])
        payload["destination"]["destinationAddress"] = "172.20.16.0/20"
        calls[-1]["stdout"] = json.dumps(payload)
        self.assertNotEqual(self.execute(4, "routing-rule-spokea-other", calls).returncode, 0)

    def test_module04_mutations_show_direct_az_commands(self):
        steps = blocks(DOCS[4])
        self.assertNotIn("prepare-04-functions", steps)
        self.assertNotIn("firewall-preflight", steps)
        self.assertNotIn("routing-before-commit", steps)
        self.assertNotIn("inspect_routing_before_commit", DOCS[4].read_text())
        for name in ("forward-hub-to-spokea", "forward-spokea-to-hub",
                     "forward-hub-to-spokeb", "forward-spokeb-to-hub"):
            self.assertIn("az network vnet peering update", steps[name])
            self.assertIn("peering_for_forwarding", steps[name])
            self.assertIn("assert_peering_forwarded", steps[name])
        self.assertNotIn("assert_routing_creation_ready", steps["routing-config-create"])
        self.assertNotIn("routing-deploy-status", steps)
        for name in ("routing-config-create", "routing-collection-spokea",
                     "routing-collection-spokeb", "routing-rule-spokea-other",
                     "routing-rule-spokea-internet", "routing-rule-spokeb-other",
                     "routing-rule-spokeb-internet"):
            self.assertIn("az network manager routing-config", steps[name])
            self.assertIn("assert_routing_", steps[name])
        for name in ("enforce-peering", "commit-enforced-connectivity", "routing-commit"):
            self.assertIn("az network manager", steps[name])
        for name in ("enforce-peering", "commit-enforced-connectivity"):
            self.assertIn("assert_connectivity_config_ready", steps[name])
            self.assertNotIn("jq -e", steps[name])
        self.assertEqual(steps["enforce-peering"].count("assert_connectivity_config_ready"), 2)
        self.assertIn("az network manager connect-config update", steps["enforce-peering"])
        self.assertIn("az network manager post-commit", steps["commit-enforced-connectivity"])

    def test_routing_commit_checks_subnet_ownership_and_existing_attachments(self):
        calls = routing_commit_calls()
        result = self.execute(4, "routing-commit", calls)
        self.assertEqual(result.returncode, 0, result.stderr)
        for index, change in (
            (5, {"routeTable": {"id": "foreign"}}),
            (5, {"natGateway": {"id": "foreign"}}),
            (5, {"id": netid("spokeb", "virtualNetworks", vnet("spokeb") + "/subnets/snet-workload")}),
            (7, {"routeTable": {"id": "foreign"}}),
        ):
            with self.subTest(index=index, change=change):
                invalid = copy.deepcopy(calls[:index + 1])
                data = json.loads(invalid[-1]["stdout"])
                data.update(change)
                invalid[-1]["stdout"] = json.dumps(data)
                self.assertNotEqual(self.execute(4, "routing-commit", invalid).returncode, 0)

    def test_routing_commit_rejects_wrong_group_member_before_deployment(self):
        calls = routing_commit_calls()
        for index in (1, 3):
            invalid = copy.deepcopy(calls)
            invalid[index]["stdout"] = json.dumps([{
                "resourceId": netid("hub", "virtualNetworks", vnet("hub")),
                "provisioningState": "Succeeded",
            }])
            self.assertNotEqual(self.execute(4, "routing-commit", invalid[:index + 1]).returncode, 0)

    def test_routing_deployment_requires_latest_successful_exact_configuration(self):
        valid = routing_cases()["inspect-avnm-routing-subnets"]
        prefix = 'firewall_ready_ip() { printf "172.20.1.4\\n"; }\nassert_avnm_routes_ready() { :; }\nassert_no_spoke_nat() { :; }\n'
        self.assertEqual(self.execute(4, "inspect-avnm-routing-subnets", valid, prefix=prefix).returncode, 0)
        terminal_page = copy.deepcopy(valid)
        terminal_page[-1]["stdout"] = json.dumps({
            "skipToken": "",
            "value": json.loads(valid[-1]["stdout"]),
        })
        self.assertEqual(self.execute(4, "inspect-avnm-routing-subnets", terminal_page, prefix=prefix).returncode, 0)
        for status in (
            {"deploymentType": "Routing", "region": "koreacentral",
             "commitTime": "2026-01-02T00:00:00Z", "deploymentStatus": "Failed",
             "configurationIds": [avnm_id() + "/routingConfigurations/rc-lzbegin-spokes-demo123"]},
            {"deploymentType": "Routing", "region": "koreacentral",
             "commitTime": "2026-01-02T00:00:00Z", "deploymentStatus": "Deployed",
             "configurationIds": [avnm_id() + "/routingConfigurations/other"]},
        ):
            with self.subTest(status=status):
                call_list = copy.deepcopy(valid)
                call_list[-1]["stdout"] = json.dumps([
                    json.loads(valid[-1]["stdout"])[0], status])
                self.assertNotEqual(self.execute(4, "inspect-avnm-routing-subnets", call_list, prefix=prefix).returncode, 0)

    def test_support_deployment_refuses_failed_routing_gate_before_any_mutation(self):
        for name in ("support-preview", "support-deploy"):
            steps = blocks(DOCS[5])
            script = ('export STATE_FILE=state.json\n' + steps["prepare-05"] +
                      '\ncheck_vm_network() { return 1; }\n' + steps[name])
            result = run(script, preparation_calls(5), files=self.keyfile, input_text="CREATE\n")
            self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_support_post_create_gate_remains_required_without_recovery_step(self):
        steps = blocks(DOCS[5])
        self.assertNotIn("support-recovery", steps)
        self.assertIn("verify-support", steps)
        self.assertIsNone(re.search(r"--public-ip-address(?:\s|$)", steps["support-deploy"]))
        self.assertIn("verify_support_all", steps["verify-support"])
        self.assertLess(DOCS[5].read_text().index("<!-- exec:verify-support -->"),
                        DOCS[5].read_text().index("<!-- exec:attach-nat-hub -->"))

    def test_first_run_support_preview_and_deploy_do_not_inventory_names(self):
        self.assertEqual(self.execute(5, "support-preview", [], files=self.keyfile).returncode, 0)
        self.assertEqual(self.execute(
            5, "support-deploy", support_cases()["support-deploy"],
            files=self.keyfile, input_text="CREATE\n").returncode, 0)

    def test_support_verifier_can_check_pip_with_nounset(self):
        steps = blocks(DOCS[5])
        script = ('export STATE_FILE=state.json\n' + steps["prepare-05"] +
                  '\nset -u\nsource scripts/workshop-support.sh\nverify_support_resource pip hub')
        result = run(script, preparation_calls(5) + [support_read("pip", "hub")],
                     files=self.keyfile)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_support_verification_accepts_exact_configuration_and_rejects_drift(self):
        calls = support_verification_calls()
        script = ('export STATE_FILE=state.json\n' + blocks(DOCS[5])["prepare-05"] +
                  '\n' + blocks(DOCS[5])["verify-support"])
        result = run(script, preparation_calls(5) + calls, files=self.keyfile)
        self.assertEqual(result.returncode, 0, result.stderr)
        for index, key, value in (
            (1, "sku", {"name": "Basic"}),
            (3, "publicIpAddresses", []),
            (5, "enableIPForwarding", True),
            (7, "securityProfile", {"securityType": "Standard"}),
            (7, "diagnosticsProfile", {"bootDiagnostics": {"enabled": False}}),
        ):
            with self.subTest(index=index, key=key):
                bad = copy.deepcopy(calls[:index + 1])
                payload = json.loads(bad[-1]["stdout"])
                payload[key] = value
                bad[-1]["stdout"] = json.dumps(payload)
                self.assertNotEqual(run(script, preparation_calls(5) + bad, files=self.keyfile).returncode, 0)

    def test_support_recovery_refuses_foreign_malformed_and_disk_collisions(self):
        script = ('export STATE_FILE=state.json\n' + blocks(DOCS[5])["prepare-05"] +
                  '\nsource scripts/workshop-support.sh\nrequire_support_missing vm hub')
        resource = support_resource("vm", "hub")
        disk = {"name": "vm-lzbegin-hub-demo123_disk1_2628fd89665b46e5a3110aef30244cdf",
                "type": "Microsoft.Compute/disks", "tags": resource["tags"]}
        for inventory in ([dict(resource, tags={"runId": "other"})], [disk],
                          [{"name": resource["name"]}], {"value": []}):
            with self.subTest(inventory=inventory):
                calls = [az(["resource", "list", "--resource-group", rg("hub"), "-o", "json"], inventory)]
                self.assertNotEqual(run(script, preparation_calls(5) + calls,
                                        files=self.keyfile).returncode, 0)

    def test_attach_nat_is_blocked_by_failed_post_creation_verification(self):
        calls = support_verification_calls()
        calls[3]["stdout"] = json.dumps(dict(support_resource("nat", "hub"),
                                                idleTimeoutInMinutes=5))
        result = self.execute(5, "attach-nat-hub", calls[:4], files=self.keyfile)
        self.assertNotEqual(result.returncode, 0)

    def test_participant_modules_do_not_run_arm_deployments(self):
        for module, path in DOCS.items():
            with self.subTest(module=module):
                for name, script in blocks(path).items():
                    self.assertNotIn("az deployment", script, name)

    def test_effective_admin_checks_require_exact_avnm_rule_and_action(self):
        for step, zone, local, remote, action, rule in (
            ("verify-admin-allow-a", "spokea", "172.20.16.4", "172.20.0.4", "Allow", "hub-to-a"),
            ("verify-admin-allow-b", "spokeb", "172.20.32.4", "172.20.0.4", "Allow", "hub-to-b"),
            ("verify-admin-allow-ab", "spokeb", "172.20.32.4", "172.20.16.4", "Allow", "a-to-b"),
        ):
            access = "AlwaysAllow" if action == "Allow" else "Deny"
            with self.subTest(step=step):
                self.assertEqual(self.execute(5, step, [
                    effective_admin_call(zone, rule, remote, local, access)
                ]).returncode, 0)
                for change in ({"access": "Deny" if action == "Allow" else "AlwaysAllow"},
                               {"id": "defaultSecurityRules/" + rule},
                               {"id": effective_admin_rule(zone, rule, remote, local, access)["id"] + "/child"},
                               {"sources": [{"addressPrefixType": "IPPrefix",
                                             "addressPrefix": "10.0.1.5/32"}]},
                               {"destinationPortRanges": ["80"]}):
                    malformed = dict(effective_admin_rule(zone, rule, remote, local, access), **change)
                    attempts = [effective_admin_call(zone, rule, remote, local, access,
                                {"value": [malformed], "skipToken": ""}) for _ in range(12)]
                    self.assertNotEqual(self.execute(5, step, attempts).returncode, 0)

    def test_security_admin_rules_reject_wrong_action_priority_ip_target_and_full_ids(self):
        for step in ("inspect-security-rules",):
            calls = security_cases()[step]
            self.assertEqual(self.execute(5, step, calls).returncode, 0)
            for index, field, value in (
                (1, "appliesToGroups", [{"networkGroupId": routing_group_id("spokeb")}]),
                (3, "kind", "Default"),
                (3, "access", "Allow"),
                (3, "priority", 100),
                (3, "sources", [{"addressPrefixType": "IPPrefix", "addressPrefix": "10.0.1.5/32"}]),
                (3, "id", security_rule("spokea", "hub-to-a", "172.20.0.4", "172.20.16.4",
                                        "AlwaysAllow", 200)["id"] + "/child"),
            ):
                with self.subTest(step=step, field=field):
                    altered = copy.deepcopy(calls[:index + 1])
                    data = json.loads(altered[-1]["stdout"])
                    data[field] = value
                    altered[-1]["stdout"] = json.dumps(data)
                    self.assertNotEqual(self.execute(5, step, altered).returncode, 0)
        altered = copy.deepcopy(security_cases()["inspect-security-rules"][:3])
        rules = json.loads(altered[-1]["stdout"])
        rules.append({"id": avnm_id() +
                      "/securityAdminConfigurations/sc-lzbegin-http-demo123"
                      "/ruleCollections/spokea/rules/deny-hub-to-a"})
        altered[-1]["stdout"] = json.dumps(rules)
        self.assertNotEqual(self.execute(5, "inspect-security-rules", altered).returncode, 0)

    def test_vm_and_validation_gates_require_deployed_avnm_routes_and_no_spoke_nat(self):
        for module, step, calls in (
            (5, "vm-route-gate", [*ready_calls(), *deployed_route_calls(), *no_spoke_nat_calls()]),
        ):
            with self.subTest(step=step):
                result = self.execute(module, step, calls)
                self.assertEqual(result.returncode, 0, result.stderr)
        for index, field, value in (
            (6, "id", avnm_id() + "/routingConfigurations/other"),
            (8, "appliesTo", [{"networkGroupId": routing_group_id("spokeb")}]),
            (9, "destination", {"type": "AddressPrefix", "destinationAddress": "172.20.16.0/20"}),
            (9, "nextHop", {"nextHopType": "VirtualAppliance", "nextHopAddress": "172.20.1.5"}),
            (11, "id", netid("spokeb", "virtualNetworks", vnet("spokeb") + "/subnets/snet-workload")),
            (12, "id", netid("spokeb", "routeTables", "avnm-managed-spokeb")),
            (12, "routes", [{"provisioningState": "Succeeded", "addressPrefix": "0.0.0.0/0",
                             "nextHopType": "VirtualAppliance", "nextHopIpAddress": FW_IP}]),
        ):
            with self.subTest(index=index, field=field):
                calls = [*ready_calls(), *deployed_route_calls()]
                altered = copy.deepcopy(calls[:index + 1])
                data = json.loads(altered[-1]["stdout"])
                data[field] = value
                altered[-1]["stdout"] = json.dumps(data)
                self.assertNotEqual(self.execute(6, "firewall-deny", altered).returncode, 0)
        calls = effective_route_calls()
        for index in (-2, -1):
            altered = copy.deepcopy(calls if index == -1 else calls[:-1])
            route = json.loads(altered[-1]["stdout"])
            route["value"][0]["nextHopIpAddress"] = ["172.20.1.5"]
            altered[-1]["stdout"] = json.dumps(route)
            self.assertNotEqual(self.execute(6, "firewall-deny", altered).returncode, 0)
        for index, payload in ((1, {"natGateway": {"id": "foreign"}}),
                               (2, [{"name": "unexpected-nat"}]), (3, [{"name": "unexpected-pip"}])):
            calls = no_spoke_nat_calls()
            altered = copy.deepcopy(calls[:2] if index == 1 else calls[:4])
            altered[index]["stdout"] = json.dumps(payload)
            self.assertNotEqual(self.execute(6, "firewall-deny",
                                            [*effective_route_calls(), *altered]).returncode, 0)

    def test_each_action_stops_after_any_failed_dependency_lookup(self):
        for module, cases in self.cases():
            for name, calls in cases.items():
                for index in range(len(calls) - 1):
                    with self.subTest(step=name, failure=index):
                        failed = copy.deepcopy(calls[:index + 1])
                        failed[-1].update(returncode=1, stdout="")
                        self.assertNotEqual(self.execute(module, name, failed, files=self.keyfile,
                                                         input_text="CREATE\nFIREWALL\n").returncode, 0)

    def test_final_cli_failure_is_not_hidden_and_does_not_exit_the_participant_shell(self):
        for module, cases in self.cases():
            for name, calls in cases.items():
                if not calls:
                    continue
                with self.subTest(step=name):
                    failed = copy.deepcopy(calls)
                    failed[-1].update(returncode=1, stdout="")
                    result = self.execute(module, name, failed, files=self.keyfile,
                                          input_text="CREATE\n" if name == "support-deploy" else "FIREWALL\n")
                    self.assertNotEqual(result.returncode, 0)

    def test_ownership_mismatch_never_reaches_mutations_or_other_resources(self):
        for module, cases in self.cases():
            for name, calls in cases.items():
                for index, item in enumerate(calls):
                    if item["argv"][:2] != ["group", "show"]:
                        continue
                    with self.subTest(step=name, group=index):
                        failed = copy.deepcopy(calls[:index + 1])
                        data = json.loads(failed[-1]["stdout"])
                        data["id"] = data["id"].replace(SUB, "99999999-9999-9999-9999-999999999999")
                        failed[-1]["stdout"] = json.dumps(data)
                        result = self.execute(module, name, failed, files=self.keyfile, input_text="CREATE\nFIREWALL\n")
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn("Ownership mismatch", result.stderr)

    def test_firewall_creation_runs_without_repeated_cost_confirmation(self):
        names = ["firewall-workspace", "firewall-public-ip", "firewall-policy", "firewall-create", "firewall-ip-config"]
        for name in names:
            with self.subTest(step=name):
                result = self.execute(4, name, firewall_cases()[name], input_text="")
                self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.execute(5, "support-deploy",
                                        [], input_text="NO\n",
                                        files=self.keyfile).returncode, 0)

    def test_missing_key_stops_preview_and_deploy_without_cloud_mutation(self):
        for name in ("support-preview", "support-deploy"):
            with self.subTest(step=name):
                self.assertNotEqual(self.execute(5, name, input_text="CREATE\n").returncode, 0)

    def test_module05_effective_routes_need_no_watcher_activation(self):
        steps = blocks(DOCS[5])
        self.assertIn("effective-vm-routes", steps)
        self.assertNotIn("inspect-watcher", steps)
        self.assertNotIn("watcher-enable", steps)
        self.assertNotIn("az network watcher", DOCS[5].read_text())

    def test_live_remote_cidrs_are_printed_in_route_evidence(self):
        result = self.execute(5, "effective-vm-routes",
                              [*ready_calls(), *effective_route_calls()[-2:]])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS: spokea NIC 172.20.32.0/20 and /0 -> Firewall", result.stdout)
        self.assertIn("PASS: spokeb NIC 172.20.16.0/20 and /0 -> Firewall", result.stdout)
        self.assertNotIn("NIC /16", result.stdout)
        for module in (4, 5, 6):
            self.assertNotIn("/16", DOCS[module].read_text())

    def test_script_actions_remain_single_purpose_and_propagate_failures(self):
        cases = [
            (5, "service-spokea", "scripts/run-vm.sh", ["spokea", "scripts/guest-server.sh"]),
            (5, "service-spokeb", "scripts/run-vm.sh", ["spokeb", "scripts/guest-server.sh"]),
            (5, "vm-preflight", "scripts/preflight.sh", []),
            (6, "verify-allowed", "scripts/verify-extension.sh", ["allowed"]),
            (6, "verify-denied", "scripts/verify-extension.sh", ["denied"]),
            (6, "verify-restored", "scripts/verify-extension.sh", ["restored"]),
            (7, "cleanup", "scripts/cleanup.sh", []),
        ]
        for module, name, script, args in cases:
            for code in (0, 1):
                with self.subTest(step=name, code=code):
                    result = self.execute(module, name, prefix=verifier(script, args, code))
                    self.assertEqual(result.returncode, code, result.stderr)
                    self.assertEqual(result.stdout.count("VERIFY:"), 1)

    def test_http_rule_changes_reject_ambiguous_collections(self):
        for name in ("firewall-deny", "firewall-restore"):
            for collections in ([], [{"name": "lab-http"}, {"name": "lab-http"}], None,
                                {"not-an-array": {"name": "lab-http"}}):
                calls = routing_cases()[name][:-1]
                calls[-1]["stdout"] = json.dumps({"ruleCollections": collections})
                self.assertNotEqual(self.execute(6, name, calls).returncode, 0)

    def test_diagnostics_reject_unsupported_categories_and_wrong_saved_workspace(self):
        for name in ("firewall-diagnostics",):
            calls = firewall_cases()[name][:-1]
            calls[-1]["stdout"] = '{"value":[]}'
            self.assertNotEqual(self.execute(4, name, calls).returncode, 0)
        calls = firewall_cases()["firewall-diagnostics"][:-1]
        calls[-1]["stdout"] = '{"value":{"first":{"name":"AZFWNetworkRule"},"second":{"name":"AZFWApplicationRule"}}}'
        self.assertNotEqual(self.execute(4, "firewall-diagnostics", calls).returncode, 0)

    def test_key_preparation_creates_or_reuses_a_private_directory_without_overwriting_partial_keys(self):
        stub = """#!/usr/bin/env python3
import pathlib, sys
assert sys.argv[1:] == ['-t', 'ed25519', '-N', '', '-f', '.workshop-keys/demo123/id_ed25519', '-C', 'lz-beginner-demo123']
key = pathlib.Path(sys.argv[sys.argv.index('-f') + 1])
assert key.parent.stat().st_mode & 0o777 == 0o700
key.write_text('fixture-private-key')
key.with_suffix('.pub').write_text('fixture-public-key')
"""
        result = self.execute(5, "support-key", files={"bin/ssh-keygen": stub})
        self.assertEqual(result.returncode, 0, result.stderr)
        both = dict(self.keyfile, **{".workshop-keys/demo123/id_ed25519": "fixture-private-key",
                                     "bin/ssh-keygen": "#!/bin/sh\nexit 99\n"})
        result = self.execute(5, "support-key", files=both)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotEqual(self.execute(5, "support-key", files=self.keyfile).returncode, 0)

    def test_cleanup_recovery_actions_are_separate_and_do_not_delete_anything(self):
        originals = ('ORIGINAL_RUN_ID=demo123\nORIGINAL_SUBSCRIPTION=' + SUB +
                     '\nORIGINAL_LOCATION=koreacentral\nORIGINAL_SCHEMA=4\n')
        self.assertEqual(self.execute(7, "recovery-input", input_text=f"demo123\n{SUB}\nkoreacentral\n4\n").returncode, 0)
        self.assertEqual(self.execute(7, "recovery-subscription",
                                     [call(["account", "set", "--subscription", SUB])], prefix=originals).returncode, 0)
        self.assertEqual(self.execute(7, "recovery-state", prefix=originals).returncode, 0)
        result = self.execute(7, "recovery-state", prefix=originals,
                              files={".workshop-state/demo123.json": "do-not-overwrite"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("State exists", result.stderr)

    def test_prepared_session_targets_state_subscription_even_after_active_subscription_switch(self):
        other = "99999999-9999-9999-9999-999999999999"
        cases = [
            (2, "foundation-hub-rg", test_network_docs.foundation_cases()["foundation-hub-rg"]),
            (2, "foundation-hub-vnet", test_network_docs.foundation_cases()["foundation-hub-vnet"]),
            (2, "avnm-create", test_network_docs.avnm_cases()["avnm-create"]),
            (3, "avnm-ready", test_network_docs.avnm_cases()["avnm-ready"]),
            (4, "register-logs", firewall_cases()["register-logs"]),
            (4, "firewall-http-rule", firewall_cases()["firewall-http-rule"]),
            (4, "firewall-diagnostics", firewall_cases()["firewall-diagnostics"]),
            (4, "forward-hub-to-spokea", routing_cases()["forward-hub-to-spokea"]),
            (5, "support-deploy", support_cases()["support-deploy"]),
            (5, "attach-nat-hub", support_cases()["attach-nat-hub"]),
            (5, "allow-hub-spokea", security_cases()["allow-hub-spokea"]),
        ]
        for module, name, calls in cases:
            with self.subTest(step=name):
                result = self.execute(module, name,
                                      [call(["account", "set", "--subscription", other]), *calls],
                                      prefix=f'az account set --subscription {other}\n',
                                      input_text="CREATE\n", files=self.keyfile)
                self.assertEqual(result.returncode, 0, result.stderr)
