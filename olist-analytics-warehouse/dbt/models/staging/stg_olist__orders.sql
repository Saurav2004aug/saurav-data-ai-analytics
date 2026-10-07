with source as (
    select * from {{ source('olist', 'orders') }}
)

select
    order_id,
    customer_id,
    order_status,
    cast(order_purchase_timestamp as {{ dbt.type_timestamp() }})      as purchased_at,
    cast(order_approved_at as {{ dbt.type_timestamp() }})             as approved_at,
    cast(order_delivered_carrier_date as {{ dbt.type_timestamp() }})  as shipped_at,
    cast(order_delivered_customer_date as {{ dbt.type_timestamp() }}) as delivered_at,
    cast(order_estimated_delivery_date as {{ dbt.type_timestamp() }}) as estimated_delivery_at
from source
