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
          $name != $vm and ($name | startswith($vm + "_osdisk") | not) and
          $name != $nic and
          ($zone != "hub" or ($name != $pip and $name != $nat))))
    ' <<< "$inventory" >/dev/null ||
      { fail "Support resource already exists or resource inventory is malformed in $rg; inspect before creating."; return 1; }
  done
}
