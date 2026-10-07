-- Grain: one row per seller.
with sellers as (
    select * from {{ ref('stg_olist__sellers') }}
),

regions as (
    select * from {{ ref('brazil_state_regions') }}
)

select
    sellers.seller_id,
    sellers.state_code,
    regions.region,
    sellers.city
from sellers
left join regions on sellers.state_code = regions.state_code
