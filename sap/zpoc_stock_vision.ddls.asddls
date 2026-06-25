@AccessControl.authorizationCheck: #NOT_REQUIRED
@EndUserText.label: 'Stock Vision - camera inventory'
define root view entity ZPOC_STOCK_VISION
  as select from zpoc_stock_t
{
  key material_number as MaterialNumber,
  key warehouse       as Warehouse,
      quantity        as Quantity,
      unit            as Unit,
      detected_at     as DetectedAt,
      source          as Source
}
