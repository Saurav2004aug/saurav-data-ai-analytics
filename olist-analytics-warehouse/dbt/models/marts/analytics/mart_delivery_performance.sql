-- How delivery timing drives customer satisfaction (delivered orders with a review).
with orders as (
    select * from {{ ref('fct_orders') }}
    where is_delivered = 1 and review_score is not null and delay_days is not null
),

bucketed as (
    select
        *,
        case
            when delay_days <= -15 then '01 >14 days early'
            when delay_days <= -8  then '02 8-14 days early'
            when delay_days <= -1  then '03 1-7 days early'
            when delay_days = 0    then '04 on the day'
            when delay_days <= 3   then '05 1-3 days late'
            when delay_days <= 7   then '06 4-7 days late'
            when delay_days <= 14  then '07 8-14 days late'
            else '08 >14 days late'
        end as delay_bucket
    from orders
)

select
    delay_bucket,
    count(*)                                                           as orders,
    avg(review_score)                                                  as avg_review_score,
    {{ safe_divide('sum(case when review_score = 1 then 1 else 0 end)', 'count(*)') }} as one_star_rate,
    {{ safe_divide('sum(case when review_score = 5 then 1 else 0 end)', 'count(*)') }} as five_star_rate,
    {{ safe_divide('sum(review_has_comment)', 'count(*)') }}           as comment_rate
from bucketed
group by delay_bucket
