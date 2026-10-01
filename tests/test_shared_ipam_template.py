import unittest

from harness import ROOT


class SharedPoolTests(unittest.TestCase):
    def test_run_pool_template_uses_existing_hub_manager(self):
        template = (ROOT / "infra/run-ipam-pool.bicep").read_text()
        self.assertIn("resource manager 'Microsoft.Network/networkManagers@2024-05-01' existing", template)
        self.assertIn("name: 'avnm-lzbegin-${runId}'", template)
        self.assertIn("name: 'ipam-lzbegin-${runId}'", template)
        self.assertIn("addressPrefixes: ['172.20.0.0/14']", template)
        self.assertIn("output poolId string = pool.id", template)
        doc = (ROOT / "docs/02-network-foundation.md").read_text()
        self.assertLess(doc.index("<!-- exec:avnm-ready -->"),
                        doc.index("<!-- exec:run-ipam-pool -->"))
        self.assertLess(doc.index("<!-- exec:run-ipam-pool -->"),
                        doc.index("<!-- exec:foundation-hub-vnet -->"))

    def test_template_has_one_shared_root(self):
        path = ROOT / "infra/shared-ipam.bicep"
        self.assertTrue(path.is_file(), "operator shared IPAM template is missing")
        template = path.read_text()
        self.assertIn("targetScope = 'resourceGroup'", template)
        self.assertIn("name: 'avnm-lzbegin-ipam'", template)
        self.assertIn("name: 'ipam-lzbegin-shared'", template)
        self.assertIn("addressPrefixes: ['172.20.0.0/14']", template)
        self.assertIn("subscriptions: [subscription().id]", template)
        self.assertIn("networkManagerScopeAccesses: []", template)
        self.assertIn("output poolId string = pool.id", template)
        self.assertIn("한 구독에서 동시에 하나의 실행", (
            ROOT / "docs/maintainer-validation.md").read_text())
