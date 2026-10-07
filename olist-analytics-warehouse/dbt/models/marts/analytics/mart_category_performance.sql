-- Category-level revenue, pricing and satisfaction.
with items as (
    select * from {{ ref('fct_order_items') }}
    where is_canceled = 0
),

orders as (
    select order_id, review_score, is_late from {{ ref('fct_orders') }}
),

agg as (
    select
        items.category,
        count(distinct items.order_id)       as orders,
        count(*)                             as units,
        sum(items.price)                     as revenue,
        avg(items.price)                     as avg_price,
        avg(items.freight_value)             as avg_freight,
        avg(orders.review_score)             as avg_review_score,
        avg(orders.is_late)                  as late_delivery_rate
    from items
    inner join orders on items.order_id = orders.order_id
    group by items.category
)

select
    *,
    {{ safe_divide('revenue', 'sum(revenue) over ()') }} as revenue_share,
    rank() over (order by revenue desc)                  as revenue_rank
from agg
