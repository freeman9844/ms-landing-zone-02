import copy
import json
import re
import unittest
from harness import ROOT, run, account, call, group, STATE, SUB, POOL_ID
from test_ipam_cidrs import fixtures as ipam_fixtures, reads as ipam_reads


def blocks(path):
    pairs = re.findall(r"<!-- exec:([a-z0-9-]+) -->\s*```bash\n(.*?)\n```", path.read_text(), re.S)
    if len(dict(pairs)) != len(pairs):
        raise AssertionError("Duplicate executable block IDs")
    return dict(pairs)


DOCS = {int(path.name[:2]): path for path in (ROOT / "docs").glob("0[2-7]-*.md")}
TAGS = ["--tags", "workshop=lz-beginner", "environment=lab", "runId=demo123", "managedBy=workshop"]
OWNED = {"runId": "demo123", "workshop": "lz-beginner", "environment": "lab", "managedBy": "workshop"}


def workshop_state(run_id="demo123", subscription=SUB):
    return {
        "schemaVersion": 2,
        "topology": "avnm-hub-spoke",
        "runId": run_id,
        "subscriptionId": subscription,
        "location": "koreacentral",
        "resourceGroups": {
            "hub": f"rg-lzbegin-hub-{run_id}",
            "spokea": f"rg-lzbegin-spokea-{run_id}",
            "spokeb": f"rg-lzbegin-spokeb-{run_id}",
        },
    }


def rg(zone, state=STATE):
    return state["resourceGroups"][zone]


def rid(zone, kind, name, state=STATE):
    return f"/subscriptions/{SUB}/resourceGroups/{rg(zone, state)}/providers/{kind}/{name}"


def netid(zone, kind, name, state=STATE):
    return rid(zone, "Microsoft.Network/" + kind, name, state)


def az(args, value="", code=0):
    return call([*args, "--subscription", SUB], value, code)


def vnet(zone, state=STATE):
    return f"vnet-lzbegin-{zone}-{state['runId']}"


def avnm_name(state=STATE):
    return f"avnm-lzbegin-{state['runId']}"


def network_group_name(state=STATE):
    return f"ng-lzbegin-spokes-{state['runId']}"

def routing_group_name(zone, state=STATE):
    return f"ng-lzbegin-route-{zone}-{state['runId']}"

def routing_group_id(zone, state=STATE):
    return avnm_id(state) + "/networkGroups/" + routing_group_name(zone, state)


def connectivity_config_name(state=STATE):
    return f"cc-lzbegin-hub-spoke-{state['runId']}"


def subnet_args(zone):
    return ["-g", rg(zone), "--vnet-name", vnet(zone), "-n",
            "snet-management" if zone == "hub" else "snet-workload"]


def nic(zone, ip):
    return az(["network", "nic", "show", "-g", rg(zone), "-n", f"nic-lzbegin-{zone}-demo123",
               "--query", "ipConfigurations[0].privateIPAddress", "-o", "tsv"], ip)


def foundation_cases():
    cases = {}
    cases["avnm-create"] = avnm_cases()["avnm-create"]
    cases["avnm-ready"] = avnm_cases()["avnm-ready"]
    for zone in ("hub", "spokea", "spokeb"):
        nsg = f"nsg-lzbegin-{zone}-demo123"
        for kind, args in (
            ("nsg", ["network", "nsg", "create", "--resource-group", rg(zone), "--name", nsg,
                     "--location", "koreacentral", *TAGS, "-o", "json"]),
            ("deny", ["network", "nsg", "rule", "create", "--resource-group", rg(zone), "--nsg-name", nsg,
                      "--name", "deny-other-vnet-inbound", "--priority", "4000", "--direction", "Inbound",
                      "--access", "Deny", "--protocol", "*", "--source-address-prefixes", "VirtualNetwork",
                      "--source-port-ranges", "*", "--destination-address-prefixes", "*",
                      "--destination-port-ranges", "*", "-o", "json"]),
        ):
            cases[f"foundation-{zone}-{kind}"] = [az(args)]
        cases[f"foundation-{zone}-vnet"] = [
            az(["network", "vnet", "create", "--resource-group", rg(zone),
                "--name", vnet(zone), "--location", "koreacentral",
                "--ipam-allocations", "[0].number-of-ip-addresses=4096",
                f"[0].id={POOL_ID}", *TAGS, "-o", "json"])]
        for subnet in (("snet-management", "AzureFirewallSubnet") if zone == "hub"
                       else ("snet-workload",)):
            size = 64 if subnet == "AzureFirewallSubnet" else 256
            cmd = ["network", "vnet", "subnet", "create", "--resource-group", rg(zone),
                   "--vnet-name", vnet(zone), "--name", subnet,
                   "--ipam-allocations", f"[0].number-of-ip-addresses={size}",
                   f"[0].id={POOL_ID}"]
            if size == 256:
                cmd.extend(["--network-security-group", nsg, "--default-outbound-access", "false"])
            cmd.extend(["-o", "json"])
            cases[f"foundation-{zone}-{subnet.lower()}"] = [az(cmd)]
        cases[f"foundation-{zone}-rg"] = [
            az(["group", "exists", "--name", rg(zone), "-o", "tsv"], "false"),
            az(["group", "create", "--name", rg(zone), "--location", "koreacentral", *TAGS, "-o", "json"])]
        cases[f"inspect-foundation-{zone}"] = [
            az(["network", "vnet", "show", "-g", rg(zone), "-n", vnet(zone), "--query",
                            "{VNet:name,Address:addressSpace.addressPrefixes,Pool:addressSpace.ipamPoolPrefixAllocations,Subnets:subnets[].{Name:name,Prefix:addressPrefix,Pool:ipamPoolPrefixAllocations,NSG:networkSecurityGroup.id,DefaultOutbound:defaultOutboundAccess},Tags:tags}",
                            "-o", "json"])]
    return cases


