-- Delivery and satisfaction by customer state - where logistics hurts the most.
with orders as (
    select * from {{ ref('fct_orders') }}
),

regions as (
    select * from {{ ref('brazil_state_regions') }}
)

select
    orders.customer_state                                                  as state_code,
    regions.state_name,
    regions.region,
    count(*)                                                               as orders,
    sum(case when orders.is_canceled = 0 then orders.order_value else 0 end) as revenue,
    avg(case when orders.is_delivered = 1 then orders.delivery_days end)   as avg_delivery_days,
    {{ safe_divide('sum(orders.is_late)', 'sum(orders.is_delivered)') }}   as late_delivery_rate,
    avg(orders.review_score)                                               as avg_review_score,
    {{ safe_divide('avg(orders.freight_value)', 'avg(orders.items_value)') }} as freight_to_price_ratio
from orders
left join regions on orders.customer_state = regions.state_code
group by 1, 2, 3
