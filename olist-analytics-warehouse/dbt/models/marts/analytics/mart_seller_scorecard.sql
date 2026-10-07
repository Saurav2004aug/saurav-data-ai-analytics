-- Seller scorecard with a tier, for marketplace operations.
with items as (
    select * from {{ ref('fct_order_items') }}
    where is_canceled = 0
),

orders as (
    select order_id, is_late, is_delivered, review_score, shipped_at, approved_at
    from {{ ref('fct_orders') }}
),

sellers as (
    select * from {{ ref('dim_sellers') }}
),

seller_orders as (
    select distinct items.seller_id, items.order_id
    from items
),

agg as (
    select
        seller_orders.seller_id,
        count(*)                                                        as orders,
        avg(orders.review_score)                                        as avg_review_score,
        {{ safe_divide('sum(orders.is_late)', 'sum(orders.is_delivered)') }} as late_delivery_rate,
        avg({{ dbt.datediff('orders.approved_at', 'orders.shipped_at', 'day') }}) as avg_days_to_ship
    from seller_orders
    inner join orders on seller_orders.order_id = orders.order_id
    group by seller_orders.seller_id
),

revenue as (
    select seller_id, sum(price) as revenue, count(*) as units
    from items
    group by seller_id
)

select
    sellers.seller_id,
    sellers.state_code,
    sellers.region,
    agg.orders,
    revenue.units,
    revenue.revenue,
    agg.avg_review_score,
    agg.late_delivery_rate,
    agg.avg_days_to_ship,
    case
        when agg.orders < 10                                             then 'New / low volume'
        when agg.avg_review_score >= 4.3 and agg.late_delivery_rate <= 0.08 then 'Gold'
        when agg.avg_review_score >= 3.8                                 then 'Silver'
        else 'Needs attention'
    end as tier
from sellers
inner join agg on sellers.seller_id = agg.seller_id
inner join revenue on sellers.seller_id = revenue.seller_id
