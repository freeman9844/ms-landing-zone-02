assert_support_slots_empty() {
  local zone rg inventory
  for zone in hub spokea spokeb; do
    case "$zone" in
      hub) rg=$RG_HUB ;;
      spokea) rg=$RG_SPOKEA ;;
      spokeb) rg=$RG_SPOKEB ;;
    esac
    inventory=$(az resource list --resource-group "$rg" -o json \
      --subscription "$SUBSCRIPTION_ID") || return 1
    jq -e --arg vm "vm-lzbegin-$zone-$RUN_ID" \
      --arg nic "nic-lzbegin-$zone-$RUN_ID" \
      --arg pip "pip-lzbegin-hub-$RUN_ID" \
      --arg nat "nat-lzbegin-hub-$RUN_ID" --arg zone "$zone" '
      type == "array" and all(.[]; (.name | type == "string") and
        ((.name | ascii_downcase) as $name |
          $name != $vm and
          ($name | startswith($vm + "_osdisk") | not) and
          ($name | startswith($vm + "_disk1_") | not) and
          $name != $nic and
          ($zone != "hub" or ($name != $pip and $name != $nat))))
    ' <<< "$inventory" >/dev/null ||
      { fail "Support resource already exists or resource inventory is malformed in $rg; inspect before creating."; return 1; }
  done
}

support_target() {
  local kind=$1 zone=$2
  case "$zone" in
    hub) SUPPORT_RG=$RG_HUB ;;
    spokea) SUPPORT_RG=$RG_SPOKEA ;;
    spokeb) SUPPORT_RG=$RG_SPOKEB ;;
    *) fail "Unknown support zone: $zone"; return 1 ;;
  esac
  case "$kind" in
    pip|nat)
      [[ "$zone" == hub ]] || { fail "Hub-only support resource"; return 1; }
      SUPPORT_NAME="$kind-lzbegin-hub-$RUN_ID"
      [[ "$kind" == pip ]] && SUPPORT_TYPE=Microsoft.Network/publicIPAddresses ||
        SUPPORT_TYPE=Microsoft.Network/natGateways
      ;;
    nic|vm)
      SUPPORT_NAME="$kind-lzbegin-$zone-$RUN_ID"
      [[ "$kind" == nic ]] && SUPPORT_TYPE=Microsoft.Network/networkInterfaces ||
        SUPPORT_TYPE=Microsoft.Compute/virtualMachines
      ;;
    *) fail "Unknown support type: $kind"; return 1 ;;
  esac
  SUPPORT_ID="/subscriptions/$SUBSCRIPTION_ID/resourceGroups/$SUPPORT_RG/providers/$SUPPORT_TYPE/$SUPPORT_NAME"
}

# Return 0 only for an exact resource, 2 only for a proven empty slot, 1 for uncertainty.
support_slot_exists() {
  local kind=$1 zone=$2 inventory
  support_target "$kind" "$zone" || return 1
  inventory=$(az resource list --resource-group "$SUPPORT_RG" -o json \
    --subscription "$SUBSCRIPTION_ID") || return 1
  jq -e --arg name "$SUPPORT_NAME" --arg id "$SUPPORT_ID" \
    --arg type "$SUPPORT_TYPE" --arg run "$RUN_ID" '
    type == "array" and all(.[]; .name | type == "string") and
    ([.[] | select((.name | ascii_downcase) == ($name | ascii_downcase))] |
     length <= 1 and all(.[]; (.id | ascii_downcase) == ($id | ascii_downcase) and
       (.type | ascii_downcase) == ($type | ascii_downcase) and
       .tags.runId == $run and .tags.workshop == "lz-beginner" and
       .tags.environment == "lab" and .tags.managedBy == "workshop"))
  ' <<<"$inventory" >/dev/null || { fail "Unsafe or malformed support inventory: $SUPPORT_NAME"; return 1; }
  if jq -e --arg name "$SUPPORT_NAME" \
    'any(.[]; (.name | ascii_downcase) == ($name | ascii_downcase))' \
    <<<"$inventory" >/dev/null; then
    return 0
  fi
  if [[ "$kind" == vm ]] && jq -e --arg name "$SUPPORT_NAME" '
    any(.[]; .name | ascii_downcase |
      startswith(($name + "_osdisk") | ascii_downcase) or
      startswith(($name + "_disk1_") | ascii_downcase))
  ' <<<"$inventory" >/dev/null; then
    fail "VM absent but OS disk slot occupied: $SUPPORT_NAME"
    return 1
  fi
  return 2
}

