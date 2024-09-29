-- disable dhl
UPDATE delivery_carrier
SET "mp_username" = 'dummy',
    mp_password = 'dummy';
