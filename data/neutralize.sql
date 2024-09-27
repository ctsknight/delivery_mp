-- disable dhl
UPDATE delivery_carrier
SET "mp_SiteID" = 'dummy',
    mp_SiteID_account_number = 'dummy',
    mp_password = 'dummy';
