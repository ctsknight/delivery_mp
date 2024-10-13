# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import base64
import json

import requests
from datetime import datetime, date, timedelta

from odoo import _
from odoo.exceptions import UserError
from odoo.tools import float_repr, float_round


class MPProvider():

    def __init__(self, debug_logger, username, password):
        self.debug_logger = debug_logger
        self.url = 'http://logistic-center.multipunkt.de/api/odoo/logistics'
        self.headers = {
            'Authorization': 'Basic ' + base64.b64encode((username + ':' + password).encode('utf-8')).decode('utf-8'),
            'Content-type': 'application/json',
            'Accept': 'application/json'}

    def call_shipping_remote(self, data):
        self.debug_logger.info("start call remote api %s........", data)
        response = requests.post(self.url, headers=self.headers, data=json.dumps(data))
        if response.status_code != 200:
            raise UserError(response.text)
        else:
            return response.json()

    def _set_consignee(self, partner_id):
        consignee = {}
        consignee['CompanyName'] = partner_id.commercial_company_name or partner_id.name
        consignee['AddressLine1'] = partner_id.street or partner_id.street2
        consignee['AddressLine2'] = partner_id.street and partner_id.street2 or None
        consignee['City'] = partner_id.city
        if partner_id.state_id:
            consignee['Division'] = partner_id.state_id.name
            consignee['DivisionCode'] = partner_id.state_id.code
        consignee['PostalCode'] = partner_id.zip
        consignee['CountryCode'] = partner_id.country_id.code
        consignee['CountryName'] = partner_id.country_id.name
        consignee['PersonName'] = partner_id.name
        consignee['PhoneNumber'] = partner_id.phone
        if partner_id.email:
            consignee['Email'] = partner_id.email
        return consignee

    def _set_dct_to(self, partner_id):
        country_code = partner_id.country_id.code
        zip_code = partner_id.zip or ''
        return {
            'country_code': country_code,
            'zip_code': zip_code,
            'city': partner_id.city,
        }

    def _set_shipper(self, company_partner_id, warehouse_partner_id):
        shipper = {}
        shipper['CompanyName'] = company_partner_id.name
        shipper['AddressLine1'] = warehouse_partner_id.street or warehouse_partner_id.street2
        shipper['AddressLine2'] = warehouse_partner_id.street and warehouse_partner_id.street2 or None
        shipper['City'] = warehouse_partner_id.city
        if warehouse_partner_id.state_id:
            shipper['Division'] = warehouse_partner_id.state_id.name
            shipper['DivisionCode'] = warehouse_partner_id.state_id.code
        shipper['PostalCode'] = warehouse_partner_id.zip
        shipper['CountryCode'] = warehouse_partner_id.country_id.code
        shipper['CountryName'] = warehouse_partner_id.country_id.name
        shipper['PersonName'] = warehouse_partner_id.name
        shipper['PhoneNumber'] = warehouse_partner_id.phone

        if warehouse_partner_id.email:
            shipper['Email'] = warehouse_partner_id.email
        return shipper

    def _set_dct_from(self, warehouse_partner_id):

        return {
            'country_code': warehouse_partner_id.country_id.code,
            'zip_code': warehouse_partner_id.zip,
            'city': warehouse_partner_id.city,
        }

    def _set_dct_bkg_details(self, carrier, packages):
        bkg_details = {}
        bkg_details['PaymentCountryCode'] = packages[0].company_id.partner_id.country_id.code
        bkg_details['DimensionUnit'] = "CM" if carrier.mp_package_dimension_unit == "C" else "IN"
        bkg_details['WeightUnit'] = "KG" if carrier.mp_package_weight_unit == "K" else "LB"
        bkg_details['InsuredValue'] = float_repr(
            sum(pkg.total_cost for pkg in packages) * carrier.shipping_insurance / 100, precision_digits=3)
        bkg_details['InsuredCurrency'] = packages[0].currency_id.name
        pieces = []
        total_weight = 0
        for sequence, package in enumerate(packages):
            piece = {}
            piece['PieceID'] = sequence
            piece['PackageTypeCode'] = package.packaging_type
            piece['Height'] = package.dimension['height']
            piece['Depth'] = package.dimension['length']
            piece['Width'] = package.dimension['width']
            piece['Weight'] = carrier._mp_convert_weight(package.weight, carrier.mp_package_weight_unit)
            pieces.append(piece)
            total_weight += float(piece['Weight'])
        bkg_details['Pieces'] = {'Piece': pieces}
        return bkg_details, total_weight

    def _set_shipment_details(self, picking):
        package_infos = []
        total_weight = 0
        packages = picking.carrier_id._get_packages_from_picking(picking, picking.carrier_id.mp_default_package_type_id)
        for sequence, package in enumerate(packages):
            goods = []
            for customs_item_id, commodity in enumerate(package.commodities):
                customs_info = {
                    'name': commodity.product_id.name,
                    'quantity': commodity.qty,
                    'code': commodity.product_id.code,
                    'weight': commodity.product_id.weight,
                }
                goods.append(customs_info)
            package_weight = picking.carrier_id._mp_convert_weight(package.weight, picking.carrier_id.mp_package_weight_unit)
            package_infos.append({
                'height': package.dimension['height'],
                'depth': package.dimension['length'],
                'width': package.dimension['width'],
                'Weight': package_weight,
                'goods': goods,
            })
            total_weight += float(package_weight)

        return {
            'total_weight': total_weight,
            'package_infos': package_infos
        }

    def _set_label(self, label):
        return label

    def check_required_value(self, carrier, recipient, shipper, order=False, picking=False):
        carrier = carrier.sudo()
        recipient_required_field = ['city', 'zip', 'country_id']
        if not carrier.mp_username:
            return _("MP Username missing, please modify your delivery method settings.")
        if not carrier.mp_password:
            return _("MP password is missing, please modify your delivery method settings.")

        # The street isn't required if we compute the rate with a partial delivery address in the
        # express checkout flow.
        if not recipient.street and not recipient.street2 and not recipient._context.get(
                'express_checkout_partial_delivery_address', False
        ):
            recipient_required_field.append('street')
        res = [field for field in recipient_required_field if not recipient[field]]
        if res:
            return _("The address of the customer is missing or wrong (Missing field(s) :\n %s)") % ", ".join(
                res).replace("_id", "")

        shipper_required_field = ['city', 'zip', 'phone', 'country_id']
        if not shipper.street and not shipper.street2:
            shipper_required_field.append('street')

        res = [field for field in shipper_required_field if not shipper[field]]
        if res:
            return _("The address of your company warehouse is missing or wrong (Missing field(s) :\n %s)") % ", ".join(
                res).replace("_id", "")

        if order:
            if not order.order_line:
                return _("Please provide at least one item to ship.")
            error_lines = order.order_line.filtered(lambda
                                                        line: not line.product_id.weight and not line.is_delivery and line.product_id.type != 'service' and not line.display_type)
            if error_lines:
                return _(
                    "The estimated shipping price cannot be computed because the weight is missing for the following product(s): \n %s") % ", ".join(
                    error_lines.product_id.mapped('name'))
        return False

    def _set_export_declaration(self, carrier, picking, is_return=False):
        export_lines = []
        move_lines = picking.move_line_ids.filtered(lambda line: line.product_id.type in ['product', 'consu'])
        currency_id = picking.sale_id and picking.sale_id.currency_id or picking.company_id.currency_id
        for sequence, line in enumerate(move_lines, start=1):
            if line.move_id.sale_line_id:
                unit_quantity = line.product_uom_id._compute_quantity(line.qty_done,
                                                                      line.move_id.sale_line_id.product_uom)
            else:
                unit_quantity = line.product_uom_id._compute_quantity(line.qty_done, line.product_id.uom_id)
            rounded_qty = max(1, float_round(unit_quantity, precision_digits=0, rounding_method='HALF-UP'))
            item = self.factory.ExportLineItem()
            item.LineNumber = sequence
            item.Quantity = int(rounded_qty)
            item.QuantityUnit = 'PCS'  # Pieces - very generic
            if len(line.product_id.name) > 75:
                raise UserError(_("MP doesn't support products with name greater than 75 characters."))
            item.Description = line.product_id.name
            item.Value = float_repr(line.sale_price / rounded_qty, currency_id.decimal_places)
            item.Weight = item.GrossWeight = {
                "Weight": carrier._mp_convert_weight(line.product_id.weight, carrier.mp_package_weight_unit),
                "WeightUnit": carrier.mp_package_weight_unit,
            }
            item.ManufactureCountryCode = line.product_id.country_of_origin.code or line.picking_id.picking_type_id.warehouse_id.partner_id.country_id.code
            if line.product_id.hs_code:
                item.ImportCommodityCode = line.product_id.hs_code
                item.CommodityCode = line.product_id.hs_code
            export_lines.append(item)

        export_declaration = self.factory.ExportDeclaration()
        export_declaration.InvoiceDate = datetime.today()
        export_declaration.InvoiceNumber = carrier.env['ir.sequence'].sudo().next_by_code(
            'delivery_mp.commercial_invoice')
        if is_return:
            export_declaration.ExportReason = 'RETURN'

        export_declaration.ExportLineItem = export_lines
        if picking.sale_id.client_order_ref:
            export_declaration.ReceiverReference = picking.sale_id.client_order_ref
        return export_declaration