def avnm_id(state=STATE):
    return netid("hub", "networkManagers", avnm_name(state), state)


def network_group_id(state=STATE):
    return avnm_id(state) + f"/networkGroups/{network_group_name(state)}"


def connectivity_config_id(state=STATE):
    return avnm_id(state) + f"/connectivityConfigurations/{connectivity_config_name(state)}"


def static_member(name, zone, state=STATE):
    return {
        "name": name,
        "id": network_group_id(state) + f"/staticMembers/{name}",
        "resourceId": netid(zone, "virtualNetworks", vnet(zone, state), state),
        "provisioningState": "Succeeded",
    }


def connectivity_config(state=STATE):
    return {
        "name": connectivity_config_name(state),
        "id": connectivity_config_id(state),
        "connectivityTopology": "HubAndSpoke",
        "deleteExistingPeering": "False",
        "isGlobal": "False",
        "provisioningState": "Succeeded",
        "connectivityCapabilities": {"peeringEnforcement": "Unenforced"},
        "hubs": [{
            "resourceId": netid("hub", "virtualNetworks", vnet("hub", state), state),
            "resourceType": "Microsoft.Network/virtualNetworks",
        }],
        "appliesToGroups": [{
            "networkGroupId": network_group_id(state),
            "groupConnectivity": "None",
            "isGlobal": "False",
            "useHubGateway": "False",
        }],
    }


def effective_configuration(zone, state=STATE, enforcement="Unenforced"):
    return {"value": [dict(connectivity_config(state), targetVirtualNetwork={
        "id": netid(zone, "virtualNetworks", vnet(zone, state), state),
    }, connectivityCapabilities={"peeringEnforcement": enforcement})]}


def avnm_peerings(zone, state=STATE, forwarded=False):
    peerings = {
        "hub": [
            {"name": "avnm-hub-a", "peeringState": "Connected",
             "remoteVirtualNetwork": {"id": netid("spokea", "virtualNetworks", vnet("spokea", state), state)}},
            {"name": "avnm-hub-b", "peeringState": "Connected",
             "remoteVirtualNetwork": {"id": netid("spokeb", "virtualNetworks", vnet("spokeb", state), state)}},
        ],
        "spokea": [
            {"name": "avnm-a-hub", "peeringState": "Connected",
             "remoteVirtualNetwork": {"id": netid("hub", "virtualNetworks", vnet("hub", state), state)}},
        ],
        "spokeb": [
            {"name": "avnm-b-hub", "peeringState": "Connected",
             "remoteVirtualNetwork": {"id": netid("hub", "virtualNetworks", vnet("hub", state), state)}},
        ],
    }
    if forwarded:
        for peering in peerings[zone]:
            peering["allowForwardedTraffic"] = True
            peering["allowVirtualNetworkAccess"] = True
    return peerings[zone]


def enforced_connectivity_calls():
    config = connectivity_config()
    config["connectivityCapabilities"] = {
        "peeringEnforcement": "Enforced",
        "connectedGroupAddressOverlap": "Allowed",
        "connectedGroupPrivateEndpointsScale": "Standard",
    }
    return [
        group("hub"),
        az(["network", "manager", "connect-config", "show", "-g", rg("hub"),
            "--network-manager-name", avnm_name(), "--configuration-name",
            connectivity_config_name(), "-o", "json"], config),
        az(["network", "manager", "list-deploy-status", "-g", rg("hub"),
            "--network-manager-name", avnm_name(), "--deployment-types",
            "Connectivity", "--regions", "koreacentral", "-o", "json"],
           [{"deploymentType": "Connectivity", "region": "koreacentral",
             "commitTime": "2026-01-01T00:00:00Z", "deploymentStatus": "Deployed",
             "configurationIds": [connectivity_config_id()]}]),
        group("spokea"),
        az(["rest", "--method", "post", "--url",
            f"{netid('spokea', 'virtualNetworks', vnet('spokea'))}"
            "/listNetworkManagerEffectiveConnectivityConfigurations?api-version=2025-05-01",
            "--body", "{}", "-o", "json"],
           {"skipToken": "", "value": [{
               "id": connectivity_config_id(),
               "properties": {key: value for key, value in
                              effective_configuration("spokea", enforcement="Enforced")["value"][0].items()
                              if key != "id"},
           }]}),
        group("spokeb"),
        az(["rest", "--method", "post", "--url",
            f"{netid('spokeb', 'virtualNetworks', vnet('spokeb'))}"
            "/listNetworkManagerEffectiveConnectivityConfigurations?api-version=2025-05-01",
            "--body", "{}", "-o", "json"],
           {"skipToken": "", "value": [{
               "id": connectivity_config_id(),
               "properties": {key: value for key, value in
                              effective_configuration("spokeb", enforcement="Enforced")["value"][0].items()
                              if key != "id"},
           }]}),
        *(entry for zone in ("hub", "spokea", "spokeb")
          for entry in (group(zone),
                        az(["network", "vnet", "peering", "list", "-g", rg(zone),
                            "--vnet-name", vnet(zone), "-o", "json"],
                           avnm_peerings(zone, forwarded=True)))),
    ]


