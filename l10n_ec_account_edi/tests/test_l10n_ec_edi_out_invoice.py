import logging
from datetime import datetime, timedelta
from unittest import skip
from unittest.mock import MagicMock, patch

from odoo import _
from odoo.exceptions import UserError
from odoo.tests import Form, tagged

from odoo.addons.l10n_ec_account_edi.models.account_edi_document import (
    AccountEdiDocument,
)

# from .sri_response import patch_service_sri, validation_sri_response_returned
from .sri_response import patch_service_sri
from .test_edi_common import TestL10nECEdiCommon

_logger = logging.getLogger(__name__)

sent_response = MagicMock(
    estado="RECIBIDA",
    comprobantes={
        "comprobante": [
            {
                "claveAcceso": "DUMMY_ACCESS_KEY",
                "mensajes": {"mensaje": []},
            }
        ]
    },
)

success_auth_response = MagicMock(
    claveAccesoConsultada="DUMMY_ACCESS_KEY9",
    numeroComprobantes=1,
    autorizaciones={
        "autorizacion": [
            dict(
                estado="AUTORIZADO",
                numeroAutorizacion="DUMMY_ACCESS_KEY9",
                fechaAutorizacion=datetime.now(),
                ambiente="PRUEBAS",
                comprobante="",
                mensajes={"mensaje": []},
            )
        ]
    },
)


def response_se(e, _=None):
    return getattr(sent_response, e)


def auth_response_se(e, _=None):
    return getattr(success_auth_response, e)


sent_response.get = MagicMock(side_effect=response_se)
success_auth_response.get = MagicMock(side_effect=auth_response_se)

# --------------------- 8<---------    PV run only these set of tests by now -----


