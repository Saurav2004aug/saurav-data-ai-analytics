{{ config(materialized='table') }}

-- Grain: one row per order. The central fact table of the warehouse.
with orders as (
    select * from {{ ref('stg_olist__orders') }}
),

customer_orders as (
    select * from {{ ref('int_customer_orders') }}
),

items as (
    select * from {{ ref('int_order_items_summary') }}
),

payments as (
    select * from {{ ref('int_order_payments') }}
),

reviews as (
    select * from {{ ref('int_order_reviews') }}
)

select
    orders.order_id,
    customer_orders.customer_unique_id,
    customer_orders.customer_order_seq,
    case when customer_orders.customer_order_seq = 1 then 1 else 0 end   as is_first_order,
    customer_orders.state_code                                           as customer_state,
    orders.order_status,

    -- dates
    orders.purchased_at,
    {{ to_date('orders.purchased_at') }}                                 as order_date,
    {{ to_date(dbt.date_trunc('month', 'orders.purchased_at')) }}        as order_month,
    orders.approved_at,
    orders.shipped_at,
    orders.delivered_at,
    orders.estimated_delivery_at,

    -- basket
    coalesce(items.n_items, 0)                                           as n_items,
    items.n_sellers,
    items.main_category,
    items.main_seller_id,
    coalesce(items.items_value, 0)                                       as items_value,
    coalesce(items.freight_value, 0)                                     as freight_value,
    coalesce(items.order_value, 0)                                       as order_value,

    -- payment
    payments.total_paid,
    payments.primary_payment_type,
    payments.max_installments,
    coalesce(payments.used_voucher, 0)                                   as used_voucher,

    -- delivery performance (days; positive delay = late)
    {{ dbt.datediff('orders.purchased_at', 'orders.delivered_at', 'day') }}          as delivery_days,
    {{ dbt.datediff('orders.purchased_at', 'orders.estimated_delivery_at', 'day') }} as promised_days,
    {{ dbt.datediff('orders.estimated_delivery_at', 'orders.delivered_at', 'day') }} as delay_days,
    case
        when orders.delivered_at is null then null
        when {{ dbt.datediff('orders.estimated_delivery_at', 'orders.delivered_at', 'day') }}
             > {{ var('late_grace_days') }} then 1
        else 0
    end                                                                  as is_late,

    -- status flags
    case when orders.order_status = 'delivered' then 1 else 0 end        as is_delivered,
    case when orders.order_status in ('canceled', 'unavailable') then 1 else 0 end as is_canceled,

    -- satisfaction
    reviews.review_score,
    reviews.has_comment                                                  as review_has_comment
from orders
inner join customer_orders on orders.order_id = customer_orders.order_id
left join items on orders.order_id = items.order_id
left join payments on orders.order_id = payments.order_id
left join reviews on orders.order_id = reviews.order_id
