-- One row per order: the most recent review (Olist has a few orders with 2+ reviews).
with reviews as (
    select * from {{ ref('stg_olist__reviews') }}
),

ranked as (
    select
        *,
        row_number() over (
            partition by order_id order by created_at desc, answered_at desc, review_id
        ) as recency_rank
    from reviews
)

select
    order_id,
    review_id,
    review_score,
    has_comment,
    created_at as reviewed_at
from ranked
where recency_rank = 1