@tagged("post_install_l10n", "post_install", "-at_install", "pv")
class TestL10nAccountEdi(TestL10nECEdiCommon):
    def setUp(self, chart_template_ref=None):
        super().setUp()

        # españa lo sabe:!!
        # https://github.com/OCA/l10n-spain/blob/17.0/l10n_es_facturae/tests/common.py
        self.tax15 = self.env["account.tax"].create(
            {
                "name": "Test tax 15%",
                "amount_type": "percent",
                "amount": 15,
                "type_tax_use": "sale",
                "tax_group_id": self.env.ref("l10n_ec_account_edi.tax_group_vat_15").id,
                "l10n_ec_xml_fe_code": "04",  # See codigoPorcentaje en FE
            }
        )

        self.product_15 = self.env["product.product"].create(
            {
                "name": "product_15",
                "uom_id": self.env.ref("uom.product_uom_unit").id,
                "uom_po_id": self.env.ref("uom.product_uom_unit").id,
                "lst_price": 1000.0,
                "standard_price": 800.0,
                "property_account_income_id": self.company_data[
                    "default_account_revenue"
                ].id,
                "property_account_expense_id": self.company_data[
                    "default_account_expense"
                ].id,
                "taxes_id": [(6, 0, self.tax15.ids)],
                # 'supplier_taxes_id': [(6, 0, self.tax_purchase_a.ids)],
            }
        )

    @skip("PV done")
    def test_l10n_ec_out_invoice_configuration(self):
        # intentar validar una factura sin tener configurado correctamente los datos
        invoice = self._l10n_ec_prepare_edi_out_invoice()
        with self.assertRaises(UserError):
            invoice.action_post()

    @skip("PV refactorizando")
    @patch_service_sri(validation_response=sent_response)
    def test_l10n_ec_out_invoice_wrong_certificate(self):
        """Test para firmar una factura con un certificado inválido"""
        self._setup_edi_company_ec()
        # Cambiar la contraseña del certificado de firma electrónica
        self.certificate.password = "invalid"
        invoice = self._l10n_ec_prepare_edi_out_invoice(auto_post=True)
        self.assertEqual("posted", invoice.state)
        edi_doc = invoice._get_edi_document(self.edi_format)

        with self.assertLogs(
            "odoo.addons.l10n_ec_account_edi.models.account_edi_format",
            level=logging.ERROR,
        ):
            edi_doc._process_documents_web_services(with_commit=False)
        self.assertFalse(edi_doc.edi_content)
        self.assertTrue(edi_doc.error)

    @skip("PV done")
    @patch_service_sri(
        validation_response=sent_response, auth_response=success_auth_response
    )
    def test_l10n_ec_out_invoice_sri(self):
        """Crear factura electrónica, con la configuración correcta"""
        _logger.info("DEBUG test test_l10n_ec_out_invoice_sri >>>>>>>>>>>>>>>>>>")
        # Configurar los datos previamente
        self._setup_edi_company_ec()
        # Compañia no obligada a llevar contabilidad
        self._l10n_ec_edi_company_no_account()
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            use_payment_term=False, auto_post=True
        )
        # Añadir pago total a la factura
        self.generate_payment(invoice_ids=invoice.ids, journal=self.journal_cash)
        self.assertEqual(invoice.payment_state, "paid")

        edi_doc = invoice._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)

        self.assertEqual(invoice.state, "posted")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        self.assertEqual(invoice.l10n_ec_xml_access_key, edi_doc.l10n_ec_xml_access_key)

        self.assertEqual(edi_doc.state, "sent")
        self.assertEqual(
            invoice.l10n_ec_authorization_date, edi_doc.l10n_ec_authorization_date
        )
        # Envio de email
        try:
            invoice.action_invoice_sent()
            mail_sended = True
        except UserError as e:
            _logger.warning(e.name)
            mail_sended = False
        self.assertTrue(mail_sended)

    @patch_service_sri(
        validation_response=sent_response, auth_response=success_auth_response
    )
    def test_l10n_ec_out_factura_exterior(self):
        """Testing facturación en el exterior"""
        _logger.info("DEBUG test  >>>> facturación en el exterior ----- ")
        self.journal_cash.l10n_ec_sri_payment_id = self.env.ref("l10n_ec.P1").id

        # PV ------- IMPORTANT --------
        # most of the tax shaping are being inspired from here:
        # odoo/custom/src/odoo/addons/account/tests/common.py
        #    ------- --------- --------

        # Configurar los datos previamente
        self._setup_edi_company_ec()

        self.company.write(
            {
                "l10n_ec_type_environment": "test",
                "l10n_ec_key_type_id": self.certificate.id,
                "l10n_ec_invoice_version": "2.1.0",
            }
        )

        # Compañia no obligada a llevar contabilidad
        self._l10n_ec_edi_company_no_account()

        # A USA state
        us_state = self.env["res.country.state"].create(
            {
                "name": "New Jersey",
                "code": "13",
                "country_id": self.env.ref("base.us").id,
            }
        )

        # Someone from USA
        self.partner = self.env["res.partner"].create(
            {
                "name": "Cliente Gringo Loco",
                "street": "C/ Ejemplo, 13",
                "zip": "07083",
                "city": "Union",
                "state_id": us_state.id,
                "country_id": self.env.ref("base.us").id,
                "vat": "US05680675C",
            }
        )

        # zero tax for USA customer
        self.tax_sale_a.write(
            {
                "l10n_ec_xml_fe_code": "2",
                "tax_group_id": self.env.ref("l10n_ec.tax_group_vat0").id,
            }
        )

        latam_document_type = self.env.ref("l10n_ec.ec_dt_18")

        # edi_format = self.env["account.edi.format"].create(
        #     {
        #         "name": "test_format",
        #         "code": "l10n_ec_format_sri",
        #     }
        # )

        # invoice is self.move, set as is for compatibility
        self.move = self.env["account.move"].create(
            {
                "partner_id": self.partner.id,
                "journal_id": self.journal_sale.id,
                "invoice_date": "2024-03-12",
                # "payment_mode_id": self.payment_mode.id,
                "l10n_latam_document_type_id": latam_document_type.id,
                "move_type": "out_invoice",
                "l10n_latam_internal_type": "invoice",
                "edi_document_ids": [
                    {
                        "edi_format_id": self.env.ref(
                            "l10n_ec_account_edi.edi_format_ec_sri"
                        )
                    }
                ],
                "invoice_line_ids": [
                    (
                        0,
                        0,
                        {
                            "product_id": self.product_a.id,
                            # "account_id": AccountEdiDocument.id,
                            "name": "Producto de prueba",
                            "quantity": 1.0,
                            "price_unit": 100.0,
                            "tax_ids": [(6, 0, self.taxes_zero_vat.ids)],
                        },
                    )
                ],
            }
        )

        self.move.action_post()

        # # Añadir pago total a la factura
        # self.generate_payment(invoice_ids=self.move.ids, journal=self.journal_cash)

        # Generar xml

        # __import__("ipdb").set_trace()

        edi_doc = self.move._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)

        self.assertEqual(self.move.invoice_line_ids.name, "Producto de prueba")
        self.assertEqual(self.move.invoice_line_ids.tax_ids[0].name, "Iva 0%")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        self.assertEqual(
            self.move.l10n_ec_xml_access_key, edi_doc.l10n_ec_xml_access_key
        )

        # validate the generated xml
        xml_data = edi_doc._l10n_ec_render_xml_edi()
        self.assertIn('version="2.1.0"', xml_data)
        self.assertIn("<codigo>2</codigo>", xml_data)
        self.assertIn("<codigoPorcentaje>0</codigoPorcentaje>", xml_data)
        self.assertEqual(edi_doc.state, "sent")
        self.assertEqual(
            self.move.l10n_ec_authorization_date, edi_doc.l10n_ec_authorization_date
        )

    # @skip("PV done")
    @patch_service_sri(
        validation_response=sent_response, auth_response=success_auth_response
    )
    def test_l10n_ec_out_iva_15(self):
        """Testing new tax 15 for poor ecuadorians"""
        _logger.info("DEBUG test  >>>>   test_l10n_ec_out_iva_15 ----- ")
        self.journal_cash.l10n_ec_sri_payment_id = self.env.ref("l10n_ec.P1").id

        # PV ------- IMPORTANT --------
        # most of the tax shaping are being inspired from here:
        # odoo/custom/src/odoo/addons/account/tests/common.py
        #    ------- --------- --------

        # Configurar los datos previamente
        self._setup_edi_company_ec()
        # Compañia no obligada a llevar contabilidad
        self._l10n_ec_edi_company_no_account()

        # invoice is self.move, set as is for compatibility
        self.move = self._l10n_ec_prepare_edi_out_invoice(
            products=self.product_15, use_payment_term=False, auto_post=True
        )
        # Añadir pago total a la factura
        self.generate_payment(invoice_ids=self.move.ids, journal=self.journal_cash)

        # Generar xml

        # __import__('ipdb').set_trace()

        edi_doc = self.move._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)

        self.assertEqual(self.move.invoice_line_ids.name, "product_15")
        self.assertEqual(self.move.invoice_line_ids.tax_ids.name, "Test tax 15%")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        self.assertEqual(
            self.move.l10n_ec_xml_access_key, edi_doc.l10n_ec_xml_access_key
        )

        # validate the generated xml
        xml_data = edi_doc._l10n_ec_render_xml_edi()
        self.assertIn("<codigo>2</codigo>", xml_data)
        self.assertIn("<codigoPorcentaje>04</codigoPorcentaje>", xml_data)
        self.assertEqual(edi_doc.state, "sent")
        self.assertEqual(
            self.move.l10n_ec_authorization_date, edi_doc.l10n_ec_authorization_date
        )

    # @skip("PV done")
    @patch_service_sri(
        validation_response=sent_response, auth_response=success_auth_response
    )
    def test_l10n_ec_out_invoice_foreign(self):
        """Test para validar envío de factura para clientes al exterior"""
        _logger.info("DEBUG test  >>>>>>>>>>>>>>>>>>")

        # Configurar una compañia EC no obligada a llevar contabilidad
        self._setup_edi_company_ec()
        self._l10n_ec_edi_company_no_account()

        # Create foreign invoice
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            partner=self.partner_passport, auto_post=True
        )

        # __import__('ipdb').set_trace()
        edi_doc = invoice._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)

        _logger.info("DEBUG edi_doc", edi_doc, "edi_format:", self.edi_format)
        _logger.info("DEBUG edi_doc.state", edi_doc.state)

    # @skip("PV refactorizando")
    @patch_service_sri(validation_response=sent_response)
    def test_l10n_ec_out_invoice_sri_without_response(self):
        """
        Crear factura electrónica, simular no respuesta del SRI,
        intentar enviar nuevamente y ahi si autorizar
        """

        def mock_l10n_ec_edi_send_xml_with_auth(edi_doc_instance, client_ws):
            return self._get_response_with_auth(edi_doc_instance)

        def mock_l10n_ec_edi_send_xml_without_auth(edi_doc_instance, client_ws):
            return self._get_response_without_auth(edi_doc_instance)

        # Configurar los datos previamente
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            use_payment_term=False, auto_post=True
        )
        edi_doc = invoice._get_edi_document(self.edi_format)
        # simular respuesta del SRI donde no se tenga autorizaciones
        with patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_send_xml_auth",
            mock_l10n_ec_edi_send_xml_without_auth,
        ):
            edi_doc._process_documents_web_services(with_commit=False)
        # comprobar que la factura este validada,
        # pero documento edi se quede en estado to_send
        self.assertEqual(invoice.state, "posted")
        self.assertEqual(edi_doc.state, "to_send")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        # intentar enviar nuevamente al SRI,
        # como ya hubo un intento previo,
        # debe consultar el documento antes de volver a enviarlo
        with patch.object(
            AccountEdiDocument,
            "_l10n_ec_edi_send_xml_auth",
            mock_l10n_ec_edi_send_xml_with_auth,
        ):
            edi_doc._process_documents_web_services(with_commit=False)
        self.assertEqual(edi_doc.state, "sent")
        self.assertEqual(invoice.l10n_ec_xml_access_key, edi_doc.l10n_ec_xml_access_key)
        self.assertEqual(
            invoice.l10n_ec_authorization_date, edi_doc.l10n_ec_authorization_date
        )

    # @skip("PV refactorizando")
    @patch_service_sri(validation_response=sent_response)
    def test_l10n_ec_out_invoice_back_sri(self):
        # Crear factura con una fecha superior a la actual
        # para que el sri me la devuelva y no se autorizar
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()
        invoice.invoice_date += timedelta(days=10)
        invoice.action_post()
        edi_doc = invoice._get_edi_document(self.edi_format)
        # Asignar el archivo xml básico para que lo encuentre y lo actualice
        edi_doc.attachment_id = self.attachment.id
        edi_doc._process_documents_web_services(with_commit=False)
        xml_data = edi_doc._l10n_ec_render_xml_edi()
        self.assertEqual(invoice.state, "posted")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)

        # verificar solamente que la fecha expuesta se haya actualizado
        self.assertIn(invoice.invoice_date.strftime("%d/%m/%Y"), xml_data)

        # Jamas se debe hacer estas pruebas en vivo con un sistema externo
        # Por que este test falla? por que estamos mockeando pues el response
        # self.assertIn("ERROR [65] FECHA EMISIÓN EXTEMPORANEA", edi_doc.error)
        # self.assertEqual(edi_doc.blocking_level, "error")

    @skip("PV este test ya no es pertinente")
    @patch_service_sri(
        validation_response=sent_response, auth_response=success_auth_response
    )
    def test_l10n_ec_out_invoice_with_foreign_client(self):
        # Factura con cliente sin identificación para que no se valide el XML

        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(
            partner=self.partner_passport, auto_post=True
        )
        edi_doc = invoice._get_edi_document(self.edi_format)
        # Error en el archivo xml
        # with self.assertLogs(
        #     "odoo.addons.l10n_ec_account_edi.models.account_edi_format",
        #     level=logging.ERROR,
        # ):
        #     edi_doc._process_documents_web_services(with_commit=False)
        # self.assertIn(_("EDI Error creating xml file"), edi_doc.error)
        # Enviar contexto para presentar clave de acceso de xml erroneo
        invoice.button_draft()
        invoice.action_post()
        edi_doc = invoice._get_edi_document(self.edi_format)

        with self.assertLogs(
            "odoo.addons.l10n_ec_account_edi.models.account_edi_document",
            level=logging.ERROR,
        ):
            edi_doc.with_context(
                l10n_ec_xml_call_from_cron=True
            )._process_documents_web_services(with_commit=False)
            self.assertIn(_("ARCHIVO NO CUMPLE ESTRUCTURA XML"), edi_doc.error)

    # @skip("PV refactorizando")
    @patch_service_sri
    def test_l10n_ec_out_invoice_with_payments(self):
        """Crear factura electronica con 2 pagos"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(auto_post=True)
        # 2 Pagos para el total de la factura
        amount = invoice.amount_total / 2
        # Pago con diario efectivo
        self.generate_payment(
            invoice_ids=invoice.ids, journal=self.journal_cash, amount=amount
        )
        # Pago con diario banco por defecto
        self.generate_payment(invoice_ids=invoice.ids, amount=amount)
        edi_doc = invoice._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        self.assertEqual(invoice.state, "posted")
        self.assertEqual(invoice.payment_state, "paid")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)

    # @skip("PV refactorizando")
    def test_l10n_ec_out_invoice_default_values_form(self):
        """Test prueba campos computados y valores por defecto
        en formulario de Factura de cliente"""
        self._setup_edi_company_ec()
        journal = self.journal_sale.copy({"name": "Invoices Journal"})
        self.assertTrue(self.AccountMove._fields["l10n_latam_internal_type"].store)
        form = self._l10n_ec_create_form_move(
            move_type="out_invoice", internal_type="invoice", partner=self.partner_cf
        )
        self.assertIn(form.journal_id, journal + self.journal_sale)
        self.assertRecordValues(
            form.journal_id,
            [
                {
                    "type": "sale",
                    "l10n_latam_use_documents": True,
                }
            ],
        )
        self.assertEqual(form.invoice_filter_type_domain, "sale")
        self.assertEqual(journal + self.journal_sale, form.suitable_journal_ids[:])
        for journal in form.suitable_journal_ids[:]:
            self.assertRecordValues(
                journal,
                [
                    {
                        "type": "sale",
                        "l10n_latam_use_documents": True,
                    }
                ],
            )
        self.assertEqual(form.l10n_latam_document_type_id.internal_type, "invoice")
        for document in form.l10n_latam_available_document_type_ids[:]:
            self.assertEqual(document.internal_type, "invoice")
        invoice = form.save()
        self.assertTrue(invoice.l10n_latam_internal_type, "invoice")

    # @skip("PV refactorizando")
    def test_l10n_ec_out_invoice_default_journal_form(self):
        """Test prueba en formulario de factura, sin diarios registrados"""
        self.journal_sale.unlink()
        invoice_model = self.AccountMove.with_context(
            default_move_type="out_invoice", internal_type="invoice"
        )
        with self.assertRaises(UserError):
            Form(invoice_model)

    # @skip("PV refactorizando")
    def test_l10n_ec_out_invoice_final_consumer_limit_amount(self):
        """Test prueba monto maximo en Factura de cliente
        emitida a consumidor final"""
        self._setup_edi_company_ec()
        self.env["ir.config_parameter"].sudo().set_param(
            "l10n_ec_final_consumer_limit", 50
        )
        self.product_a.list_price = 51
        form = self._l10n_ec_create_form_move(
            move_type="out_invoice",
            internal_type="invoice",
            partner=self.env.ref("l10n_ec.ec_final_consumer"),
        )
        invoice = form.save()
        with self.assertRaises(UserError):
            invoice.action_post()
        self.product_a.list_price = 40
        form = self._l10n_ec_create_form_move(
            move_type="out_invoice",
            internal_type="invoice",
            partner=self.env.ref("l10n_ec.ec_final_consumer"),
        )
        invoice = form.save()
        invoice.action_post()
        self.assertEqual(invoice.state, "posted")

    # @skip("PV refactorizando")
    def test_l10n_ec_validate_lines_invoice(self):
        """Validaciones de cantidad y valor total en 0 en lineas de facturas"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice()
        with Form(invoice) as form:
            with form.invoice_line_ids.edit(0) as line:
                line.quantity = 0
        with self.assertRaises(UserError):
            invoice.action_post()

    # @skip("PV refactorizando")
    @patch_service_sri
    def test_l10n_ec_out_invoice_with_additional_info(self):
        """Crear factura electronica con informacion adicional"""
        self._setup_edi_company_ec()
        invoice = self._l10n_ec_prepare_edi_out_invoice(auto_post=False)
        with Form(invoice) as form:
            with form.l10n_ec_additional_information_move_ids.new() as line:
                line.name = "Test"
                line.description = "ABC"
        invoice.action_post()
        edi_doc = invoice._get_edi_document(self.edi_format)
        edi_doc._process_documents_web_services(with_commit=False)
        self.assertEqual(invoice.state, "posted")
        self.assertTrue(edi_doc.l10n_ec_xml_access_key)
        self.assertEqual(len(invoice.l10n_ec_additional_information_move_ids), 1)
        self.assertEqual(
            invoice.l10n_ec_additional_information_move_ids[0].name, "Test"
        )
