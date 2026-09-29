import unittest

from harness import ROOT


class SharedPoolTests(unittest.TestCase):
    def test_template_has_one_shared_root(self):
        path = ROOT / "infra/shared-ipam.bicep"
        self.assertTrue(path.is_file(), "operator shared IPAM template is missing")
        template = path.read_text()
        self.assertIn("targetScope = 'resourceGroup'", template)
        self.assertIn("name: 'avnm-lzbegin-ipam'", template)
        self.assertIn("name: 'ipam-lzbegin-shared'", template)
        self.assertIn("addressPrefixes: ['172.20.0.0/14']", template)
        self.assertIn("subscriptions: [subscription().id]", template)
        self.assertIn("output poolId string = pool.id", template)
