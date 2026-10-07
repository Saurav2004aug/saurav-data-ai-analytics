-- Executive KPIs by month. Revenue = merchandise + freight of orders not canceled.
with orders as (
    select * from {{ ref('fct_orders') }}
),

monthly as (
    select
        order_month,
        count(*)                                                        as orders,
        sum(case when is_canceled = 0 then 1 else 0 end)                as valid_orders,
        count(distinct customer_unique_id)                              as active_customers,
        sum(is_first_order)                                             as new_customers,
        sum(case when is_canceled = 0 then order_value else 0 end)      as revenue,
        sum(case when is_canceled = 0 then freight_value else 0 end)    as freight_revenue,
        avg(review_score)                                               as avg_review_score,
        {{ safe_divide('sum(is_late)', 'sum(is_delivered)') }}          as late_delivery_rate,
        {{ safe_divide('sum(is_canceled)', 'count(*)') }}               as cancellation_rate,
        avg(case when is_delivered = 1 then delivery_days end)          as avg_delivery_days
    from orders
    group by order_month
)

select
    order_month,
    orders,
    valid_orders,
    active_customers,
    new_customers,
    active_customers - new_customers                                    as returning_customers,
    revenue,
    {{ safe_divide('revenue', 'valid_orders') }}                        as avg_order_value,
    {{ safe_divide('freight_revenue', 'revenue') }}                     as freight_share,
    avg_review_score,
    late_delivery_rate,
    cancellation_rate,
    avg_delivery_days,
    {{ safe_divide('revenue - lag(revenue) over (order by order_month)',
                   'lag(revenue) over (order by order_month)') }}       as revenue_mom_growth
from monthly
