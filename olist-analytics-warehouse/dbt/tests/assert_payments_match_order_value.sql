{{ config(severity='warn', warn_if='>50') }}
-- Paid amount should equal merchandise + freight. Olist has known small mismatches
-- (voucher rounding), so this warns rather than fails; > 50 mismatches means a real problem.
select order_id, order_value, total_paid
from {{ ref('fct_orders') }}
where total_paid is not null
  and n_items > 0
  and abs(total_paid - order_value) > 1.0
