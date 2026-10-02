CREATE OR REPLACE TABLE SUPPLYCHAINIQ_COCO.ONTOLOGY.RELATIONSHIP_GOVERNANCE (
    SUBJECT_ENTITY VARCHAR,
    RELATIONSHIP VARCHAR,
    OBJECT_ENTITY VARCHAR,
    LEFT_KEY VARCHAR,
    RIGHT_KEY VARCHAR,
    STATUS VARCHAR,
    EVIDENCE VARCHAR,
    NOTES VARCHAR
);

INSERT INTO SUPPLYCHAINIQ_COCO.ONTOLOGY.RELATIONSHIP_GOVERNANCE VALUES
    -- SUPPORTED relationships (defensible joins)
    ('CUSTOMER',           'PLACES',       'ORDER',      'CUSTOMER_ID',        'CUSTOMER_ID',        'SUPPORTED',   'Direct FK in ORDER_ITEM_FACT',              'DataCo internal join'),
    ('ORDER',              'CONTAINS',     'ORDER_ITEM', 'ORDER_ID',           'ORDER_ID',           'SUPPORTED',   'Direct FK in ORDER_ITEM_FACT',              'DataCo internal join'),
    ('PRODUCT',            'APPEARS_IN',   'ORDER_ITEM', 'PRODUCT_CARD_ID',    'PRODUCT_CARD_ID',    'SUPPORTED',   'Direct FK in ORDER_ITEM_FACT',              'DataCo internal join'),
    ('SUPPLIER',           'PROVIDES',     'SHIPMENT',   'VENDOR_NAME',        'VENDOR',             'SUPPORTED',   'SCMS source attribute',                     'SCMS internal join'),
    ('MANUFACTURING_SITE', 'PRODUCES_FOR', 'SHIPMENT',   'SITE_NAME',          'MANUFACTURING_SITE', 'SUPPORTED',   'SCMS source attribute',                     'SCMS internal join'),
    ('SHIPMENT',           'DESTINED_FOR', 'GEOGRAPHY',  'COUNTRY',            'COUNTRY_NAME',       'SUPPORTED',   'SCMS country attribute',                    'SCMS to conformed geography'),
    ('ORDER',              'LOCATED_IN',   'GEOGRAPHY',  'CANONICAL_COUNTRY',  'COUNTRY_NAME',       'SUPPORTED',   'DataCo normalized country name',            'DataCo to conformed geography via CANONICAL_COUNTRY'),
    ('ORDER_ITEM',         'HAS_DELIVERY', 'ORDER_ITEM', 'ORDER_ITEM_ID',      'ORDER_ITEM_ID',      'SUPPORTED',   'Delivery is an attribute of the order item','Same grain - no join needed'),
    ('SHIPMENT',           'HAS_LOGISTICS','LOGISTICS',  NULL,                 NULL,                 'SUPPORTED',   'Same SCMS grain - no cross-table join',     'Logistics is a projection of SCMS_SHIPMENT_FACT'),
    -- UNSUPPORTED relationships (no defensible key)
    ('ORDER',              'LINKED_TO',    'SHIPMENT',   NULL,                 NULL,                 'UNSUPPORTED', 'No row-level cross-source key exists',      'DataCo and SCMS are independent source systems with no shared transaction ID'),
    ('SUPPLIER',           'SUPPLIES',     'ORDER',      NULL,                 NULL,                 'UNSUPPORTED', 'No supplier attribute in DataCo',           'SCMS vendors do not appear in DataCo data'),
    ('PRODUCT',            'SHIPPED_AS',   'SHIPMENT',   NULL,                 NULL,                 'UNSUPPORTED', 'No product-to-shipment identifier',         'DataCo products are consumer goods; SCMS items are pharmaceuticals');
