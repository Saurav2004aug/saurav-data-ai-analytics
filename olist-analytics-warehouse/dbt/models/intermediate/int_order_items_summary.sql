-- One row per order: basket composition and value.
with items as (
    select * from {{ ref('stg_olist__order_items') }}
),

products as (
    select product_id, category from {{ ref('stg_olist__products') }}
)

select
    items.order_id,
    count(*)                                                        as n_items,
    count(distinct items.product_id)                                as n_distinct_products,
    count(distinct items.seller_id)                                 as n_sellers,
    sum(items.price)                                                as items_value,
    sum(items.freight_value)                                        as freight_value,
    sum(items.price) + sum(items.freight_value)                     as order_value,
    max(case when items.order_item_seq = 1 then products.category end) as main_category,
    max(case when items.order_item_seq = 1 then items.seller_id end)   as main_seller_id
from items
left join products on items.product_id = products.product_id
group by items.order_id
