import copy
import json
import unittest
import test_network_docs
from harness import run, account, group, call, ROOT, SUB
from test_network_docs import blocks, DOCS, az, rg, netid, vnet, subnet_args, nic, TAGS, recase_ids, foreign_ids, preparation_calls, avnm_id, routing_group_id, avnm_peerings, connectivity_config, connectivity_config_id, enforced_connectivity_calls
from test_workshop_safety import FW, LAW, FW_IP, ready_calls, effective_admin_call, effective_admin_rule


def support_args(verb):
    return ["deployment", "sub", verb, "--name", "support-demo123", "--location", "koreacentral",
            "--template-file", "infra/lab-support.bicep", "--parameters", "runId=demo123",
            "location=koreacentral", "hubResourceGroup=" + rg("hub"),
            "spokeaResourceGroup=" + rg("spokea"), "spokebResourceGroup=" + rg("spokeb"),
            "sshPublicKey=fixture-public-key"]


def support_cases():
    cases = {
        "support-preview": [az(support_args("what-if"))],
        "support-deploy": [az([*support_args("create"), "-o", "json"])],
        "inspect-watcher": [az(["network", "watcher", "list", "--query",
                               "[?location=='koreacentral'].id", "-o", "json"], [])],
        "watcher-enable": [az(["network", "watcher", "list", "--query",
                              "[?location=='koreacentral'].id", "-o", "json"], []),
                           az(["group", "exists", "--name", "NetworkWatcherRG", "-o", "tsv"], "true"),
                           az(["network", "watcher", "configure", "--locations", "koreacentral",
                               "--enabled", "true", "--resource-group", "NetworkWatcherRG", "-o", "json"])],
        "attach-nat-hub": [az(["network", "vnet", "subnet", "update", *subnet_args("hub"),
                              "--nat-gateway", "nat-lzbegin-hub-demo123", "-o", "json"])],
        "inspect-nat-hub": [az(["network", "vnet", "subnet", "show", *subnet_args("hub"),
                               "--query", "{Subnet:name,NatGateway:natGateway.id,NSG:networkSecurityGroup.id,DefaultOutbound:defaultOutboundAccess}",
                               "-o", "json"], {"Subnet": "snet-management",
                                               "NatGateway": netid("hub", "natGateways", "nat-lzbegin-hub-demo123"),
                                               "NSG": netid("hub", "networkSecurityGroups", "nsg-lzbegin-hub-demo123"),
                                               "DefaultOutbound": False})],
        "read-vm-ips": [nic("hub", "10.0.1.4"), nic("spokea", "10.10.1.4"), nic("spokeb", "10.20.1.4")],
    }
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
                                                       "--source-addresses", "10.10.1.0/24", "10.20.1.0/24",
                                                       "--destination-addresses", "AzureCloud", "--destination-ports", "443",
                                                       "-o", "json"])],
        "firewall-http-rule": [az([*collection, "-n", "lab-http", "--collection-priority", "200", "--action", "Allow",
                                   "--rule-name", "spokea-to-spokeb", "--rule-type", "NetworkRule",
                                   "--ip-protocols", "TCP", "--source-addresses", "10.10.1.0/24",
                                   "--destination-addresses", "10.20.1.0/24", "--destination-ports", "8080", "-o", "json"])],
        "firewall-egress-rule": [az([*collection, "-n", "egress-check", "--collection-priority", "300",
                                                   "--action", "Allow", "--rule-name", "public-ip-check",
                                                   "--rule-type", "ApplicationRule", "--source-addresses",
                                                   "10.10.1.0/24", "10.20.1.0/24", "--protocols", "Https=443",
                                                   "--target-fqdns", "api.ipify.org", "-o", "json"])],
        "inspect-firewall-rules": [ready_calls()[-1]],
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
        "routing-config-create": [
            az(["network", "manager", "show", "-g", rg("hub"), "-n", "avnm-lzbegin-demo123",
                "-o", "json"], {"id": manager, "provisioningState": "Succeeded",
                               "networkManagerScopeAccesses": ["Connectivity", "SecurityAdmin", "Routing"]}),
        ],
        "routing-deploy-status": [az([
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
        for kind, rule, prefix in (("other", "to-other-spoke", "10.20.0.0/16" if zone == "spokea" else "10.10.0.0/16"),
                                   ("internet", "to-internet", "0.0.0.0/0")):
            dest = json.dumps({"type": "AddressPrefix", "destinationAddress": prefix}, separators=(",", ":"))
            hop = json.dumps({"nextHopType": "VirtualAppliance", "nextHopAddress": FW_IP}, separators=(",", ":"))
            cases[f"routing-rule-{zone}-{kind}"] = [*ready_calls(), az([
                "network", "manager", "routing-config", "rule-collection", "rule", "create",
                "-g", rg("hub"), "--manager-name", "avnm-lzbegin-demo123",
                "--config-name", "rc-lzbegin-spokes-demo123", "--collection-name", zone, "-n", rule,
                "--destination", dest, "--next-hop", hop, "-o", "json"],
                {"id": collection + "/rules/" + rule,
                 "destination": {"type": "AddressPrefix", "destinationAddress": prefix},
                 "nextHop": {"nextHopType": "VirtualAppliance", "nextHopAddress": FW_IP}})]
    for name, action in (("firewall-deny", "Deny"), ("firewall-restore", "Allow")):
        cases[name] = [az(["network", "firewall", "policy", "rule-collection-group", "show", "-g", rg("hub"),
                           "--policy-name", "fwpol-lzbegin-demo123", "-n", "workshop", "-o", "json"],
                          {"ruleCollections": [{"name": "egress-check"}, {"name": "management"},
                                               {"name": "lab-http", "action": {"type": "Allow" if action == "Deny" else "Deny"}}]}),
                       az(["network", "firewall", "policy", "rule-collection-group", "update", "-g", rg("hub"),
                           "--policy-name", "fwpol-lzbegin-demo123", "-n", "workshop",
                           "--set", f"ruleCollections[2].action.type={action}", "-o", "json"])]
    return cases


def route_configuration_calls():
    manager = avnm_id()
    calls = routing_cases()["routing-config-create"].copy()
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
    calls += [
        az(["network", "manager", "routing-config", "list", "-g", rg("hub"),
            "--manager-name", "avnm-lzbegin-demo123", "-o", "json"], []),
        az(["network", "manager", "routing-config", "create", "-g", rg("hub"),
            "--manager-name", "avnm-lzbegin-demo123", "-n", "rc-lzbegin-spokes-demo123",
            "--description", "Spoke routes via Hub Firewall", "-o", "json"],
           {"id": manager + "/routingConfigurations/rc-lzbegin-spokes-demo123"})]
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
    for zone, remote in (("spokea", "10.20.0.0/16"), ("spokeb", "10.10.0.0/16")):
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
    for zone, remote in (("spokea", "10.20.0.0/16"), ("spokeb", "10.10.0.0/16")):
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
        ("spokea", [("hub-to-a", "10.0.1.4", "10.10.1.4", "AlwaysAllow", 200)]
         + ([("deny-hub-to-a", "10.0.1.4", "10.10.1.4", "Deny", 100)] if stage == "denied" else [])),
        ("spokeb", [("hub-to-b", "10.0.1.4", "10.20.1.4", "AlwaysAllow", 210),
                     ("a-to-b", "10.10.1.4", "10.20.1.4", "AlwaysAllow", 220)]),
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


def undeployed_security_status(deployments=None):
    if deployments is None:
        deployments = [{
            "deploymentType": "SecurityAdmin",
            "region": "koreacentral",
            "commitTime": "2026-09-27T04:00:00Z",
            "deploymentStatus": "Deployed",
            "configurationIds": [],
        }]
    return az([
        "rest", "--method", "post",
        "--url", avnm_id() + "/listDeploymentStatus?api-version=2025-05-01",
        "--body", '{"deploymentTypes":["SecurityAdmin"],"regions":["koreacentral"]}',
        "-o", "json",
    ], deployments)


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
        ("allow-hub-spokea", "spokea", "hub-to-a", "10.0.1.4", "10.10.1.4", "AlwaysAllow", 200),
        ("allow-hub-spokeb", "spokeb", "hub-to-b", "10.0.1.4", "10.20.1.4", "AlwaysAllow", 210),
        ("allow-spokea-spokeb", "spokeb", "a-to-b", "10.10.1.4", "10.20.1.4", "AlwaysAllow", 220),
        ("deny-hub", "spokea", "deny-hub-to-a", "10.0.1.4", "10.10.1.4", "Deny", 100),
    ):
        cases[step] = [az([*base, "rule-collection", "rule", "create", *options,
                           "--rule-collection-name", zone, "--rule-name", rule,
                           "--priority", str(priority), "--direction", "Inbound",
                           "--access", access, "--protocol", "Tcp",
                           "--sources", f"address-prefix={source}/32", "address-prefix-type=IPPrefix",
                           "--source-port-ranges", "0-65535", "--destinations",
                           f"address-prefix={dest}/32", "address-prefix-type=IPPrefix",
                           "--dest-port-ranges", "8080", "-o", "json"])]
    for step in ("security-deploy", "security-deploy-deny", "security-deploy-restore"):
        cases[step] = [az(["network", "manager", "post-commit", "-g", rg("hub"),
                           "--network-manager-name", "avnm-lzbegin-demo123", "--commit-type",
                           "SecurityAdmin", "--configuration-ids", config,
                           "--target-locations", "koreacentral", "-o", "json"])]
    cases["security-undeploy-for-restore"] = [
        az(["network", "manager", "post-commit", "-g", rg("hub"),
            "--network-manager-name", "avnm-lzbegin-demo123", "--commit-type",
            "SecurityAdmin", "--configuration-ids", "[]",
            "--target-locations", "koreacentral", "-o", "json"]),
        undeployed_security_status(),
    ]
    cases["restore-hub"] = [undeployed_security_status(),
                            az([*base, "rule-collection", "rule", "delete", *options,
                                "--rule-collection-name", "spokea", "--rule-name",
                                "deny-hub-to-a", "--yes"])]
    for step, stage in (("inspect-security-rules", "baseline"),
                        ("inspect-admin-deny", "denied"),
                        ("inspect-admin-restored", "restored")):
        cases[step] = admin_rule_checks(stage)
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

    def execute(self, module, name, calls=(), input_text=None, files=None, prefix="", state=test_network_docs.STATE):
        steps = blocks(DOCS[module])
        if (module, name) in ((4, "routing-config-create"), (5, "vm-route-gate")):
            calls = [*enforced_connectivity_calls(), *calls]
        if module == 5 and name in ("support-preview", "support-deploy"):
            prefix += "check_vm_network() { :; }\n"
        if module == 5 and name in ("allow-hub-spokea", "allow-hub-spokeb",
                                     "allow-spokea-spokeb", "deny-hub",
                                     "inspect-security-rules", "inspect-admin-deny",
                                     "inspect-admin-restored"):
            prefix += 'hub_ip=10.0.1.4; a_ip=10.10.1.4; b_ip=10.20.1.4\n'
        if module == 5 and name.startswith("verify-admin-") and name not in (
            "verify-admin-http-baseline", "verify-admin-http-denied", "verify-admin-http-restored"):
            prefix += steps["admin-flow-check"] + "\n"
            prefix += 'hub_ip=10.0.1.4; a_ip=10.10.1.4; b_ip=10.20.1.4\n'
        if module == 6 and name == "firewall-deny":
            prefix += "validate_effective_nic_routes() { :; }\nassert_no_spoke_nat() { :; }\n"
        return test_network_docs.NetworkDocsTests.execute(
            self, module, name, calls, input_text, files, prefix, state)

    def test_module_05_execution_blocks_do_not_chain_with_and(self):
        for name, script in blocks(DOCS[5]).items():
            with self.subTest(step=name):
                self.assertNotIn("&&", script)

    def test_security_undeploy_is_confirmed_before_deleting_deployed_deny_rule(self):
        steps = blocks(DOCS[5])
        names = ("security-undeploy-for-restore", "restore-hub", "security-deploy-restore")
        self.assertTrue(names[0] in steps,
                        "A deployed Security Admin configuration must be undeployed before rule deletion")
        self.assertLess(list(steps).index(names[0]), list(steps).index(names[1]))
        script = 'export STATE_FILE=state.json\n' + steps["prepare-05"] + "\n"
        script += "\n".join(f'{steps[name]}\n[[ $? == 0 ]] || exit 1' for name in names)
        calls = [*preparation_calls(5)]
        for name in names:
            calls.extend(security_cases()[name])
        result = run(script, calls)
        self.assertEqual(result.returncode, 0, result.stderr)

        latest_deployed = {"deploymentType": "SecurityAdmin", "region": "koreacentral",
                           "commitTime": "2026-09-27T04:00:00Z", "deploymentStatus": "Deployed",
                           "configurationIds": []}
        previous_deployed = dict(latest_deployed, commitTime="2026-09-27T03:00:00Z",
                                 configurationIds=[avnm_id() +
                                                   "/securityAdminConfigurations/sc-lzbegin-http-demo123"])
        for label, deployments in (
            ("still-deployed", [previous_deployed]),
            ("latest-failed", [previous_deployed, dict(latest_deployed, deploymentStatus="Failed")]),
            ("latest-pending", [previous_deployed, dict(latest_deployed, deploymentStatus="Deploying")]),
            ("stale-empty", [dict(latest_deployed, commitTime="2026-09-27T02:00:00Z"),
                             previous_deployed]),
            ("wrong-region", [dict(latest_deployed, region="eastus")]),
            ("missing", []),
        ):
            with self.subTest(label=label):
                invalid = security_cases()["security-undeploy-for-restore"][:1]
                invalid.append(undeployed_security_status(deployments))
                self.assertNotEqual(self.execute(5, "security-undeploy-for-restore", invalid).returncode, 0)
                self.assertNotEqual(self.execute(5, "restore-hub",
                                                [undeployed_security_status(deployments)]).returncode, 0)

        newest = [latest_deployed, previous_deployed]
        self.assertEqual(self.execute(5, "security-undeploy-for-restore", [
            security_cases()["security-undeploy-for-restore"][0],
            undeployed_security_status(newest),
        ]).returncode, 0)
        self.assertEqual(self.execute(5, "restore-hub", [
            undeployed_security_status(newest), security_cases()["restore-hub"][-1],
        ]).returncode, 0)

    def test_ordinary_actions_check_ownership_once_for_a_prepared_session(self):
        cases = dict(self.cases())
        cases[3] = test_network_docs.avnm_cases()
        for module, names in (
            (3, ("avnm-create", "network-group-create", "member-spokea",
                 "member-spokeb", "connectivity-config-create",
                 "connectivity-commit", "effective-hub")),
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
        for module, action in ((3, "avnm-create"), (4, "firewall-workspace"),
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

    def test_nat_inspections_display_ids_in_original_casing(self):
        for zone in ("hub",):
            name = f"inspect-nat-{zone}"
            for transform in (str.lower, str.swapcase):
                with self.subTest(step=name, casing=transform.__name__):
                    result = self.execute(5, name, recase_ids(support_cases()[name], transform))
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(transform(netid(zone, "natGateways", f"nat-lzbegin-{zone}-demo123")),
                                  result.stdout)

    def test_reference_mismatches_remain_errors_not_suffix_matches(self):
        for bad in foreign_ids(LAW):
            calls = firewall_cases()["firewall-diagnostics"]
            calls[1]["stdout"] = bad.lower()
            self.assertNotEqual(self.execute(4, "firewall-diagnostics", calls[:2]).returncode, 0)

    def cases(self):
        return ((4, {k: v for k, v in firewall_cases().items() if k != "inspect-firewall-rules"}
                 | {k: v for k, v in routing_cases().items() if k.startswith("forward-")
                    or k.startswith("routing-collection-") or k.startswith("routing-rule-")
                    or k.startswith("routing-deploy-status")}
                 | enforcement_cases()),
                (5, {k: v for k, v in support_cases().items() if k not in ("watcher-enable",)}
                 | security_cases()),
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
            calls[-2]["stdout"] = json.dumps(dict(connectivity_config(), id="wrong-config"))
            self.assertNotEqual(self.execute(4, name, calls[:-1]).returncode, 0)

    def test_routing_configuration_rejects_wrong_member_and_full_group_ids(self):
        calls = route_configuration_calls()
        self.assertEqual(self.execute(4, "routing-config-create", calls).returncode, 0)
        for index, field, wrong in (
            (1, "id", routing_group_id("spokeb")),
            (2, "resourceId", netid("spokeb", "virtualNetworks", vnet("spokeb"))),
            (3, "id", routing_group_id("spokea") + "/staticMembers/spokea"),
            (4, "resourceId", netid("spokeb", "virtualNetworks", vnet("spokeb")) + "/subnets/snet-workload"),
            (6, "id", avnm_id() + "/routingConfigurations/other"),
        ):
            with self.subTest(index=index, field=field):
                invalid = copy.deepcopy(calls[:index + 1])
                payload = json.loads(invalid[-1]["stdout"])
                if index in (2, 4):
                    payload[0][field] = wrong
                else:
                    payload[field] = wrong
                invalid[-1]["stdout"] = json.dumps(payload)
                self.assertNotEqual(self.execute(4, "routing-config-create", invalid).returncode, 0)

    def test_routing_collections_and_rules_reject_wrong_targets_next_hops_and_full_ids(self):
        for zone in ("spokea", "spokeb"):
            for step, field, wrong in (
                (f"routing-collection-{zone}", "appliesTo",
                 [{"networkGroupId": routing_group_id("spokeb" if zone == "spokea" else "spokea")}]),
                (f"routing-collection-{zone}", "id", routing_group_id(zone)),
                (f"routing-rule-{zone}-other", "nextHop",
                 {"nextHopType": "VirtualAppliance", "nextHopAddress": "10.0.2.5"}),
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
        payload["destination"]["destinationAddress"] = "10.10.0.0/16"
        calls[-1]["stdout"] = json.dumps(payload)
        self.assertNotEqual(self.execute(4, "routing-rule-spokea-other", calls).returncode, 0)

    def test_module04_mutations_show_direct_az_commands(self):
        steps = blocks(DOCS[4])
        self.assertNotIn("prepare-04-functions", steps)
        for name in ("forward-hub-to-spokea", "forward-spokea-to-hub",
                     "forward-hub-to-spokeb", "forward-spokeb-to-hub"):
            self.assertIn("az network vnet peering update", steps[name])
            self.assertIn("peering_for_forwarding", steps[name])
            self.assertIn("assert_peering_forwarded", steps[name])
        for name in ("routing-config-create", "routing-collection-spokea",
                     "routing-collection-spokeb", "routing-rule-spokea-other",
                     "routing-rule-spokea-internet", "routing-rule-spokeb-other",
                     "routing-rule-spokeb-internet"):
            self.assertIn("az network manager routing-config", steps[name])
            self.assertIn("assert_routing_", steps[name])
        for name in ("enforce-peering", "commit-enforced-connectivity", "routing-commit"):
            self.assertIn("az network manager", steps[name])

    def test_routing_deployment_requires_latest_successful_exact_configuration(self):
        valid = routing_cases()["routing-deploy-status"]
        self.assertEqual(self.execute(4, "routing-deploy-status", valid).returncode, 0)
        terminal_page = copy.deepcopy(valid)
        terminal_page[-1]["stdout"] = json.dumps({
            "skipToken": "",
            "value": json.loads(valid[-1]["stdout"]),
        })
        self.assertEqual(self.execute(4, "routing-deploy-status", terminal_page).returncode, 0)
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
                self.assertNotEqual(self.execute(4, "routing-deploy-status", call_list).returncode, 0)

    def test_support_deployment_refuses_failed_routing_gate_before_any_mutation(self):
        for name in ("support-preview", "support-deploy"):
            steps = blocks(DOCS[5])
            script = ('export STATE_FILE=state.json\n' + steps["prepare-05"] +
                      '\ncheck_vm_network() { return 1; }\n' + steps[name])
            result = run(script, preparation_calls(5), files=self.keyfile, input_text="CREATE\n")
            self.assertNotEqual(result.returncode, 0, result.stderr)

    def test_effective_admin_checks_require_exact_avnm_rule_and_action(self):
        for step, zone, local, remote, action, rule in (
            ("verify-admin-allow-a", "spokea", "10.10.1.4", "10.0.1.4", "Allow", "hub-to-a"),
            ("verify-admin-allow-b", "spokeb", "10.20.1.4", "10.0.1.4", "Allow", "hub-to-b"),
            ("verify-admin-allow-ab", "spokeb", "10.20.1.4", "10.10.1.4", "Allow", "a-to-b"),
            ("verify-admin-deny", "spokea", "10.10.1.4", "10.0.1.4", "Deny", "deny-hub-to-a"),
            ("verify-admin-restored", "spokea", "10.10.1.4", "10.0.1.4", "Allow", "hub-to-a"),
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
        for step in ("inspect-security-rules", "inspect-admin-deny", "inspect-admin-restored"):
            calls = security_cases()[step]
            self.assertEqual(self.execute(5, step, calls).returncode, 0)
            for index, field, value in (
                (1, "appliesToGroups", [{"networkGroupId": routing_group_id("spokeb")}]),
                (3, "kind", "Default"),
                (3, "access", "Allow"),
                (3, "priority", 100),
                (3, "sources", [{"addressPrefixType": "IPPrefix", "addressPrefix": "10.0.1.5/32"}]),
                (3, "id", security_rule("spokea", "hub-to-a", "10.0.1.4", "10.10.1.4",
                                        "AlwaysAllow", 200)["id"] + "/child"),
            ):
                with self.subTest(step=step, field=field):
                    altered = copy.deepcopy(calls[:index + 1])
                    data = json.loads(altered[-1]["stdout"])
                    data[field] = value
                    altered[-1]["stdout"] = json.dumps(data)
                    self.assertNotEqual(self.execute(5, step, altered).returncode, 0)
        denied = security_cases()["inspect-admin-deny"]
        for field, wrong in (("access", "AlwaysAllow"), ("priority", 300),
                             ("destinations", [{"addressPrefixType": "IPPrefix", "addressPrefix": "10.20.1.4/32"}])):
            altered = copy.deepcopy(denied[:5])
            data = json.loads(altered[-1]["stdout"])
            data[field] = wrong
            altered[-1]["stdout"] = json.dumps(data)
            self.assertNotEqual(self.execute(5, "inspect-admin-deny", altered).returncode, 0)

    def test_vm_and_validation_gates_require_deployed_avnm_routes_and_no_spoke_nat(self):
        for module, step, calls in (
            (5, "vm-route-gate", [*ready_calls(), *deployed_route_calls(), *no_spoke_nat_calls()]),
            (5, "inspect-no-spoke-nat", no_spoke_nat_calls()),
            (6, "validate-avnm-subnets", [*ready_calls(), *deployed_route_calls(), *no_spoke_nat_calls()]),
            (6, "validate-effective-nic-routes", effective_route_calls()),
        ):
            with self.subTest(step=step):
                result = self.execute(module, step, calls)
                self.assertEqual(result.returncode, 0, result.stderr)
        for index, field, value in (
            (6, "id", avnm_id() + "/routingConfigurations/other"),
            (8, "appliesTo", [{"networkGroupId": routing_group_id("spokeb")}]),
            (9, "destination", {"type": "AddressPrefix", "destinationAddress": "10.10.0.0/16"}),
            (9, "nextHop", {"nextHopType": "VirtualAppliance", "nextHopAddress": "10.0.2.5"}),
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
                self.assertNotEqual(self.execute(6, "validate-avnm-subnets", altered).returncode, 0)
        calls = effective_route_calls()
        for index in (-2, -1):
            altered = copy.deepcopy(calls if index == -1 else calls[:-1])
            route = json.loads(altered[-1]["stdout"])
            route["value"][0]["nextHopIpAddress"] = ["10.0.2.5"]
            altered[-1]["stdout"] = json.dumps(route)
            self.assertNotEqual(self.execute(6, "validate-effective-nic-routes", altered).returncode, 0)
        for index, payload in ((1, {"natGateway": {"id": "foreign"}}),
                               (2, [{"name": "unexpected-nat"}]), (3, [{"name": "unexpected-pip"}])):
            calls = no_spoke_nat_calls()
            altered = copy.deepcopy(calls[:2] if index == 1 else calls[:4])
            altered[index]["stdout"] = json.dumps(payload)
            self.assertNotEqual(self.execute(5, "inspect-no-spoke-nat", altered).returncode, 0)

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
                                        input_text="NO\n", files=self.keyfile).returncode, 0)

    def test_missing_key_stops_preview_and_deploy_without_cloud_mutation(self):
        for name in ("support-preview", "support-deploy"):
            with self.subTest(step=name):
                self.assertNotEqual(self.execute(5, name, input_text="CREATE\n").returncode, 0)

    def test_nat_inspection_shows_settings_for_manual_comparison_without_claiming_pass(self):
        for zone in ("hub",):
            calls = copy.deepcopy(support_cases()[f"inspect-nat-{zone}"])
            data = json.loads(calls[-1]["stdout"])
            data["NSG"] = None
            data["DefaultOutbound"] = True
            calls[-1]["stdout"] = json.dumps(data)
            result = self.execute(5, f"inspect-nat-{zone}", calls)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('"NSG": null', result.stdout)
            self.assertIn('"DefaultOutbound": true', result.stdout)
            self.assertNotIn("PASS", result.stdout)

    def test_shared_watcher_is_preserved_and_malformed_discovery_never_enables(self):
        listing = support_cases()["watcher-enable"][0]
        for value, success in ((["/existing/watcher"], True), (None, False), ({}, False), ("malformed", False)):
            altered = copy.deepcopy(listing)
            altered["stdout"] = json.dumps(value)
            calls = [altered, az(["network", "watcher", "list", "--query",
                                "[?location=='koreacentral'].id", "-o", "json"], ["/existing/watcher"])]
            if success:
                self.assertEqual(self.execute(5, "watcher-enable", calls).returncode, 0)
            else:
                self.assertNotEqual(self.execute(5, "watcher-enable", [altered]).returncode, 0)

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
                calls = routing_cases()[name][:1]
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
                     '\nORIGINAL_LOCATION=koreacentral\n')
        self.assertEqual(self.execute(7, "recovery-input", input_text=f"demo123\n{SUB}\nkoreacentral\n").returncode, 0)
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
            (3, "avnm-create", test_network_docs.avnm_cases()["avnm-create"]),
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
