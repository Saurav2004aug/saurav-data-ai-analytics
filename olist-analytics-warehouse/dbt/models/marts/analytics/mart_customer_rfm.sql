-- RFM segmentation. Olist is ~97% one-time buyers, so Frequency uses fixed buckets
-- (1 / 2 / 3+) instead of quintiles, which would be meaningless here.
with customers as (
    select * from {{ ref('dim_customers') }}
    where n_valid_orders > 0
),

snapshot as (
    select max(purchased_at) as as_of from {{ ref('fct_orders') }}
),

base as (
    select
        customers.customer_unique_id,
        customers.state_code,
        customers.region,
        {{ dbt.datediff('customers.last_order_at', 'snapshot.as_of', 'day') }} as recency_days,
        customers.n_valid_orders                                               as frequency,
        customers.lifetime_value                                               as monetary
    from customers
    cross join snapshot
),

scored as (
    select
        *,
        6 - ntile(5) over (order by recency_days)      as r_score,   -- 5 = most recent
        case when frequency >= 3 then 3 when frequency = 2 then 2 else 1 end as f_score,
        ntile(5) over (order by monetary)               as m_score    -- 5 = highest spend
    from base
)

select
    *,
    case
        when f_score >= 2 and r_score >= 4                   then 'Champions'
        when f_score >= 2                                     then 'Loyal - at risk'
        when r_score >= 4 and m_score >= 4                    then 'Promising big spenders'
        when r_score >= 4                                     then 'Recent one-timers'
        when r_score = 3                                      then 'Cooling down'
        when m_score >= 4                                     then 'Lost big spenders'
        else 'Hibernating'
    end as segment
from scored
