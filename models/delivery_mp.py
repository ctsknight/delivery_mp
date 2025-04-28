# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import base64

from docutils.nodes import reference

from .mp_request import MPProvider
from odoo.tools.zeep.helpers import serialize_object

from odoo import api, models, fields, _
from odoo.exceptions import UserError
from odoo.tools import float_repr
from odoo.tools.safe_eval import const_eval

import logging


class Providermp(models.Model):
    _inherit = 'delivery.carrier'

    delivery_type = fields.Selection(selection_add=[
        ('mp', "MP")
    ], ondelete={'mp': lambda recs: recs.write({'delivery_type': 'fixed', 'fixed_price': 0})})

    mp_username = fields.Char(string="MP username", groups="base.group_system")
    mp_password = fields.Char(string="MP Password", groups="base.group_system")
    mp_label_format = fields.Selection([
        ('PNG', 'PNG'),
        ('PDF', 'PDF')
    ], string="Label Image Format", default='PDF')

    mp_package_dimension_unit = fields.Selection([('I', 'Inches'),
                                                  ('C', 'Centimeters')],
                                                 default='C',
                                                 string='Package Dimension Unit')
    mp_package_weight_unit = fields.Selection([('L', 'Pounds'),
                                               ('K', 'Kilograms')],
                                              default='K',
                                              string="Package Weight Unit")
    mp_default_package_type_id = fields.Many2one('stock.package.type', string='MP Package Type')
    mp_custom_data_request = fields.Text(
        'Custom data for MP requests,',
        help="""The custom data in MP is organized like the inside of a json file.
        There are 3 possible keys: 'rate', 'ship', 'return', to which you can add your custom data.
        More info on https://xmlportal.dhl.com/"""
    )

    def __init__(self, env, ids, prefetch_ids):
        super().__init__(env, ids, prefetch_ids)

    @api.ondelete(at_uninstall=False)
    def _unlink_except_commercial_invoice_sequence(self):
        if self.env.ref('delivery_mp.mp_commercial_invoice_seq').id in self.ids:
            raise UserError(_('You cannot delete the commercial invoice sequence.'))

    def _compute_can_generate_return(self):
        super(Providermp, self)._compute_can_generate_return()
        for carrier in self:
            if carrier.delivery_type == 'mp':
                carrier.can_generate_return = True

    def _compute_supports_shipping_insurance(self):
        super(Providermp, self)._compute_supports_shipping_insurance()
        for carrier in self:
            if carrier.delivery_type == 'mp':
                carrier.supports_shipping_insurance = False

    def mp_rate_shipment(self, order):
        mp_provider = MPProvider(logging.getLogger(__name__), self.sudo().mp_username, self.sudo().mp_password)
        packages = self._get_packages_from_order(order, self.mp_default_package_type_id)
        details, total_weight = mp_provider._set_dct_bkg_details(self, packages)

        response = mp_provider.call_shipping_remote({
            'action': 'rate',
            'shipping_method': self.mp_default_package_type_id.shipper_package_code,
            'country': order.partner_shipping_id.country_id.code,
            'total_weight': total_weight
        })

        if response.get('status') == 200:
            return {'success': True,
                    'price': response['data']['price'],
                    'error_message': False,
                    'warning_message': False}
        else:
            return {'success': False,
                    'price': 0.0,
                    'error_message': response.get('msg', ''),
                    'warning_message': False}

    def mp_send_shipping(self, pickings):
        mp_provider = MPProvider(logging.getLogger(__name__), self.sudo().mp_username, self.sudo().mp_password)
        res = []
        for picking in pickings:
            if picking:
                # Generate a PDF using Odoo's report action
                result, report_format = self.env['ir.actions.report']._render_qweb_pdf('studio_customization.abholschein_4a016bec-b09d-44ea-897f-abdcc8d1ec1c',
                                                [picking.id])
                print('Lieferschein － ' + picking.name + '.pdf')

                # Encode the PDF content in Base64
                pdf_base64 = base64.b64encode(result)

                response = mp_provider.call_shipping_remote({
                    'action': 'shipment',
                    'warehouse': picking.location_id.warehouse_id.name,
                    'shipping_method': self.mp_default_package_type_id.shipper_package_code,
                    'consignee': mp_provider._set_consignee(picking.partner_id),
                    'consignor': mp_provider._set_shipper(picking.company_id.partner_id,
                                                          picking.picking_type_id.warehouse_id.partner_id),
                    'reference_no': picking.sale_id.name + '_' + picking.name if picking.sale_id else picking.name,
                    'details': mp_provider._set_shipment_details(picking),
                    'file_base64': pdf_base64.decode('utf-8'),
                    'file_name': 'Lieferschein － ' + picking.name + '.pdf'
                })

                if response.get('status') == 200:
                    tracking_number = response['data']['tracking_number']
                else:
                    raise UserError(response['msg'])

                picking.message_post(body='Shipping to the Logistics Center has been successfully completed {} : {}, '
                                          'Please proceed to the Logistics Center for the next steps'
                                     .format(picking.name, tracking_number))

                '''
                if response['data'].get('shipping_message', ''):
                    picking.message_post(body='Shipping Message for picking {} : {} '
                                         .format(picking.name, response['data'].get('shipping_message', '')))

                if response['data'].get('warehouse_message', ''):
                    picking.message_post(body='Warehouse Sending Message for picking {} : {} '
                                         .format(picking.name, response['data'].get('warehouse_message', '')))

                if response['data'].get('label', ''):
                    pdf_data = base64.b64decode(response['data']['label'])

                    mp_labels = [('%s.%s' % (tracking_number, self.mp_label_format),
                                  pdf_data)]

                    picking.message_post(body='MP Delivery Documents', attachments=mp_labels)
                '''

                shipping_data = {
                    'exact_price': 0,
                    'tracking_number': tracking_number,
                }

                res.append(shipping_data)

        return res

    def mp_get_return_label(self, picking, tracking_number=None, origin_date=None):
        return super(Providermp, self).get_return_label(picking, tracking_number, origin_date)

    def mp_get_tracking_link(self, picking):
        return 'http://www.dhl.com/en/express/tracking.html?AWB=%s' % picking.carrier_tracking_ref

    def mp_cancel_shipment(self, picking):
        # Obviously you need a pick up date to delete SHIPMENT by DHL. So you can't do it if you didn't schedule a pick-up.
        picking.message_post(body=_(u"You can't cancel MP shipping without pickup date."))
        picking.write({'carrier_tracking_ref': '',
                       'carrier_price': 0.0})

    def _mp_convert_weight(self, weight, unit):
        weight_uom_id = self.env['product.template']._get_weight_uom_id_from_ir_config_parameter()
        weight = weight_uom_id._compute_quantity(weight, self.env.ref('uom.product_uom_kgm'), round=False)
        return float_repr(weight, 3)

    def _mp_add_custom_data_to_request(self, request, request_type):
        """Adds the custom data to the request.
        When there are multiple items in a list, they will all be affected by
        the change.
        for example, with
        {"ShipmentDetails": {"Pieces": {"Piece": {"AdditionalInformation": "custom info"}}}}
        the AdditionalInformation of each piece will be updated.
        """
        if not self.mp_custom_data_request:
            return
        try:
            custom_data = const_eval('{%s}' % self.mp_custom_data_request).get(request_type, {})
        except SyntaxError:
            raise UserError(_('Invalid syntax for DHL custom data.'))

        def extra_data_to_request(request, custom_data):
            """recursive function that adds custom data to the current request."""
            for key, new_value in custom_data.items():
                request[key] = current_value = serialize_object(request.get(key, {})) or None
                if isinstance(current_value, list):
                    for item in current_value:
                        extra_data_to_request(item, new_value)
                elif isinstance(new_value, dict) and isinstance(current_value, dict):
                    extra_data_to_request(current_value, new_value)
                else:
                    request[key] = new_value

        extra_data_to_request(request, custom_data)

    def _mp_calculate_value(self, picking):
        sale_order = picking.sale_id
        if sale_order:
            total_value = sum(line.price_reduce_taxinc * line.product_uom_qty for line in
                              sale_order.order_line.filtered(
                                  lambda l: l.product_id.type in ('consu', 'product') and not l.display_type))
            currency_name = picking.sale_id.currency_id.name
        else:
            total_value = sum([line.product_id.lst_price * line.product_qty for line in picking.move_ids])
            currency_name = picking.company_id.currency_id.name
        return total_value, currency_name
