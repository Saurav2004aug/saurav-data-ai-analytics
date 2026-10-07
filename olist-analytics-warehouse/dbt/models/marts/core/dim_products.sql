-- Grain: one row per product.
with products as (
    select * from {{ ref('stg_olist__products') }}
),

sales as (
    select
        product_id,
        count(*)                   as units_sold,
        avg(price)                 as avg_price,
        sum(price)                 as revenue
    from {{ ref('stg_olist__order_items') }}
    group by product_id
)

select
    products.product_id,
    products.category,
    products.category_name_pt,
    products.photos_qty,
    products.weight_g,
    products.volume_cm3,
    coalesce(sales.units_sold, 0)  as units_sold,
    sales.avg_price,
    coalesce(sales.revenue, 0)     as revenue
from products
left join sales on products.product_id = sales.product_id
