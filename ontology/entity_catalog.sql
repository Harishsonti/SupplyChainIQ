CREATE OR REPLACE TABLE SUPPLYCHAINIQ_COCO.ONTOLOGY.ENTITY_CATALOG (
    ENTITY_NAME VARCHAR,
    GRAIN VARCHAR,
    PRIMARY_KEY VARCHAR,
    SOURCE_SYSTEM VARCHAR,
    CORE_TABLE VARCHAR,
    DESCRIPTION VARCHAR
);

INSERT INTO SUPPLYCHAINIQ_COCO.ONTOLOGY.ENTITY_CATALOG VALUES
    ('CUSTOMER',          'Customer',                 'CUSTOMER_ID',        'DataCo', 'CORE.CUSTOMER_DIM',          'A DataCo customer who places orders'),
    ('PRODUCT',           'Product card',             'PRODUCT_CARD_ID',    'DataCo', 'CORE.PRODUCT_DIM',           'A DataCo product in the catalog'),
    ('ORDER',             'Customer order',           'ORDER_ID',           'DataCo', 'CORE.ORDER_ITEM_FACT',       'A DataCo customer order (derived by grouping order items)'),
    ('ORDER_ITEM',        'Order line item',          'ORDER_ITEM_ID',      'DataCo', 'CORE.ORDER_ITEM_FACT',       'A single line item within a DataCo order'),
    ('SUPPLIER',          'Vendor/supplier',          'VENDOR_NAME',        'SCMS',   'CORE.SUPPLIER_DIM',          'An SCMS pharmaceutical supplier/vendor'),
    ('MANUFACTURING_SITE','Manufacturing facility',   'SITE_NAME',          'SCMS',   'CORE.MANUFACTURING_SITE_DIM','An SCMS manufacturing site/plant'),
    ('SHIPMENT',          'Shipment line',            'SHIPMENT_ID',        'SCMS',   'CORE.SCMS_SHIPMENT_FACT',    'An SCMS procurement shipment line'),
    ('LOGISTICS',         'Shipment cost attributes', 'SHIPMENT_ID',        'SCMS',   'CORE.SCMS_SHIPMENT_FACT',    'Cost and freight attributes of an SCMS shipment (same grain as SHIPMENT)'),
    ('GEOGRAPHY',         'Country',                  'COUNTRY_NAME',       'Both',   'CORE.GEOGRAPHY_DIM',         'A conformed country entity from both DataCo and SCMS');
