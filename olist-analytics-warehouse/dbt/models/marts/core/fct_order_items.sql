{{
    config(
        materialized='incremental',
        unique_key='order_item_key',
        incremental_strategy='delete+insert',
        on_schema_change='append_new_columns'
    )
}}

-- Grain: one row per order line. Incremental: only lines from orders newer than the
-- latest one already loaded are processed on each run (full refresh: dbt build --full-refresh).
with items as (
    select * from {{ ref('stg_olist__order_items') }}
),

orders as (
    select order_id, customer_unique_id, purchased_at, order_date, order_status, is_canceled
    from {{ ref('fct_orders') }}
),

products as (
    select product_id, category from {{ ref('stg_olist__products') }}
)

select
    items.order_item_key,
    items.order_id,
    items.order_item_seq,
    items.product_id,
    items.seller_id,
    orders.customer_unique_id,
    products.category,
    orders.purchased_at,
    orders.order_date,
    orders.order_status,
    orders.is_canceled,
    items.price,
    items.freight_value,
    items.price + items.freight_value as line_value
from items
inner join orders on items.order_id = orders.order_id
left join products on items.product_id = products.product_id

{% if is_incremental() %}
where orders.purchased_at > (select max(purchased_at) from {{ this }})
{% endif %}
