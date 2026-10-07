with source as (
    select * from {{ source('olist', 'order_items') }}
)

select
    order_id || '-' || order_item_id                            as order_item_key,
    order_id,
    cast(order_item_id as {{ dbt.type_int() }})                 as order_item_seq,
    product_id,
    seller_id,
    cast(shipping_limit_date as {{ dbt.type_timestamp() }})     as shipping_limit_at,
    cast(price as {{ dbt.type_numeric() }})                     as price,
    cast(freight_value as {{ dbt.type_numeric() }})             as freight_value
from source
