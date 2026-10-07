-- Grain: one row per real customer (customer_unique_id).
with customer_orders as (
    select * from {{ ref('int_customer_orders') }}
),

orders as (
    select * from {{ ref('fct_orders') }}
),

regions as (
    select * from {{ ref('brazil_state_regions') }}
),

first_order as (
    select customer_unique_id, state_code, city
    from customer_orders
    where customer_order_seq = 1
),

order_stats as (
    select
        customer_unique_id,
        min(purchased_at)                                           as first_order_at,
        max(purchased_at)                                           as last_order_at,
        count(*)                                                    as n_orders,
        sum(case when is_canceled = 0 then 1 else 0 end)            as n_valid_orders,
        sum(case when is_canceled = 0 then order_value else 0 end)  as lifetime_value,
        avg(review_score)                                           as avg_review_score,
        sum(case when is_late = 1 then 1 else 0 end)                as n_late_orders
    from orders
    group by customer_unique_id
)

select
    first_order.customer_unique_id,
    first_order.state_code,
    regions.region,
    first_order.city,
    order_stats.first_order_at,
    order_stats.last_order_at,
    {{ to_date(dbt.date_trunc('month', 'order_stats.first_order_at')) }} as cohort_month,
    order_stats.n_orders,
    order_stats.n_valid_orders,
    order_stats.lifetime_value,
    order_stats.avg_review_score,
    order_stats.n_late_orders,
    case when order_stats.n_orders > 1 then 1 else 0 end            as is_repeat_customer
from first_order
inner join order_stats on first_order.customer_unique_id = order_stats.customer_unique_id
left join regions on first_order.state_code = regions.state_code
