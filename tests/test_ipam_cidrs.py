import unittest
import re

from harness import POOL_ID, ROOT, STATE, SUB, account, call, group, run, vnet_id

PREFIXES = {
    "hub": ("172.20.0.0/20", "172.20.0.0/24"),
    "spokea": ("172.20.16.0/20", "172.20.16.0/24"),
    "spokeb": ("172.20.32.0/20", "172.20.32.0/24"),
}
EXPORTS = ("HUB_VNET_CIDR", "SPOKEA_VNET_CIDR", "SPOKEB_VNET_CIDR",
           "HUB_SUBNET_CIDR", "SPOKEA_SUBNET_CIDR", "SPOKEB_SUBNET_CIDR",
           "FIREWALL_SUBNET_CIDR")
CIDR_ENV = ('HUB_VNET_CIDR=172.20.0.0/20 SPOKEA_VNET_CIDR=172.20.16.0/20 '
            'SPOKEB_VNET_CIDR=172.20.32.0/20 HUB_SUBNET_CIDR=172.20.0.0/24 '
            'SPOKEA_SUBNET_CIDR=172.20.16.0/24 SPOKEB_SUBNET_CIDR=172.20.32.0/24 '
            'FIREWALL_SUBNET_CIDR=172.20.1.0/26; ')


def blocks(path):
    return dict(re.findall(r"<!-- exec:([a-z0-9-]+) -->\s*```bash\n(.*?)\n```",
                           path.read_text(), re.S))


def allocation(size):
    return [{"numberOfIpAddresses": str(size), "pool": {"id": POOL_ID}}]


def fixtures():
    vnets, subnets = {}, {}
    for zone, (vnet_prefix, subnet_prefix) in PREFIXES.items():
        vnets[zone] = {
            "id": vnet_id(zone), "name": f"vnet-lzbegin-{zone}-demo123",
            "provisioningState": "Succeeded",
            "tags": {"workshop": "lz-beginner", "environment": "lab",
                     "runId": "demo123", "managedBy": "workshop"},
            "addressSpace": {"addressPrefixes": [vnet_prefix],
                             "ipamPoolPrefixAllocations": allocation(4096)},
        }
        name = "snet-management" if zone == "hub" else "snet-workload"
        subnets[(zone, name)] = {
            "id": f"{vnet_id(zone)}/subnets/{name}",
            "name": name, "provisioningState": "Succeeded", "addressPrefix": subnet_prefix,
            "ipamPoolPrefixAllocations": allocation(256),
        }
    subnets[("hub", "AzureFirewallSubnet")] = {
        "id": f"{vnet_id('hub')}/subnets/AzureFirewallSubnet",
        "name": "AzureFirewallSubnet", "provisioningState": "Succeeded",
        "addressPrefix": "172.20.1.0/26",
        "ipamPoolPrefixAllocations": allocation(64),
    }
    return vnets, subnets


def reads(vnets, subnets, error=None):
    calls = []
    for zone in PREFIXES:
        rg = STATE["resourceGroups"][zone]
        vnet = f"vnet-lzbegin-{zone}-demo123"
        calls.append(call(["network", "vnet", "show", "--resource-group", rg,
                           "--name", vnet, "-o", "json", "--subscription", SUB],
                          vnets[zone], **({"code": 1, "stderr": "network error"}
                                         if error == ("vnet", zone) else {})))
    for zone, name in (("hub", "snet-management"), ("hub", "AzureFirewallSubnet"),
                       ("spokea", "snet-workload"), ("spokeb", "snet-workload")):
        calls.append(call(["network", "vnet", "subnet", "show", "--resource-group",
                           STATE["resourceGroups"][zone], "--vnet-name",
                           f"vnet-lzbegin-{zone}-demo123", "--name", name, "-o",
                           "json", "--subscription", SUB], subnets[(zone, name)],
                          **({"code": 1, "stderr": "network error"}
                             if error == ("subnet", zone, name) else {})))
    if error:
        index = 0 if error[0] == "vnet" else 3 + [
            ("hub", "snet-management"), ("hub", "AzureFirewallSubnet"),
            ("spokea", "snet-workload"), ("spokeb", "snet-workload"),
        ].index(error[1:])
        return calls[:index + 1]
    return calls


