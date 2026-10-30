# -*- coding: utf-8 -*-
"""Permisos y multicompañía (en Odoo 20 se definen con ``ir.access``)."""
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, new_test_user, tagged


@tagged("post_install", "-at_install", "saeko")
class TestSaekoSecurity(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company_a = cls.env.company
        cls.company_b = cls.env["res.company"].create({"name": "Universidad B"})
        cls.backend_a = cls.env["saeko.backend"].create({"name": "A"})
        cls.backend_b = cls.env["saeko.backend"].create(
            {"name": "B", "company_id": cls.company_b.id})
        cls.auditor = new_test_user(
            cls.env, login="saeko_auditor", groups="saeko_connector.group_saeko_user",
            company_id=cls.company_a.id, company_ids=[cls.company_a.id])
        cls.manager = new_test_user(
            cls.env, login="saeko_manager", groups="saeko_connector.group_saeko_manager",
            company_id=cls.company_a.id, company_ids=[cls.company_a.id])
        cls.env["saeko.api.log"].create({
            "backend_id": cls.backend_a.id, "method": "GET", "endpoint": "/x", "success": True})

    def test_auditor_reads_but_cannot_change(self):
        Backend = self.env["saeko.backend"].with_user(self.auditor)
        self.assertEqual(Backend.search([]), self.backend_a)
        self.assertTrue(self.env["saeko.api.log"].with_user(self.auditor).search([]))
        with self.assertRaises(AccessError):
            self.backend_a.with_user(self.auditor).write({"name": "X"})
        with self.assertRaises(AccessError):
            Backend.create({"name": "Nuevo"})

    def test_manager_configures_but_not_secrets(self):
        backend = self.env["saeko.backend"].with_user(self.manager).create({"name": "Nuevo"})
        self.assertTrue(backend)
        with self.assertRaises(AccessError):
            self.env["saeko.token"].with_user(self.manager).search([])
        with self.assertRaises(AccessError):
            backend.private_key  # noqa: B018 - campo restringido a base.group_system

    def test_multicompany_restriction(self):
        Backend = self.env["saeko.backend"].with_user(self.manager)
        self.assertNotIn(self.backend_b, Backend.search([]))
        with self.assertRaises(AccessError):
            self.backend_b.with_user(self.manager).read(["name"])

    def test_log_is_immutable(self):
        log = self.env["saeko.api.log"].search([], limit=1)
        with self.assertRaises((UserError, AccessError)):
            log.with_user(self.manager).write({"endpoint": "/hack"})
        with self.assertRaises(AccessError):
            log.with_user(self.manager).unlink()
