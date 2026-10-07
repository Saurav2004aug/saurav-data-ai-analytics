-- A delivery can never happen before the purchase.
select order_id, purchased_at, delivered_at
from {{ ref('fct_orders') }}
where delivered_at < purchased_at
