#!/usr/bin/env python3
"""Validate the seven live IPAM allocations before exposing any CIDR to Bash."""

import ipaddress
import json
import sys

POOL = ipaddress.ip_network("172.20.0.0/14")
ZONES = ("hub", "spokea", "spokeb")
SUBNETS = (("hub", "snet-management", 24), ("spokea", "snet-workload", 24),
           ("spokeb", "snet-workload", 24), ("hub", "AzureFirewallSubnet", 26))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def network(prefix, length):
    require(isinstance(prefix, str), "Missing IPAM address prefix")
    result = ipaddress.ip_network(prefix, strict=True)
    require(result.version == 4 and result.prefixlen == length,
            f"Expected IPv4 /{length}: {prefix}")
    require(result.subnet_of(POOL), f"Address outside shared IPAM pool: {prefix}")
    return result


def allocation(value, pool_id, size):
    require(isinstance(value, list) and len(value) == 1, "Expected one IPAM pool allocation")
    item = value[0]
    require(isinstance(item, dict), "Invalid IPAM pool allocation")
    pool = item.get("pool")
    require(isinstance(pool, dict) and isinstance(pool.get("id"), str)
            and pool["id"].lower() == pool_id.lower(), "IPAM pool ID mismatch")
    require(item.get("numberOfIpAddresses") == str(size),
            f"IPAM allocation size must be {size}")


def resource(value, expected_id, name):
    require(isinstance(value, dict), f"Invalid {name} response")
    require(isinstance(value.get("id"), str) and value["id"].lower() == expected_id.lower()
            and isinstance(value.get("name"), str) and value["name"].lower() == name.lower(),
            f"Unexpected {name} resource ID or name")
    require(value.get("provisioningState") == "Succeeded",
            f"Resource not provisioned successfully: {name}")


def prefix_from_subnet(value):
    prefix = value.get("addressPrefix")
    prefixes = value.get("addressPrefixes")
    if prefixes is not None:
        require(isinstance(prefixes, list) and len(prefixes) == 1,
                "Expected exactly one Subnet prefix")
        require(prefix is None or prefix == prefixes[0], "Conflicting Subnet prefixes")
        prefix = prefixes[0]
    return prefix


def validate(payload):
    require(isinstance(payload, dict), "Invalid IPAM response envelope")
    run_id, sub, pool_id = (payload.get(key) for key in ("runId", "subscriptionId", "poolId"))
    require(all(isinstance(item, str) and item for item in (run_id, sub, pool_id)),
            "Missing workshop state for IPAM lookup")
    vnets, subnets = payload.get("vnets"), payload.get("subnets")
    require(isinstance(vnets, dict) and set(vnets) == set(ZONES), "Expected three VNets")
    require(isinstance(subnets, dict) and set(subnets) ==
            {f"{zone}/{name}" for zone, name, _ in SUBNETS}, "Expected four Subnets")
    parents = {}
    for zone in ZONES:
        name = f"vnet-lzbegin-{zone}-{run_id}"
        rg = f"rg-lzbegin-{zone}-{run_id}"
        expected = (f"/subscriptions/{sub}/resourceGroups/{rg}/providers/"
                    f"Microsoft.Network/virtualNetworks/{name}")
        vnet = vnets[zone]
        resource(vnet, expected, name)
        tags = vnet.get("tags")
        require(isinstance(tags, dict) and all(tags.get(key) == value for key, value in (
            ("workshop", "lz-beginner"), ("environment", "lab"),
            ("runId", run_id), ("managedBy", "workshop"))), f"Ownership mismatch: {name}")
        space = vnet.get("addressSpace")
        require(isinstance(space, dict), f"Missing VNet address space: {name}")
        allocation(space.get("ipamPoolPrefixAllocations"), pool_id, 4096)
        prefixes = space.get("addressPrefixes")
        require(isinstance(prefixes, list) and len(prefixes) == 1,
                f"Expected exactly one VNet prefix: {name}")
        parents[zone] = network(prefixes[0], 20)
    for index, zone in enumerate(ZONES):
        require(all(not parents[zone].overlaps(parents[other]) for other in ZONES[index + 1:]),
                "Overlapping VNet CIDRs")
    children = {}
    for zone, name, length in SUBNETS:
        subnet = subnets[f"{zone}/{name}"]
        resource(subnet, f"{vnets[zone]['id']}/subnets/{name}", name)
        allocation(subnet.get("ipamPoolPrefixAllocations"), pool_id, 1 << (32 - length))
        children[(zone, name)] = network(prefix_from_subnet(subnet), length)
        require(children[(zone, name)].subnet_of(parents[zone]),
                f"Subnet outside parent VNet: {zone}/{name}")
    require(not children[("hub", "snet-management")].overlaps(
        children[("hub", "AzureFirewallSubnet")]), "Overlapping Hub Subnets")
    return (str(parents["hub"]), str(parents["spokea"]), str(parents["spokeb"]),
            str(children[("hub", "snet-management")]),
            str(children[("spokea", "snet-workload")]),
            str(children[("spokeb", "snet-workload")]),
            str(children[("hub", "AzureFirewallSubnet")]))


if __name__ == "__main__":
    try:
        print("\n".join(validate(json.load(sys.stdin))))
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: Invalid live IPAM CIDRs: {exc}", file=sys.stderr)
        sys.exit(1)
