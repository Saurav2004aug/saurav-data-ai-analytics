-- Orders keyed by the real person (customer_unique_id), with their order sequence.
with orders as (
    select * from {{ ref('stg_olist__orders') }}
),

customers as (
    select * from {{ ref('stg_olist__customers') }}
)

select
    orders.order_id,
    customers.customer_unique_id,
    customers.state_code,
    customers.city,
    orders.purchased_at,
    row_number() over (
        partition by customers.customer_unique_id order by orders.purchased_at, orders.order_id
    ) as customer_order_seq
from orders
inner join customers on orders.customer_id = customers.customer_id
