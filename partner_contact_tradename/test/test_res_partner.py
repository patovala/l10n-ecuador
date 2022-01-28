# Copyright 2022: PBox (<https://www.pupilabox.net.ec>)
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).


from odoo.tests import common


class TestResPartner(common.TransactionCase):
    def setUp(self):
        super(TestResPartner, self).setUp()
        self.partner_admin = self.env.ref("base.partner_admin")
        self.partner_admin.write({"tradename": "PupilaBox"})

    def test_name_search(self):
        expected_names = ["Pupilabox"]
        names = self.partner_admin.name_search(name: 'pbox')
        self.assertEqual(names in expected_names)