def owned_group_call(zone, state=STATE):
    name = rg(zone, state)
    return call(["group", "show", "--name", name, "-o", "json"], {
        "name": name,
        "id": f"/subscriptions/{SUB}/resourceGroups/{name}",
        "tags": {
            "workshop": "lz-beginner",
            "environment": "lab",
            "runId": state["runId"],
            "managedBy": "workshop",
        },
    })


def avnm_cases():
    hub = netid("hub", "virtualNetworks", vnet("hub"))
    spokea = netid("spokea", "virtualNetworks", vnet("spokea"))
    spokeb = netid("spokeb", "virtualNetworks", vnet("spokeb"))
    manager = avnm_id()
    manager_body = {
        "location": "koreacentral",
        "properties": {
            "description": "Beginner Hub and Spoke connectivity",
            "networkManagerScopes": {"subscriptions": [f"/subscriptions/{SUB}"]},
            "networkManagerScopeAccesses": ["Connectivity", "SecurityAdmin", "Routing"],
        },
    }
    hubs = json.dumps([{
        "resourceId": hub,
        "resourceType": "Microsoft.Network/virtualNetworks",
    }], separators=(",", ":"))
    groups = json.dumps([{
        "networkGroupId": network_group_id(),
        "groupConnectivity": "None",
        "isGlobal": False,
        "useHubGateway": False,
    }], separators=(",", ":"))
    return {
        "avnm-create": [
            az([
                "rest", "--method", "put",
                "--url", f"{manager}?api-version=2025-01-01",
                "--body", json.dumps(manager_body, separators=(",", ":")),
                "-o", "json",
            ], {"id": manager, "properties": {
                **manager_body["properties"], "provisioningState": "Succeeded"}}),
        ],
        "avnm-ready": [
            az(["network", "manager", "show", "--name", avnm_name(),
                "--resource-group", rg("hub"), "-o", "json"],
               {"id": manager, **manager_body["properties"], "provisioningState": "Succeeded"}),
        ],
        "network-group-create": [
            az([
                "network", "manager", "group", "create",
                "--name", "ng-lzbegin-spokes-demo123",
                "--network-manager-name", "avnm-lzbegin-demo123",
                "--resource-group", rg("hub"),
                "--description", "Workshop spoke virtual networks",
                "-o", "json",
            ]),
        ],
        "member-spokea": [
            az([
                "network", "manager", "group", "static-member", "create",
                "--name", "spokea",
                "--network-group", "ng-lzbegin-spokes-demo123",
                "--network-manager", "avnm-lzbegin-demo123",
                "--resource-group", rg("hub"),
                "--resource-id", spokea,
                "-o", "json",
            ]),
        ],
        "member-spokeb": [
            az([
                "network", "manager", "group", "static-member", "create",
                "--name", "spokeb",
                "--network-group", "ng-lzbegin-spokes-demo123",
                "--network-manager", "avnm-lzbegin-demo123",
                "--resource-group", rg("hub"),
                "--resource-id", spokeb,
                "-o", "json",
            ]),
        ],
        "route-group-spokea-create": [
            az(["network", "manager", "group", "create",
                "--name", routing_group_name("spokea"),
                "--network-manager-name", avnm_name(), "--resource-group", rg("hub"),
                "--description", "Spoke A routing scope", "-o", "json"]),
        ],
        "route-group-spokeb-create": [
            az(["network", "manager", "group", "create",
                "--name", routing_group_name("spokeb"),
                "--network-manager-name", avnm_name(), "--resource-group", rg("hub"),
                "--description", "Spoke B routing scope", "-o", "json"]),
        ],
        "route-member-spokea": [
            az(["network", "manager", "group", "static-member", "create",
                "--name", "spokea", "--network-group", routing_group_name("spokea"),
                "--network-manager", avnm_name(), "--resource-group", rg("hub"),
                "--resource-id", spokea, "-o", "json"]),
        ],
        "route-member-spokeb": [
            az(["network", "manager", "group", "static-member", "create",
                "--name", "spokeb", "--network-group", routing_group_name("spokeb"),
                "--network-manager", avnm_name(), "--resource-group", rg("hub"),
                "--resource-id", spokeb, "-o", "json"]),
        ],
        "connectivity-config-create": [
            az([
                "network", "manager", "connect-config", "create",
                "--configuration-name", "cc-lzbegin-hub-spoke-demo123",
                "--description", "AVNM managed beginner hub and spoke",
                "--applies-to-groups", groups,
                "--hubs", hubs,
                "--connectivity-topology", "HubAndSpoke",
                "--delete-existing-peering", "False",
                "--is-global", "False",
                "--network-manager-name", "avnm-lzbegin-demo123",
                "--resource-group", rg("hub"),
                "-o", "json",
            ]),
        ],
        "connectivity-commit": [az([
            "network", "manager", "post-commit",
            "--network-manager-name", "avnm-lzbegin-demo123",
            "--commit-type", "Connectivity",
            "--configuration-ids", connectivity_config_id(),
            "--target-locations", "koreacentral",
            "--resource-group", rg("hub"),
            "-o", "json",
        ])],
        "inspect-avnm-peerings-hub": [az([
            "network", "vnet", "peering", "list",
            "-g", rg("hub"),
            "--vnet-name", vnet("hub"),
            "-o", "json",
        ], avnm_peerings("hub"))],
    }


