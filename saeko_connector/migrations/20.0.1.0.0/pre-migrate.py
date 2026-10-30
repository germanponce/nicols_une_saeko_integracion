# -*- coding: utf-8 -*-
"""19.0 → 20.0

Odoo 20 unifica ``ir.model.access`` e ``ir.rule`` en ``ir.access``. El
servicio oficial de actualización de Odoo migra los registros existentes;
aquí solo se liberan los XML-ID de este módulo que apuntaban a los modelos
antiguos, para que ``security/ir.access.csv`` los vuelva a crear sobre
``ir.access`` sin choques de identificadores.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        """
        DELETE FROM ir_model_data
         WHERE module = 'saeko_connector'
           AND model IN ('ir.model.access', 'ir.rule')
        """
    )
    _logger.info("saeko_connector: %s XML-ID de seguridad heredados liberados", cr.rowcount)
