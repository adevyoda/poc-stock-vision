@EndUserText.label : 'POC Stock Vision table'
@AbapCatalog.enhancement.category : #NOT_EXTENSIBLE
@AbapCatalog.tableCategory : #TRANSPARENT
@AbapCatalog.deliveryClass : #A
@AbapCatalog.dataMaintenance : #RESTRICTED
define table zpoc_stock_t {
  key client          : abap.clnt not null;
  key material_number : abap.char(18) not null;
  key warehouse       : abap.char(10) not null;
  quantity            : abap.int4;
  unit                : abap.unit(3);
  detected_at         : abap.utclong;
  source              : abap.char(60);
}
