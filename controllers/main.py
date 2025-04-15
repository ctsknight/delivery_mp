# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import base64
import json
import logging

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class DeliveryMPController(http.Controller):

    def _validate_basic_auth(self):
        """Validate the Basic Authentication credentials"""
        _logger.info("Validating Basic Authentication")
        auth_header = request.httprequest.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Basic '):
            _logger.warning("Missing or invalid Authorization header")
            return False
        
        try:
            # Decode the Authorization header to get username and password
            auth_decoded = base64.b64decode(auth_header.split(' ')[1]).decode('utf-8')
            username, password = auth_decoded.split(':', 1)
            _logger.info(f"Authentication attempt with username: {username}")
            
            # Validate user credentials using Odoo's authentication
            if username == 'Mulitpunkt' and password == '77hk-4iix-p38r':
                _logger.info("Basic Authentication successful")
                return True
            else:
                _logger.warning(f"Invalid credentials for user: {username}")
                return False
        except Exception as e:
            _logger.error(f"Error during Basic Authentication: {str(e)}")
            return False

    @http.route('/delivery_mp/tracking_update', type='json', auth='none', csrf=False, methods=['POST'])
    def update_tracking_number(self, **post):
        """Endpoint for third-party providers to update tracking numbers
        
        Expected JSON payload:
        {
            "reference": "picking_name_or_sale_order_reference",
            "tracking_numbers": ["tracking_number1", "tracking_number2", ...],
            "shipping_method": "shipper_package_code",
            "provider": "provider_code_optional"
        }
        """
        _logger.info("=== Tracking update API call received ===")
        try:
            # Validate authentication
            if not self._validate_basic_auth():
                _logger.warning("Authentication failed for tracking update request")
                return request.make_response(json.dumps({
                    "status": "error",
                    "message": 'Invalid username or password'
                }), headers={'Content-Type': 'application/json'}, status=401)

            # Parse the incoming JSON request to get data
            data = request.get_json_data()
            _logger.info(f"Received tracking update data: {data}")

            if not data:
                _logger.error("No data provided in request")
                raise Exception('no data provided')

            # Validate required fields
            _logger.info("Validating required fields")
            if not all(key in data for key in ['name', 'origin', 'tracking_numbers', 'shipping_method', 'delivery_date']):
                missing_fields = [field for field in ['name', 'origin', 'tracking_numbers', 'shipping_method'] if field not in data]
                _logger.warning(f"Missing required fields: {', '.join(missing_fields)}")
                return request.make_response(json.dumps({
                    "status": "error",
                    "message": "Missing required fields: name, origin, tracking_numbers and shipping_method are "
                               "required"
                }), headers={'Content-Type': 'application/json'}, status=200)

            # Validate tracking_numbers is an array
            if not isinstance(data.get('tracking_numbers'), list):
                _logger.warning("tracking_numbers is not an array")
                return request.make_response(json.dumps({
                    "status": "error",
                    "message": "tracking_numbers must be an array"
                }), headers={'Content-Type': 'application/json'}, status=200)

            # Search for the picking using the reference
            _logger.info(f"Searching for picking with origin: {data.get('origin')} and name: {data.get('name')}")
            picking = request.env['stock.picking'].sudo().search([
                ('origin', '=', data.get('origin')),
                ('name', '=', data.get('name'))
            ], limit=1)

            if not picking:
                _logger.warning(f"Picking not found for origin: {data.get('origin')} and name: {data.get('name')}")
                return request.make_response(json.dumps({
                    "status": "error",
                    "message": f"Picking not found for origin: {data.get('origin')} and name: {data.get('name')}"
                }), headers={'Content-Type': 'application/json'}, status=200)
            
            _logger.info(f"Found picking: {picking.name} (ID: {picking.id})")

            # Check if carrier needs to be updated
            carrier_update_needed = False
            carrier = None
            shipping_method = data.get('shipping_method')
            schedule_date = data.get('delivery_date')
            _logger.info(f"Processing shipping method: {shipping_method}, schedule_date: {schedule_date}")

            if schedule_date:
                picking.write({'scheduled_date': schedule_date})

            if shipping_method:
                # First, search for a package type with matching shipper_package_code
                _logger.info(f"Searching for package type with shipper_package_code: {shipping_method}")
                package_type = request.env['stock.package.type'].sudo().search([
                    ('shipper_package_code', '=', shipping_method),
                    ('package_carrier_type', '=', 'mp')
                ], limit=1)
                
                if package_type:
                    _logger.info(f"Found package type: {package_type.name} (ID: {package_type.id})")
                    
                    # Find carrier with this package type as mp_default_package_type_id
                    _logger.info(f"Searching for carrier with mp_default_package_type_id: {package_type.id}")
                    carrier = request.env['delivery.carrier'].sudo().search([
                        ('mp_default_package_type_id', '=', package_type.id),
                        ('delivery_type', '=', 'mp')
                    ], limit=1)
                    
                    if carrier:
                        _logger.info(f"Found carrier: {carrier.name} (ID: {carrier.id})")
                        # Check if carrier exists and needs to be updated
                        if not picking.carrier_id:
                            _logger.info("Picking has no carrier assigned, will update")
                            carrier_update_needed = True
                        elif picking.carrier_id.id != carrier.id:
                            _logger.info(f"Picking has different carrier: {picking.carrier_id.name}, will update")
                            carrier_update_needed = True
                        else:
                            _logger.info("Picking already has the correct carrier, no update needed")
                    else:
                        _logger.warning(f"No carrier found for package type: {package_type.name}")
                else:
                    _logger.warning(f"No package type found with shipper_package_code: {shipping_method}")
                    
                    # Fallback: Try to search by carrier name or delivery_type
                    _logger.info(f"Trying fallback search for carrier by name or delivery_type: {shipping_method}")
                    carrier = request.env['delivery.carrier'].sudo().search([
                        '|',
                        ('name', '=', shipping_method),
                        ('delivery_type', '=', shipping_method)
                    ], limit=1)
                    
                    if carrier:
                        _logger.info(f"Found carrier through fallback search: {carrier.name} (ID: {carrier.id})")
                        if not picking.carrier_id:
                            _logger.info("Picking has no carrier assigned, will update")
                            carrier_update_needed = True
                        elif picking.carrier_id.id != carrier.id:
                            _logger.info(f"Picking has different carrier: {picking.carrier_id.name}, will update")
                            carrier_update_needed = True
                        else:
                            _logger.info("Picking already has the correct carrier, no update needed")

            # Prepare update data
            _logger.info("Preparing update data")
            update_data = {'carrier_tracking_ref': ''}  # Clear existing tracking numbers first

            # Update carrier if needed
            if carrier_update_needed and carrier:
                _logger.info(f"Will update carrier to: {carrier.name}")
                update_data['carrier_id'] = carrier.id

            # Apply the first update
            _logger.info(f"Applying initial update: {update_data}")
            picking.write(update_data)

            # Join the new tracking numbers with comma separator
            tracking_numbers = data.get('tracking_numbers')
            _logger.info(f"Processing tracking numbers: {tracking_numbers}")
            joined_tracking_numbers = ','.join(tracking_numbers) if tracking_numbers else ''

            # Update with the new tracking numbers
            _logger.info(f"Updating tracking numbers to: {joined_tracking_numbers}")
            picking.write({
                'carrier_tracking_ref': joined_tracking_numbers
            })

            # Add a note in the chatter
            message_parts = [f"Tracking numbers updated to {joined_tracking_numbers}"]

            if carrier_update_needed and carrier:
                message_parts.append(f"Carrier updated to {carrier.name}")

            message = f"{' and '.join(message_parts)} via API"
            _logger.info(f"Adding chatter message: {message}")
            picking.message_post(
                body=message,
                subtype_xmlid="mail.mt_note"
            )

            _logger.info("Preparing response data")
            response_data = {
                'success': True,
                'message': f"Updates applied for {picking.name}",
                'picking_id': picking.id,
                'tracking_numbers': tracking_numbers
            }

            if carrier:
                response_data['carrier'] = {
                    'id': carrier.id,
                    'name': carrier.name
                }
                if hasattr(carrier, 'mp_default_package_type_id') and carrier.mp_default_package_type_id:
                    response_data['package_type'] = {
                        'id': carrier.mp_default_package_type_id.id,
                        'name': carrier.mp_default_package_type_id.name,
                        'shipper_package_code': carrier.mp_default_package_type_id.shipper_package_code
                    }

            _logger.info("Successfully processed tracking update")
            return request.make_response(json.dumps({
                "status": "success",
            }), headers={'Content-Type': 'application/json'}, status=200)

        except Exception as e:
            _logger.exception(f"Error while processing tracking update: {str(e)}")
            return request.make_response(json.dumps({
                "status": "error",
                "message": str(e)
            }), headers={'Content-Type': 'application/json'}, status=200)