verify_support_resource() {
  local kind=$1 zone=$2 data rg name id subnet public_key=''
  support_target "$kind" "$zone" || return 1
  rg=$SUPPORT_RG name=$SUPPORT_NAME id=$SUPPORT_ID
  case "$kind" in
    pip) data=$(az network public-ip show -g "$rg" -n "$name" -o json --subscription "$SUBSCRIPTION_ID") || return 1 ;;
    nat) data=$(az network nat gateway show -g "$rg" -n "$name" -o json --subscription "$SUBSCRIPTION_ID") || return 1 ;;
    nic) data=$(az network nic show -g "$rg" -n "$name" -o json --subscription "$SUBSCRIPTION_ID") || return 1 ;;
    vm) data=$(az vm show -g "$rg" -n "$name" -o json --subscription "$SUBSCRIPTION_ID") || return 1 ;;
  esac
  subnet=snet-workload
  [[ "$zone" == hub ]] && subnet=snet-management
  if [[ "$kind" == vm ]]; then
    public_key=$(cat ".workshop-keys/$RUN_ID/id_ed25519.pub") || return 1
    [[ -n "$public_key" ]] || return 1
  fi
  jq -e --arg id "$id" --arg location "$LOCATION" --arg run "$RUN_ID" \
    --arg zone "$zone" --arg sub "$SUBSCRIPTION_ID" --arg rg "$rg" \
    --arg subnet "$subnet" --arg public_key "$public_key" --arg boot "${3:-required}" '
    def same($a; $b): ($a | type == "string") and ($a | ascii_downcase) == ($b | ascii_downcase);
    same(.id; $id) and same(.location; $location) and
    .provisioningState == "Succeeded" and
    .tags.runId == $run and .tags.workshop == "lz-beginner" and
    .tags.environment == "lab" and .tags.managedBy == "workshop" and
    (if $ARGS.positional[0] == "pip" then
       .sku.name == "Standard" and .publicIPAllocationMethod == "Static" and
       .publicIPAddressVersion == "IPv4"
     elif $ARGS.positional[0] == "nat" then
       .sku.name == "Standard" and .idleTimeoutInMinutes == 4 and
       (.publicIpAddresses | type == "array" and length == 1) and
       same(.publicIpAddresses[0].id;
         ("/subscriptions/" + $sub + "/resourceGroups/" + $rg +
          "/providers/Microsoft.Network/publicIPAddresses/pip-lzbegin-hub-" + $run))
     elif $ARGS.positional[0] == "nic" then
       .enableIPForwarding == false and
       (.ipConfigurations | type == "array" and length == 1) and
       (.ipConfigurations[0].publicIPAddress == null) and
       same(.ipConfigurations[0].subnet.id;
         ("/subscriptions/" + $sub + "/resourceGroups/" + $rg +
          "/providers/Microsoft.Network/virtualNetworks/vnet-lzbegin-" + $zone +
          "-" + $run + "/subnets/" + $subnet))
     else
       .hardwareProfile.vmSize == "Standard_B2als_v2" and
       .storageProfile.imageReference.publisher == "Canonical" and
       .storageProfile.imageReference.offer == "ubuntu-24_04-lts" and
       .storageProfile.imageReference.sku == "server" and
       .storageProfile.osDisk.managedDisk.storageAccountType == "StandardSSD_LRS" and
       (.storageProfile.osDisk.name | type == "string" and
        (ascii_downcase |
         startswith(("vm-lzbegin-" + $zone + "-" + $run + "_osdisk") | ascii_downcase) or
         startswith(("vm-lzbegin-" + $zone + "-" + $run + "_disk1_") | ascii_downcase))) and
       same(.storageProfile.osDisk.managedDisk.id;
         ("/subscriptions/" + $sub + "/resourceGroups/" + $rg +
          "/providers/Microsoft.Compute/disks/" + .storageProfile.osDisk.name)) and
       .storageProfile.osDisk.deleteOption == "Delete" and
       .securityProfile.securityType == "TrustedLaunch" and
       .securityProfile.uefiSettings.secureBootEnabled == true and
       .securityProfile.uefiSettings.vTpmEnabled == true and
       .osProfile.adminUsername == "workshopadmin" and
       same(.osProfile.computerName; ($zone + "-" + $run)) and
       .osProfile.linuxConfiguration.disablePasswordAuthentication == true and
       .osProfile.linuxConfiguration.provisionVMAgent == true and
       (.osProfile.linuxConfiguration.ssh.publicKeys | type == "array" and length == 1) and
       .osProfile.linuxConfiguration.ssh.publicKeys[0].keyData == $public_key and
       (.networkProfile.networkInterfaces | type == "array" and length == 1) and
       .networkProfile.networkInterfaces[0].deleteOption == "Delete" and
       same(.networkProfile.networkInterfaces[0].id;
         ("/subscriptions/" + $sub + "/resourceGroups/" + $rg +
          "/providers/Microsoft.Network/networkInterfaces/nic-lzbegin-" + $zone + "-" + $run)) and
       (if $boot == "pending" then
         (.diagnosticsProfile.bootDiagnostics.enabled == false or
          .diagnosticsProfile.bootDiagnostics.enabled == null)
        else .diagnosticsProfile.bootDiagnostics.enabled == true end)
     end)
  ' --args "$kind" <<<"$data" >/dev/null ||
    { fail "Support configuration mismatch: $kind/$zone"; return 1; }
  printf 'PASS: %s/%s exact configuration\n' "$kind" "$zone"
}