def connectivity_cases():
    return {name: calls for name, calls in avnm_cases().items()
            if name != "avnm-create"}


def recase_ids(calls, transform):
    """Vary Azure ID casing without changing tags, names, or CLI option names."""
    def convert(value):
        if isinstance(value, str):
            return transform(value) if value.lower().startswith("/subscriptions/") else value
        if isinstance(value, list):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        return value

    result = copy.deepcopy(calls)
    for item in result:
        try:
            payload = json.loads(item["stdout"])
        except json.JSONDecodeError:
            item["stdout"] = convert(item["stdout"])
        else:
            item["stdout"] = json.dumps(convert(payload))
        item["argv"] = convert(item["argv"])
    return result


def foreign_ids(resource_id):
    parts = resource_id.split("/")
    # Subscription, RG, provider namespace, resource type and name must all match.
    for index in (2, 4, 6, 7, 8):
        changed = parts.copy()
        changed[index] += "-foreign"
        yield "/".join(changed)
    yield "/unexpected-prefix" + resource_id
    yield resource_id + "/unexpected-child"


def preparation_calls(module, state=STATE):
    calls = [account()]
    if module in (3, 4, 5, 6):
        calls.extend(owned_group_call(zone, state) for zone in ("hub", "spokea", "spokeb"))
        vnets, subnets = ipam_fixtures()
        calls.extend(ipam_reads(vnets, subnets))
    return calls