class LiveCidrTests(unittest.TestCase):
    def resolve(self, calls, success=False):
        script = ('source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; '
                  'source "$WORKSHOP_ROOT/scripts/workshop-ipam.sh"; '
                  'load_run state.json || exit 1; '
                  'for name in ' + " ".join(EXPORTS) + '; do export "$name=stale"; done; '
                  'load_ipam_cidrs; status=$?; '
                  'printf "STATUS=%s\\n" "$status"; '
                  'for name in ' + " ".join(EXPORTS) +
                  '; do printf "%s=%s\\n" "$name" "${!name-UNSET}"; done; '
                  'exit "$status"')
        result = run(script, calls)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("ERROR:", result.stderr)
            for name in EXPORTS:
                self.assertIn(f"{name}=UNSET", result.stdout)
        return result

    def test_exports_only_valid_live_allocations(self):
        vnets, subnets = fixtures()
        result = self.resolve(reads(vnets, subnets), success=True)
        for zone, (parent, child) in PREFIXES.items():
            self.assertIn(f"{zone.upper()}_VNET_CIDR={parent}", result.stdout)
            self.assertIn(f"{zone.upper()}_SUBNET_CIDR={child}", result.stdout)
        self.assertIn("FIREWALL_SUBNET_CIDR=172.20.1.0/26", result.stdout)

    def test_rejects_non_succeeded_vnet_and_subnet_without_stale_exports(self):
        for resource in (("vnet", "hub"), ("vnet", "spokea"), ("vnet", "spokeb"),
                         ("subnet", "hub", "snet-management"),
                         ("subnet", "hub", "AzureFirewallSubnet"),
                         ("subnet", "spokea", "snet-workload"),
                         ("subnet", "spokeb", "snet-workload")):
            for state in ("Failed", "Updating", None):
                with self.subTest(resource=resource, state=state):
                    vnets, subnets = fixtures()
                    item = (vnets[resource[1]] if resource[0] == "vnet"
                            else subnets[resource[1:]])
                    if state is None:
                        del item["provisioningState"]
                    else:
                        item["provisioningState"] = state
                    self.resolve(reads(vnets, subnets))

    def test_rejects_wrong_pool_and_size(self):
        for path, value in [
            (("vnet", "hub", "pool"), "/subscriptions/other"),
            (("subnet", "spokea", "pool"), "/subscriptions/other"),
            (("vnet", "hub", "size"), "2048"),
            (("subnet", "spokea", "size"), "128"),
            (("subnet", "firewall", "size"), "128"),
        ]:
            with self.subTest(path=path):
                vnets, subnets = fixtures()
                item = (vnets[path[1]] if path[0] == "vnet" else
                        subnets[("hub", "AzureFirewallSubnet")] if path[1] == "firewall" else
                        subnets[(path[1], "snet-workload")])
                alloc = (item["addressSpace"]["ipamPoolPrefixAllocations"] if path[0] == "vnet"
                         else item["ipamPoolPrefixAllocations"])[0]
                if path[2] == "pool":
                    alloc["pool"]["id"] = value
                else:
                    alloc["numberOfIpAddresses"] = value
                self.resolve(reads(vnets, subnets))

    def test_rejects_missing_allocation_and_subnet_prefix(self):
        for mutation in ("no-vnet-pool", "no-subnet-pool", "no-subnet-prefix",
                         "wrong-id", "wrong-tags", "multiple-prefixes"):
            with self.subTest(mutation=mutation):
                vnets, subnets = fixtures()
                if mutation == "no-vnet-pool":
                    del vnets["hub"]["addressSpace"]["ipamPoolPrefixAllocations"]
                elif mutation == "no-subnet-pool":
                    del subnets[("spokeb", "snet-workload")]["ipamPoolPrefixAllocations"]
                elif mutation == "no-subnet-prefix":
                    del subnets[("spokeb", "snet-workload")]["addressPrefix"]
                elif mutation == "wrong-id":
                    vnets["hub"]["id"] = vnet_id("spokea")
                elif mutation == "wrong-tags":
                    vnets["hub"]["tags"]["runId"] = "other"
                else:
                    vnets["hub"]["addressSpace"]["addressPrefixes"].append("172.20.48.0/20")
                self.resolve(reads(vnets, subnets))

    def test_rejects_prefix_length_containment_overlap_and_pool_range(self):
        for key, prefix in [
            (("vnet", "hub"), "172.20.0.0/21"),
            (("vnet", "spokea"), "172.20.0.0/20"),
            (("vnet", "spokeb"), "172.24.0.0/20"),
            (("subnet", "spokea"), "172.20.32.0/24"),
            (("subnet", "spokeb"), "172.20.32.0/25"),
            (("firewall", "hub"), "172.20.0.0/26"),
            (("firewall", "length"), "172.20.1.0/24"),
            (("vnet", "uncanonical"), "172.20.0.1/20"),
        ]:
            with self.subTest(key=key):
                vnets, subnets = fixtures()
                if key[0] == "vnet":
                    vnets["hub" if key[1] == "uncanonical" else key[1]]["addressSpace"]["addressPrefixes"] = [prefix]
                else:
                    subnets[("hub", "AzureFirewallSubnet") if key[0] == "firewall" else
                            (key[1], "snet-workload")]["addressPrefix"] = prefix
                self.resolve(reads(vnets, subnets))

    def test_read_error_clears_old_exports(self):
        vnets, subnets = fixtures()
        for error in (("vnet", "hub"), ("subnet", "spokeb", "snet-workload")):
            with self.subTest(error=error):
                self.resolve(reads(vnets, subnets, error=error))

    def test_rejects_malformed_azure_json_and_wrong_subnet_identity(self):
        for mutation in ("bad-vnet-json", "bad-subnet-json", "wrong-subnet-id",
                         "wrong-subnet-name", "two-allocations", "ipv6"):
            with self.subTest(mutation=mutation):
                current_vnets, current_subnets = fixtures()
                if mutation == "bad-vnet-json":
                    current_vnets["hub"] = "{"
                elif mutation == "bad-subnet-json":
                    current_subnets[("hub", "AzureFirewallSubnet")] = "not-json"
                elif mutation == "wrong-subnet-id":
                    current_subnets[("hub", "AzureFirewallSubnet")]["id"] = (
                        f"{vnet_id('spokea')}/subnets/AzureFirewallSubnet")
                elif mutation == "wrong-subnet-name":
                    current_subnets[("hub", "AzureFirewallSubnet")]["name"] = "firewall"
                elif mutation == "two-allocations":
                    current_vnets["hub"]["addressSpace"]["ipamPoolPrefixAllocations"] *= 2
                else:
                    current_subnets[("spokea", "snet-workload")]["addressPrefix"] = "2001:db8::/24"
                self.resolve(reads(current_vnets, current_subnets))

    def test_zone_context_needs_resolved_prefix(self):
        result = run('source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; '
                     'load_run state.json && zone_context hub')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR:", result.stderr)

    def test_zone_context_without_state_is_an_error_under_nounset(self):
        result = run('set -u; source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; '
                     'zone_context hub')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR:", result.stderr)
        self.assertNotIn("unbound variable", result.stderr)

    def test_unknown_zone_drops_previous_zone_targets(self):
        result = run('source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; '
                     'load_run state.json; export HUB_VNET_CIDR=172.20.0.0/20; '
                     'zone_context hub; zone_context unknown; '
                     'printf "TARGET=%s\\n" "${RG-UNSET}"')
        self.assertEqual(result.stdout.strip(), "TARGET=UNSET")

    def test_clear_run_removes_resolved_cidrs(self):
        result = run('source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; '
                     'export HUB_VNET_CIDR=stale FIREWALL_SUBNET_CIDR=stale; '
                     'clear_run; printf "%s %s\\n" "${HUB_VNET_CIDR-UNSET}" "${FIREWALL_SUBNET_CIDR-UNSET}"')
        self.assertEqual(result.stdout.strip(), "UNSET UNSET")

    def test_failed_reresolution_drops_previous_zone_prefix(self):
        vnets, subnets = fixtures()
        script = ('source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; '
                  'source "$WORKSHOP_ROOT/scripts/workshop-ipam.sh"; '
                  'load_run state.json && load_ipam_cidrs && zone_context spokea || exit 90; '
                  'load_ipam_cidrs; status=$?; '
                  'printf "STATUS=%s PREFIX=%s RG=%s\\n" "$status" "${PREFIX-UNSET}" "${RG-UNSET}"; '
                  'test "$status" -ne 0')
        result = run(script, reads(vnets, subnets) +
                     reads(vnets, subnets, error=("vnet", "hub")))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("STATUS=1 PREFIX=UNSET RG=UNSET", result.stdout)

    def test_failed_provisioning_state_after_success_drops_all_previous_exports(self):
        vnets, subnets = fixtures()
        failed_vnets, failed_subnets = fixtures()
        failed_subnets[("spokeb", "snet-workload")]["provisioningState"] = "Failed"
        script = ('source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; '
                  'source "$WORKSHOP_ROOT/scripts/workshop-ipam.sh"; '
                  'load_run state.json && load_ipam_cidrs && zone_context spokea || exit 90; '
                  'load_ipam_cidrs; status=$?; '
                  'printf "STATUS=%s PREFIX=%s RG=%s\\n" "$status" "${PREFIX-UNSET}" "${RG-UNSET}"; '
                  'for name in ' + " ".join(EXPORTS) +
                  '; do printf "%s=%s\\n" "$name" "${!name-UNSET}"; done; '
                  'test "$status" -ne 0')
        result = run(script, reads(vnets, subnets) + reads(failed_vnets, failed_subnets))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("ERROR:", result.stderr)
        self.assertIn("STATUS=1 PREFIX=UNSET RG=UNSET", result.stdout)
        for name in EXPORTS:
            self.assertIn(f"{name}=UNSET", result.stdout)

    def test_zone_context_uses_live_parent_prefix(self):
        vnets, subnets = fixtures()
        result = run('source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; '
                     'source "$WORKSHOP_ROOT/scripts/workshop-ipam.sh"; '
                     'load_run state.json && load_ipam_cidrs && '
                     'zone_context spokea && printf "%s\\n" "$PREFIX"',
                     reads(vnets, subnets))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "172.20.16.0/20")

    def test_module_sessions_load_cidrs_after_ownership_checks(self):
        vnets, subnets = fixtures()
        for module in (3, 4, 5, 6):
            with self.subTest(module=module):
                path = next((ROOT / "docs").glob(f"0{module}-*.md"))
                setup = blocks(path)[f"prepare-0{module}"]
                result = run('STATE_FILE=state.json; ' + setup +
                             '; printf "RESOLVED=%s\\n" "${HUB_VNET_CIDR-UNSET}"',
                             [account(), *(group(zone) for zone in PREFIXES),
                              *reads(vnets, subnets)])
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("RESOLVED=172.20.0.0/20", result.stdout)

    def test_module_two_displays_live_addresses_only_after_all_vnets_exist(self):
        setup = blocks(next((ROOT / "docs").glob("02-*.md")))["inspect-foundation-cidrs"]
        vnets, subnets = fixtures()
        result = run('source "$WORKSHOP_ROOT/scripts/workshop-common.sh"; '
                     'load_run state.json && ' + setup,
                     [*(group(zone) for zone in PREFIXES), *reads(vnets, subnets)])
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Hub VNet 172.20.0.0/20", result.stdout)
        self.assertIn("Spoke B VNet 172.20.32.0/20", result.stdout)

    def test_cleanup_handles_no_created_resources_without_resolving_cidrs(self):
        calls = [account()] + [
            call(["group", "exists", "--name", STATE["resourceGroups"][zone],
                  "-o", "tsv"], "false") for zone in PREFIXES
        ]
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PASS:", result.stdout)

    def test_cleanup_handles_only_hub_group_before_any_vnet(self):
        hub = STATE["resourceGroups"]["hub"]
        calls = [account()]
        for zone in PREFIXES:
            calls.append(call(["group", "exists", "--name", STATE["resourceGroups"][zone],
                               "-o", "tsv"], "true" if zone == "hub" else "false"))
            if zone == "hub":
                calls.append(group("hub"))
        calls.extend([
            account(), group("hub"),
            call(["network", "manager", "list", "-g", hub, "-o", "json",
                  "--subscription", SUB], []),
            call(["group", "delete", "--name", hub, "--yes", "--no-wait"]),
            call(["group", "exists", "--name", hub, "-o", "tsv"], "false"),
        ])
        result = run('bash "$WORKSHOP_ROOT/scripts/cleanup.sh" state.json', calls,
                     input_text=f"DELETE demo123 FROM {SUB}\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Shared resources were not deleted", result.stdout)

    def test_vm_helper_reads_cidrs_before_using_zone_context(self):
        vnets, subnets = fixtures()
        vnets["spokeb"]["addressSpace"]["addressPrefixes"] = ["172.20.0.0/20"]
        script = ('bash "$WORKSHOP_ROOT/scripts/run-vm.sh" state.json spokea guest.sh')
        result = run(script, [account(), group("spokea"), *reads(vnets, subnets)],
                     files={"guest.sh": "echo ok\n"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ERROR: Invalid live IPAM CIDRs", result.stderr)

    def test_independent_verifiers_reject_bad_cidrs_before_other_evidence(self):
        vnets, subnets = fixtures()
        vnets["spokeb"]["addressSpace"]["addressPrefixes"] = ["172.20.0.0/20"]
        for executable, stage in (("verify-core.sh", "baseline"),
                                  ("verify-extension.sh", "denied")):
            with self.subTest(executable=executable):
                result = run(f'bash "$WORKSHOP_ROOT/scripts/{executable}" state.json {stage}',
                             [account(), *(group(zone) for zone in PREFIXES),
                              *reads(vnets, subnets)])
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ERROR: Invalid live IPAM CIDRs", result.stderr)
