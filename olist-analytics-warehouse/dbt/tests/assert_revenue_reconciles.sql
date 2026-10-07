-- The monthly mart must add up to the order-level fact (no rows lost in aggregation).
with mart as (select sum(revenue) as total from {{ ref('mart_monthly_kpis') }}),
     fact as (select sum(order_value) as total from {{ ref('fct_orders') }} where is_canceled = 0)
select mart.total as mart_total, fact.total as fact_total
from mart cross join fact
where abs(mart.total - fact.total) > 0.01