class NetworkDocsTests(unittest.TestCase):
    def test_fresh_foundation_creation_uses_direct_cli_commands(self):
        cases = foundation_cases()
        for zone in ("hub", "spokea", "spokeb"):
            suffixes = ("vnet", "snet-management", "azurefirewallsubnet") if zone == "hub" \
                else ("vnet", "snet-workload")
            for suffix in suffixes:
                name = f"foundation-{zone}-{suffix}"
                with self.subTest(step=name):
                    result = self.execute(2, name, [cases[name][-1]])
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_module_02_partial_creation_has_separate_guarded_resume_steps(self):
        steps = blocks(DOCS[2])
        for zone, subnet_names in (("hub", ("snet-management", "AzureFirewallSubnet")),
                                   ("spokea", ("snet-workload",)),
                                   ("spokeb", ("snet-workload",))):
            with self.subTest(zone=zone):
                vnet_step = f"foundation-{zone}-vnet"
                self.assertIn(vnet_step, steps)
                self.assertEqual(steps[vnet_step].count("az network vnet create"), 1)
                self.assertNotIn("az network vnet subnet create", steps[vnet_step])
                for subnet in subnet_names:
                    step = f"foundation-{zone}-{subnet.lower()}"
                    self.assertIn(step, steps)
                    self.assertEqual(steps[step].count("az network vnet subnet create"), 1)
                    self.assertNotIn("az network vnet create", steps[step])
                    self.assertLess(list(steps).index(vnet_step), list(steps).index(step))

    def test_firewall_rules_and_routing_use_allocated_ipam_prefixes(self):
        actions = blocks(DOCS[4])
        for name in ("firewall-management-rule", "firewall-egress-rule"):
            with self.subTest(name=name):
                self.assertIn('"$SPOKEA_SUBNET_CIDR"', actions[name])
                self.assertIn('"$SPOKEB_SUBNET_CIDR"', actions[name])
        http = actions["firewall-http-rule"]
        self.assertIn('--source-addresses "$SPOKEA_SUBNET_CIDR"', http)
        self.assertIn('--destination-addresses "$SPOKEB_SUBNET_CIDR"', http)
        self.assertNotIn("inspect-firewall-rules", actions)
        self.assertNotIn("firewall-ready", actions)
        self.assertIn("firewall_ready_ip", actions["forward-hub-to-spokea"])
        safety = (ROOT / "scripts/workshop-safety.sh").read_text()
        self.assertIn('--arg a "$SPOKEA_SUBNET_CIDR"', safety)
        self.assertIn('--arg b "$SPOKEB_SUBNET_CIDR"', safety)
        for zone, remote in (("spokea", "SPOKEB"), ("spokeb", "SPOKEA")):
            with self.subTest(zone=zone):
                rule = actions[f"routing-rule-{zone}-other"]
                self.assertIn(f'--arg address "${remote}_VNET_CIDR"', rule)
                self.assertIn("destination_address:$address", rule)
                self.assertIn('--arg ip "$fw_ip"', rule)
                self.assertIn("next_hop_address:$ip", rule)
                self.assertIn(f'other-spoke "${remote}_VNET_CIDR"', rule)
        self.assertIn('"$FIREWALL_SUBNET_CIDR"', actions["inspect-firewall"])
        self.assertIn('"$SPOKEB_VNET_CIDR"', blocks(DOCS[5])["effective-vm-routes"])
        self.assertIn('"$HUB_SUBNET_CIDR"', blocks(DOCS[5])["read-vm-ips"])
        self.assertNotRegex("\n".join(actions.values()), r"10\.(?:0|10|20)\.\d+\.\d+/\d+")

    def test_module_03_only_chains_dependent_connectivity_creation_commands(self):
        for name, script in blocks(DOCS[3]).items():
            with self.subTest(step=name):
                if name == "connectivity-config-create":
                    self.assertIn("&&", script)
                else:
                    self.assertNotIn("&&", script)

    def test_configuration_waits_for_both_static_members_before_create(self):
        calls = [az([
            "network", "manager", "group", "static-member", "list",
            "--network-group", network_group_name(),
            "--network-manager", avnm_name(),
            "--resource-group", rg("hub"), "-o", "json",
        ], [static_member("spokea", "spokea"), static_member("spokeb", "spokeb")])]
        result = self.execute(3, "inspect-static-members", [
            dict(calls[0], stdout=json.dumps([static_member("spokea", "spokea")])),
            calls[0],
        ])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_configuration_preflight_checks_hub_separately_and_create_uses_verified_ids(self):
        hub_call = az(["network", "vnet", "show", "-g", rg("hub"), "-n", vnet("hub"),
                       "--query", "id", "-o", "tsv"], netid("hub", "virtualNetworks", vnet("hub")))
        result = self.execute(3, "inspect-avnm-hub", [hub_call])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(netid("hub", "virtualNetworks", vnet("hub")), result.stdout)
        result = self.execute(3, "inspect-avnm-hub", [dict(hub_call, stdout="unexpected")])
        self.assertNotEqual(result.returncode, 0)
        script = blocks(DOCS[3])["connectivity-config-create"]
        self.assertNotIn("static-member list", script)
        self.assertNotIn("network vnet show", script)
        self.assertIn("&&", script)

    def test_configuration_creation_follows_member_and_hub_checks(self):
        steps = blocks(DOCS[3])
        members = az([
            "network", "manager", "group", "static-member", "list",
            "--network-group", network_group_name(), "--network-manager", avnm_name(),
            "--resource-group", rg("hub"), "-o", "json",
        ], [static_member("spokea", "spokea"), static_member("spokeb", "spokeb")])
        hub = az(["network", "vnet", "show", "-g", rg("hub"), "-n", vnet("hub"),
                  "--query", "id", "-o", "tsv"], netid("hub", "virtualNetworks", vnet("hub")))
        actions = ["prepare-03", "inspect-static-members", "inspect-avnm-hub", "connectivity-config-create"]
        script = 'export STATE_FILE=state.json\n' + " || exit 1\n".join(steps[action] for action in actions)
        result = run(script, [*preparation_calls(3), members, hub,
                              *avnm_cases()["connectivity-config-create"]])
        self.assertEqual(result.returncode, 0, result.stderr)
        result = run(script, [*preparation_calls(3),
                              dict(members, stdout=json.dumps([static_member("hub", "hub")]))])
        self.assertNotEqual(result.returncode, 0)

    def execute(self, module, name, calls=(), input_text=None, files=None, prefix="", state=STATE):
        steps = blocks(DOCS[module])
        self.assertIn(f"prepare-{module:02}", steps, "Module needs one common preparation block")
        self.assertIn(name, steps, "Missing separate teaching action")
        script = 'export STATE_FILE=state.json\n' + steps[f"prepare-{module:02}"] + "\n"
        script += 'prepared=$?\nif [[ "$prepared" == 0 ]]; then\n' + prefix + steps[name] + '\nelse\nfalse\nfi\n'
        script += 'status=$?\nprintf "SHELL_ALIVE\\n"\nexit "$status"'
        result = run(script, [*preparation_calls(module, state), *calls], input_text=input_text, files=files)
        self.assertIn("SHELL_ALIVE", result.stdout, result.stderr)
        return result

    def test_every_module_preparation_rejects_wrong_subscription_without_exiting(self):
        for module, path in DOCS.items():
            with self.subTest(module=module):
                steps = blocks(path)
                self.assertIn(f"prepare-{module:02}", steps)
                result = run('export STATE_FILE=state.json\n' + steps[f"prepare-{module:02}"] +
                             '\nstatus=$?\nprintf "ALIVE\\n"\nexit "$status"',
                             [call(["account", "show", "--query", "id", "-o", "tsv"], "wrong")])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ALIVE", result.stdout)
                self.assertIn("Subscription mismatch", result.stderr)

    def test_every_module_preparation_rejects_invalid_state(self):
        for module, path in DOCS.items():
            with self.subTest(module=module):
                steps = blocks(path)
                self.assertIn(f"prepare-{module:02}", steps)
                result = run('export STATE_FILE=state.json\n' + steps[f"prepare-{module:02}"],
                             files={"state.json": '{"schemaVersion":999}'})
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Invalid or unreadable", result.stderr)

    def test_each_preparation_prompts_for_existing_state_only_when_path_is_unset(self):
        for module, path in DOCS.items():
            with self.subTest(module=module):
                prepare = blocks(path)[f"prepare-{module:02}"]
                result = run(prepare + '\nprintf "TARGET=%s:%s\\n" "$STATE_FILE" "$RUN_ID"\n',
                             preparation_calls(module),
                             files={".workshop-state/demo123.json": json.dumps(STATE)},
                             input_text=".workshop-state/demo123.json\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("TARGET=.workshop-state/demo123.json:demo123", result.stdout)
                result = run('export STATE_FILE=state.json\n' + prepare +
                             '\nprintf "TARGET=%s:%s\\n" "$STATE_FILE" "$RUN_ID"\n',
                             preparation_calls(module))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("TARGET=state.json:demo123", result.stdout)

    def test_every_module_lists_state_filenames_before_requesting_missing_path(self):
        for module, path in DOCS.items():
            with self.subTest(module=module):
                prepare = blocks(path)[f"prepare-{module:02}"]
                capture_prompt = 'read() { printf "PROMPT=%s\\n" "$2"; builtin read "$@"; }\n'
                result = run(capture_prompt + prepare + '\nprintf "TARGET=%s:%s\\n" "$STATE_FILE" "$RUN_ID"\n',
                             preparation_calls(module),
                             files={".workshop-state/demo123.json": json.dumps(STATE)},
                             input_text=".workshop-state/demo123.json\n")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(result.stdout.startswith("demo123.json\n"), result.stdout)
                self.assertIn("PROMPT=기존 상태 파일 경로 (예: .workshop-state/demo123.json): ", result.stdout)
                self.assertIn("TARGET=.workshop-state/demo123.json:demo123", result.stdout)

                uploaded = run(capture_prompt + prepare + '\nprintf "TARGET=%s:%s\\n" "$STATE_FILE" "$RUN_ID"\n',
                               preparation_calls(module),
                               files={"uploaded/state.json": json.dumps(STATE)},
                               input_text="uploaded/state.json\n")
                self.assertEqual(uploaded.returncode, 0, uploaded.stderr)
                self.assertIn("PROMPT=기존 상태 파일 경로 (예: .workshop-state/<실행 ID>.json): ", uploaded.stdout)
                self.assertIn("TARGET=uploaded/state.json:demo123", uploaded.stdout)

    def test_module04_example_does_not_choose_a_run_when_multiple_state_files_exist(self):
        prepare = blocks(DOCS[4])["prepare-04"]
        script = 'read() { printf "PROMPT=%s\\n" "$2"; builtin read "$@"; }\n'
        result = run(script + prepare + '\nprintf "TARGET=%s:%s\\n" "$STATE_FILE" "$RUN_ID"\n',
                     preparation_calls(4),
                     files={".workshop-state/abc123.json": "{}",
                            ".workshop-state/demo123.json": json.dumps(STATE)},
                     input_text=".workshop-state/demo123.json\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PROMPT=기존 상태 파일 경로 (예: .workshop-state/abc123.json): ", result.stdout)
        self.assertIn("TARGET=.workshop-state/demo123.json:demo123", result.stdout)

    def test_preparation_rejects_wrong_path_and_cancelled_input_without_stale_targets(self):
        for module, path in DOCS.items():
            for input_text in ("./workshop-state/demo123.json\n", "\n", ""):
                with self.subTest(module=module, input=input_text):
                    prepare = blocks(path)[f"prepare-{module:02}"]
                    script = 'source scripts/workshop-common.sh\nload_run state.json && zone_context hub\n'
                    script += 'unset STATE_FILE\n' + prepare + '''
status=$?
printf 'PREPARE_STATUS=%s\\n' "$status"
for name in RUN_ID SUBSCRIPTION_ID LOCATION RG_HUB RG_SPOKEA RG_SPOKEB \
AVNM NETWORK_GROUP CONNECTIVITY_CONFIG AVNM_ID NETWORK_GROUP_ID CONNECTIVITY_CONFIG_ID \
RG VNET VM NSG; do
  [[ ! -v "$name" ]] || { printf 'STALE:%s\\n' "$name"; exit 91; }
done
printf 'SHELL_ALIVE\\n'
'''
                    result = run(script, input_text=input_text)
                    self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                    self.assertIn("PREPARE_STATUS=1\nSHELL_ALIVE", result.stdout)
                    self.assertIn("ERROR:", result.stderr)

    def test_failed_preparation_does_not_leave_a_previous_workshop_target(self):
        for module, path in DOCS.items():
            with self.subTest(module=module):
                script = 'source scripts/workshop-common.sh\nload_run state.json\nzone_context hub\n'
                script += 'export STATE_FILE=missing.json\n' + blocks(path)[f"prepare-{module:02}"]
                script += '''
status=$?
printf 'PREPARE_STATUS=%s\\n' "$status"
for name in RUN_ID SUBSCRIPTION_ID LOCATION RG_HUB RG_SPOKEA RG_SPOKEB \
AVNM NETWORK_GROUP CONNECTIVITY_CONFIG AVNM_ID NETWORK_GROUP_ID CONNECTIVITY_CONFIG_ID \
RG VNET VM NSG; do
  [[ ! -v "$name" ]] || { printf 'STALE:%s\\n' "$name"; exit 91; }
done
printf 'SHELL_ALIVE\\n'
'''
                result = run(script)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertIn("PREPARE_STATUS=1\nSHELL_ALIVE", result.stdout)

    def test_foundation_and_avnm_actions_are_independent_and_subscription_scoped(self):
        for module, cases in ((2, foundation_cases()), (3, connectivity_cases())):
            for name, calls in cases.items():
                with self.subTest(module=module, step=name):
                    result = self.execute(module, name, calls)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_module_02_creates_manager_before_any_pool_allocation(self):
        steps = blocks(DOCS[2])
        order = list(steps)
        self.assertLess(order.index("foundation-hub-rg"), order.index("avnm-create"))
        self.assertLess(order.index("avnm-ready"), order.index("foundation-spokea-rg"))
        for zone in ("hub", "spokea", "spokeb"):
            self.assertLess(order.index(f"foundation-{zone}-nsg"), order.index(f"foundation-{zone}-vnet"))
            script = steps[f"foundation-{zone}-vnet"]
            self.assertNotIn("infra/workshop-ipam-vnet.bicep", script)
            self.assertNotIn("az deployment group create", script)
            self.assertIn("az network vnet create", script)
            self.assertNotIn("az network vnet subnet create", script)
            self.assertNotIn("--address-prefixes 10.", script)
            self.assertNotIn("rg-lzbegin-ipam", script)
        self.assertNotIn("network manager list", blocks(DOCS[3])["avnm-ready"])
        self.assertNotIn("avnm-create", blocks(DOCS[3]))

    def test_first_creation_runs_with_fresh_ids_without_inventory(self):
        for module, preview, creation in (
            (2, "inspect-avnm", "avnm-create"),
            (3, "inspect-network-groups", "network-group-create"),
            (3, "inspect-members-before-spokea", "member-spokea"),
            (3, "inspect-members-before-spokeb", "member-spokeb"),
        ):
            with self.subTest(action=creation):
                self.assertNotIn(preview, blocks(DOCS[module]))
                result = self.execute(module, creation, avnm_cases()[creation])
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_module_03_checks_hub_peerings_and_defers_spoke_validation_to_module_04(self):
        steps = blocks(DOCS[3])
        self.assertIn("inspect-avnm-peerings-hub", steps)
        for old in ("effective-hub", "effective-spokea", "effective-spokeb",
                    "inspect-avnm-peerings-spokea", "inspect-avnm-peerings-spokeb"):
            self.assertNotIn(old, steps)
        routing = blocks(DOCS[4])
        for direction in ("hub-to-spokea", "spokea-to-hub", "hub-to-spokeb", "spokeb-to-hub"):
            self.assertIn(f"forward-{direction}", routing)
        self.assertIn("assert_enforced_connectivity", routing["inspect-enforced-connectivity"])

    def test_firewall_inspection_explains_missing_common_preparation(self):
        result = run(blocks(DOCS[4])["inspect-firewall"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("모듈 04 공통 준비", result.stderr)

    def test_firewall_diagnostics_explains_missing_common_preparation(self):
        result = run(blocks(DOCS[4])["firewall-diagnostics"])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("모듈 04 공통 준비", result.stderr)

    def test_prerequisite_lookup_failures_stop_before_mutation(self):
        for module, cases in ((2, foundation_cases()), (3, connectivity_cases())):
            for name, calls in cases.items():
                for index in range(len(calls) - 1):
                    with self.subTest(step=name, failure=index):
                        failed = copy.deepcopy(calls[:index + 1])
                        failed[-1].update(returncode=1, stdout="")
                        result = self.execute(module, name, failed)
                        self.assertNotEqual(result.returncode, 0)

    def test_rg_collision_never_retags_existing_group(self):
        for zone in ("hub", "spokea", "spokeb"):
            for owned in (True, False):
                with self.subTest(zone=zone, owned=owned):
                    ownership = group(zone)
                    if not owned:
                        ownership["stdout"] = json.dumps({"id": "foreign", "tags": {}})
                    result = self.execute(2, f"foundation-{zone}-rg", [
                        az(["group", "exists", "--name", rg(zone), "-o", "tsv"], "true"), ownership])
                    self.assertEqual(result.returncode == 0, owned, result.stderr)

    def test_reused_owned_group_remains_unchanged_before_other_creation(self):
        steps = blocks(DOCS[2])
        cases = foundation_cases()
        for zone in ("hub", "spokea", "spokeb"):
            with self.subTest(zone=zone):
                names = [f"foundation-{zone}-{kind}" for kind in ("rg", "nsg", "vnet")]
                script = 'export STATE_FILE=state.json\n'
                script += " &&\n".join([steps["prepare-02"], *(steps[name] for name in names)])
                calls = [account(), az(["group", "exists", "--name", rg(zone), "-o", "tsv"], "true"), group(zone)]
                for name in names[1:]:
                    calls.extend(cases[name])
                result = run(script, calls)
                self.assertEqual(result.returncode, 0, result.stderr)

    def test_only_preparation_and_state_changing_safety_boundaries_keep_assertions(self):
        for module, path in DOCS.items():
            for name, script in blocks(path).items():
                with self.subTest(module=module, step=name):
                    assertions = re.findall(r"\bassert_\w+", script)
                    if re.fullmatch(r"prepare-\d\d", name):
                        expected = ["assert_subscription"]
                        if module in (3, 4, 5, 6):
                            expected.extend(["assert_owned_rg"] * 3)
                    elif module == 2 and name.endswith("-rg"):
                        expected = ["assert_owned_rg"]
                    elif module == 2 and name == "inspect-foundation-cidrs":
                        expected = ["assert_owned_rg"] * 3
                    else:
                        expected = {
                            (4, "inspect-firewall"): ["assert_ipv4_in_subnet"] * 2,
                            (4, "firewall-diagnostics"): ["assert_resource_id"] * 3,
                            (4, "enforce-peering"): ["assert_forwarded_peerings",
                                                    "assert_connectivity_config_ready",
                                                    "assert_connectivity_config_ready"],
                            (4, "commit-enforced-connectivity"): ["assert_forwarded_peerings",
                                                                  "assert_connectivity_config_ready"],
                            (4, "forward-hub-to-spokea"): ["assert_peering_forwarded"],
                            (4, "forward-spokea-to-hub"): ["assert_peering_forwarded"],
                            (4, "forward-hub-to-spokeb"): ["assert_peering_forwarded"],
                            (4, "forward-spokeb-to-hub"): ["assert_peering_forwarded"],
                            (4, "inspect-enforced-connectivity"): ["assert_enforced_connectivity"],
                            (4, "routing-config-create"): ["assert_routing_creation_result"],
                            (4, "routing-collection-spokea"): ["assert_routing_collection_result"],
                            (4, "routing-collection-spokeb"): ["assert_routing_collection_result"],
                            (4, "routing-rule-spokea-other"): ["assert_routing_rule_result"],
                            (4, "routing-rule-spokea-internet"): ["assert_routing_rule_result"],
                            (4, "routing-rule-spokeb-other"): ["assert_routing_rule_result"],
                            (4, "routing-rule-spokeb-internet"): ["assert_routing_rule_result"],
                            (4, "routing-commit"): ["assert_unattached_workload_subnets"],
                            (4, "inspect-avnm-routing-subnets"): ["assert_avnm_routes_ready",
                                                                   "assert_no_spoke_nat"],
                            (5, "vm-route-gate"): ["assert_enforced_connectivity",
                                                    "assert_avnm_routes_ready", "assert_no_spoke_nat"],
                            (5, "read-vm-ips"): ["assert_ipv4_in_subnet"] * 3,
                            (5, "inspect-security-rules"): ["assert_admin_rules_ready"],
                            (6, "firewall-deny"): ["assert_no_spoke_nat"],
                        }.get((module, name), [])
                    self.assertEqual(assertions, expected)
        for module in (3,):
            self.assertNotIn("source scripts/workshop-safety.sh", DOCS[module].read_text())

    def test_avnm_creation_propagates_rest_failure(self):
        calls = avnm_cases()["avnm-create"]
        result = self.execute(2, "avnm-create",
                              [dict(calls[-1], returncode=1, stdout="", stderr="create failed")])
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("create failed", result.stderr)

    def test_avnm_readiness_requires_flattened_cli_scope_and_full_id(self):
        valid = avnm_cases()["avnm-ready"][0]
        self.assertEqual(self.execute(3, "avnm-ready", [valid]).returncode, 0)
        response = json.loads(valid["stdout"])
        for payload in (
            {"id": response["id"], "properties": {
                "provisioningState": "Succeeded",
                "networkManagerScopes": response["networkManagerScopes"],
                "networkManagerScopeAccesses": response["networkManagerScopeAccesses"],
            }},
            dict(response, id=response["id"] + "/unexpected-child"),
            dict(response, networkManagerScopes={"subscriptions": [
                "/subscriptions/99999999-9999-9999-9999-999999999999"]}),
            dict(response, networkManagerScopeAccesses=["Connectivity", "SecurityAdmin"]),
            dict(response, provisioningState="Updating"),
        ):
            with self.subTest(payload=payload):
                altered = dict(valid, stdout=json.dumps(payload))
                result = self.execute(3, "avnm-ready", [altered])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR:", result.stderr)

    def test_avnm_readiness_accepts_scope_resource_id_case_variants(self):
        calls = avnm_cases()["avnm-ready"]
        response = json.loads(calls[-1]["stdout"])
        response["networkManagerScopes"]["subscriptions"][0] = (
            response["networkManagerScopes"]["subscriptions"][0].upper())
        result = self.execute(2, "avnm-ready",
                              [dict(calls[-1], stdout=json.dumps(response))])
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_state_restores_distinct_spoke_routing_group_ids(self):
        script = ('source scripts/workshop-common.sh\nload_run state.json\n'
                  'printf "%s\\n%s\\n" "$ROUTE_GROUP_A_ID" "$ROUTE_GROUP_B_ID"\n')
        result = run(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(),
                         [routing_group_id("spokea"), routing_group_id("spokeb")])

    def test_member_lists_reject_unapproved_topology_membership(self):
        valid = [static_member("spokea", "spokea"), static_member("spokeb", "spokeb")]
        scenarios = (
            ("hub-present", [*valid, static_member("hub", "hub")]),
            ("missing-spokea", [static_member("spokeb", "spokeb")]),
            ("missing-spokeb", [static_member("spokea", "spokea")]),
            ("foreign-subscription", [dict(static_member("spokea", "spokea"),
                                           resourceId=netid("spokea", "virtualNetworks", vnet("spokea")).replace(
                                               SUB, "99999999-9999-9999-9999-999999999999")),
                                     static_member("spokeb", "spokeb")]),
            ("foreign-rg", [dict(static_member("spokea", "spokea"),
                                 resourceId=netid("spokea", "virtualNetworks", vnet("spokea")).replace(
                                     rg("spokea"), rg("spokea") + "-foreign")),
                            static_member("spokeb", "spokeb")]),
        )
        for label, members in scenarios:
            with self.subTest(case=label):
                calls = [az([
                    "network", "manager", "group", "static-member", "list",
                    "--network-group", "ng-lzbegin-spokes-demo123",
                    "--network-manager", "avnm-lzbegin-demo123",
                    "--resource-group", rg("hub"),
                    "-o", "json",
                ], members)]
                result = self.execute(3, "inspect-static-members", calls * 12 if label.startswith("missing-") else calls)
                self.assertNotEqual(result.returncode, 0)

    def test_foundation_and_avnm_propagate_final_cli_errors(self):
        for module, cases in ((2, foundation_cases()), (3, connectivity_cases())):
            for name, calls in cases.items():
                with self.subTest(module=module, step=name):
                    failed = copy.deepcopy(calls)
                    failed[-1].update(returncode=1, stdout="", stderr="Azure request failed")
                    result = self.execute(module, name, failed)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("Azure request failed", result.stderr)
