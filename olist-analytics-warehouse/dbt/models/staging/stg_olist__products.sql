with products as (
    select * from {{ source('olist', 'products') }}
),

translation as (
    select * from {{ source('olist', 'category_translation') }}
)

select
    products.product_id,
    products.product_category_name                                        as category_name_pt,
    coalesce(translation.product_category_name_english,
             products.product_category_name, 'unknown')                   as category,
    -- the source columns really are misspelled ("lenght"); fixed here, once
    cast(products.product_name_lenght as {{ dbt.type_int() }})            as name_length,
    cast(products.product_description_lenght as {{ dbt.type_int() }})     as description_length,
    cast(products.product_photos_qty as {{ dbt.type_int() }})             as photos_qty,
    cast(products.product_weight_g as {{ dbt.type_numeric() }})           as weight_g,
    cast(products.product_length_cm as {{ dbt.type_numeric() }})
        * cast(products.product_height_cm as {{ dbt.type_numeric() }})
        * cast(products.product_width_cm as {{ dbt.type_numeric() }})     as volume_cm3
from products
left join translation
    on products.product_category_name = translation.product_category_name
