with source as (
    select * from {{ source('olist', 'order_reviews') }}
)

select
    review_id,
    order_id,
    cast(review_score as {{ dbt.type_int() }})                   as review_score,
    case when review_comment_message is not null
              and length(trim(review_comment_message)) > 0
         then 1 else 0 end                                       as has_comment,
    cast(review_creation_date as {{ dbt.type_timestamp() }})     as created_at,
    cast(review_answer_timestamp as {{ dbt.type_timestamp() }})  as answered_at
from source