inspect_support_slots() {
  local kind zone status
  for kind in pip nat; do
    if support_slot_exists "$kind" hub; then
      verify_support_resource "$kind" hub || return 1
    else
      status=$?
      [[ $status == 2 ]] || return 1
      printf 'MISSING: %s hub\n' "$kind"
    fi
  done
  for zone in hub spokea spokeb; do
    for kind in nic vm; do
      if support_slot_exists "$kind" "$zone"; then
        if [[ "$kind" == vm ]] && verify_support_resource vm "$zone" pending 2>/dev/null; then
          printf 'BOOT_PENDING: vm %s (verify then enable diagnostics)\n' "$zone"
        else
          verify_support_resource "$kind" "$zone" || return 1
        fi
      else
        status=$?
        [[ $status == 2 ]] || return 1
        printf 'MISSING: %s %s\n' "$kind" "$zone"
      fi
    done
  done
}

require_support_present() {
  support_slot_exists "$1" "$2" || { fail "Missing or unsafe prerequisite: $1/$2"; return 1; }
  verify_support_resource "$1" "$2"
}

require_support_missing() {
  local status
  if support_slot_exists "$1" "$2"; then
    fail "Already exists: $1/$2"; return 1
  else
    status=$?
    [[ $status == 2 ]] || return 1
  fi
}

verify_support_all() {
  local zone
  require_support_present pip hub || return 1
  require_support_present nat hub || return 1
  for zone in hub spokea spokeb; do
    require_support_present nic "$zone" || return 1
    require_support_present vm "$zone" || return 1
  done
}
