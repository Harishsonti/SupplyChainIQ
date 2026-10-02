CREATE OR REPLACE TABLE SUPPLYCHAINIQ_COCO.ONTOLOGY.ENTITY_RELATIONSHIPS (
    SUBJECT_ENTITY VARCHAR,
    RELATIONSHIP VARCHAR,
    OBJECT_ENTITY VARCHAR,
    CARDINALITY VARCHAR,
    DESCRIPTION VARCHAR
);

INSERT INTO SUPPLYCHAINIQ_COCO.ONTOLOGY.ENTITY_RELATIONSHIPS VALUES
    ('CUSTOMER',          'PLACES',        'ORDER',       '1:N',  'A customer places one or more orders'),
    ('ORDER',             'CONTAINS',      'ORDER_ITEM',  '1:N',  'An order contains one or more order items'),
    ('PRODUCT',           'APPEARS_IN',    'ORDER_ITEM',  '1:N',  'A product appears in DataCo order items'),
    ('SUPPLIER',          'PROVIDES',      'SHIPMENT',    '1:N',  'A supplier/vendor provides SCMS shipment lines'),
    ('MANUFACTURING_SITE','PRODUCES_FOR',  'SHIPMENT',    '1:N',  'A manufacturing site is associated with SCMS shipments'),
    ('SHIPMENT',          'DESTINED_FOR',  'GEOGRAPHY',   'N:1',  'An SCMS shipment is destined for a country'),
    ('ORDER',             'LOCATED_IN',    'GEOGRAPHY',   'N:1',  'A DataCo order is associated with a destination country'),
    ('ORDER_ITEM',        'HAS_DELIVERY',  'ORDER_ITEM',  '1:1',  'Delivery performance is an attribute of the order item itself'),
    ('SHIPMENT',          'HAS_LOGISTICS', 'LOGISTICS',   '1:1',  'Logistics/cost attributes are derived from the same shipment grain');
