# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': "MP Shipping",
    'description': "Send your shippings through MP and track them online",
    'category': 'Inventory/Delivery',
    'author': "Mulitpunkt",
 #   'sequence': 285,
    'version': '1.0',
    'application': True,
    'depends': ['delivery', 'mail'],
    'data': [
        'data/delivery_mp_data.xml',
        'views/delivery_mp_view.xml',
       ## 'views/res_config_settings_views.xml',
    ],
    'license': 'OEEL-1',
}
